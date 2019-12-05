import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
import traceback
import sys
import json
import splunklib
from splunklib.searchcommands import \
    dispatch, GeneratingCommand, Configuration, Option, validators
import logging
import stack_deployment
import os
import errors
import stacks
import clusters
from kubernetes import client as kuberneteslib
import services
import stack_deployment
import app_deployment
import time


def up(splunk, stack_id):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_name = stack_config["cluster"]
    kubernetes = clusters.create_client(splunk, cluster_name)
    cluster_config = clusters.get_cluster_config(splunk, cluster_name)
    status = stack_config["status"]
    if status == stacks.CREATING:
        stack_deployment.create_deployment(
            splunk, kubernetes, stack_id, stack_config, cluster_config)
        logging.info("created")
        stacks.update_config(splunk, stack_id, {
            "status": stacks.CREATED,
        })
    elif status == stacks.CREATED:
        #import instances
        # if stack_config["deployment_type"] == "standalone":
        #    inst = instances.create_client(
        #        core_api, stack_id, stack_config, services.standalone_role)
        # elif stack_config["deployment_type"] == "distributed":
        #    inst = instances.create_client(
        #        core_api, stack_id, stack_config, services.search_head_role)
        # inst.indexes["main"].submit("test")
        # logging.warning("sent")
        app_deployment.update_apps(splunk, kubernetes, stack_id)
    else:
        logging.warning("unexpected status: %s", status)


def down(splunk, stack_id, force=False):
    stacks.update_config(splunk, stack_id, {
        "status": stacks.DELETING,
    })
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_name = stack_config["cluster"]
    api_client = clusters.create_client(splunk, cluster_name)
    core_api = kuberneteslib.CoreV1Api(api_client)
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
    try:
        services.delete_all_load_balancers(
            core_api, stack_id, stack_config["namespace"])
        if stack_deployment.get_splunk(custom_objects_api, stack_id, stack_config):
            stack_deployment.delete_splunk(
                custom_objects_api, stack_id, stack_config)
        if stack_deployment.license_exists(core_api, stack_id, stack_config):
            stack_deployment.delete_license(core_api, stack_id, stack_config)
    except:
        if not force:
            raise
    stacks.update_config(splunk, stack_id, {
        "status": stacks.DELETED,
    })


def get_command_name(stack_id):
    return "stack_operation_%s" % (stack_id)


def schedule_operation(splunk, stack_id, command):
    try:
        unschedule_operation(splunk, stack_id)
    except KeyError:
        pass
    search = splunk.saved_searches.create(
        name=get_command_name(stack_id),
        search="| stackoperation stack_id=\"%s\" command=\"%s\"" % (
            stack_id, command),
        **{
            "cron_schedule": "* * * * *",
            "is_scheduled": 1,
            "schedule_window": "auto",
            "dispatch.auto_cancel": 0,
            "dispatch.auto_pause": 0,
            "dispatch.max_time": 0,
        }
    )
    search.dispatch(
        **{
            "dispatch.now": True,
            "force_dispatch": False,
        }
    )


def unschedule_operation(splunk, stack_id):
    search_name = get_command_name(stack_id)
    splunk.saved_searches.delete(search_name)


def start(splunk, stack_id):
    schedule_operation(splunk, stack_id, "up")


def stop(splunk, stack_id, force=False):
    if force:
        schedule_operation(splunk, stack_id, "kill")
    else:
        schedule_operation(splunk, stack_id, "down")


@Configuration(type='reporting')
class StackOperation(GeneratingCommand):
    command = Option(require=True)
    stack_id = Option(require=True)

    def generate(self):
        log_file_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "..", "..", "..", "var", "log", "splunk", "saas_stack_operation_" + self.stack_id + ".log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=25000000, backupCount=5)
        tz = time.strftime("%Z")
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d ' + tz + ' stack_id=\"' + self.stack_id +
            '\" level=\"%(levelname)s\" %(message)s')
        formatter.datefmt = "%m/%d/%Y %H:%M:%S"
        file_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.setLevel("DEBUG")
        root_logger.addHandler(file_handler)

        class EventBufferHandler(logging.Handler):
            _events = None

            def __init__(self):
                logging.Handler.__init__(self)
                self._events = []

            def emit(self, record):
                self._events.append({
                    "level": record.levelname,
                    "_time": record.created,
                    "msg": record.getMessage(),
                })

            @property
            def events(self):
                return self._events
        buffer_handler = EventBufferHandler()
        root_logger.addHandler(buffer_handler)

        logging.debug("running '%s' command .." % self.command)

        # HTTPError: HTTP 503 Service Unavailable - - KV Store is initializing.
        # Please try again later.
        try:
            _ = self.service.kvstore["stacks"].data
        except splunklib.binding.HTTPError as e:
            if e.status == 503:
                logging.warning("%s" % e)
                return
            raise

        try:
            if self.command == "up":
                up(self.service, self.stack_id)
                return
            elif self.command == "down" or self.command == "kill":
                down(self.service, self.stack_id,
                     force=self.command == "kill")
            else:
                logging.error("unknown command: %s" % self.command)
            logging.debug("will stop '%s' command" % self.command)
        except errors.RetryOperation as e:
            msg = "%s" % e
            if msg:
                logging.info("%s" % msg)
            logging.debug("will check in 1m")
            return
        except:
            import traceback
            logging.error("%s\n(will try again in 1m)" %
                          traceback.format_exc())
            return
        finally:
            logging.shutdown()
            for e in buffer_handler.events:
                yield e

        unschedule_operation(self.service, self.stack_id)


dispatch(StackOperation, sys.argv, sys.stdin, sys.stdout, __name__)
