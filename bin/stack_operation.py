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
            os.path.dirname(__file__)), "..", "..", "..", "var", "log", "splunk", "saas_stack_operation_" + self.stack_id+".log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=25000000, backupCount=5)
        formatter = logging.Formatter(
            '%(asctime)s stack_id=\"'+self.stack_id +
            '\" level=\"%(levelname)s\" %(message)s')
        formatter.datefmt = "%m/%d/%Y %H:%M:%S %Z"
        file_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.setLevel("DEBUG")
        root_logger.addHandler(file_handler)

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

        if False:
            yield

        try:
            if self.command == "up":
                stack_deployment.up(self.service, self.stack_id)
                return
            elif self.command == "down" or self.command == "kill":
                stack_deployment.down(self.service, self.stack_id,
                                      force=self.command == "kill")
            else:
                logging.error("unknown command: %s" % self.command)
        except errors.RetryOperation:
            logging.debug("will retry '%s' command" % self.command)
            return
        except:
            import traceback
            logging.error(traceback.format_exc())
            logging.debug("will retry '%s' command" % self.command)
            return

        logging.debug("will stop '%s' command" % self.command)
        logging.shutdown()
        unschedule_operation(self.service, self.stack_id)


dispatch(StackOperation, sys.argv, sys.stdin, sys.stdout, __name__)
