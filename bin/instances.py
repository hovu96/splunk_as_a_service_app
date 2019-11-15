import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import services
import splunklib
import base64
import logging


def create_client(core_api, stack_id, stack_config, role):
    hosts = services.get_load_balancer_hosts(
        core_api, stack_id, role, stack_config["namespace"])
    if len(hosts) == 0:
        raise Exception(
            "could not get hostname for load balancer for role %s " % (role))
    secrets = core_api.read_namespaced_secret(
        "splunk-%s-secrets" % stack_id,
        namespace=stack_config["namespace"],
    )
    password = base64.b64decode(secrets.data["password"])
    logging.info("%s" % hosts[0])
    splunk = splunklib.client.Service(
        port=8089,
        scheme="https",
        host=hosts[0],
        username="admin",
        password=password,
        # verify=False,
    )
    splunk.login()
    return splunk


def check_instance_startup_complated(core_api, stack_config, pod):
    if pod.status.phase != "Running":
        logging.debug("pod=\"%s\" not yet running (still %s)" %
                      (pod.metadata.name, pod.status.phase))
        return False
    logs = core_api.read_namespaced_pod_log(
        name=pod.metadata.name,
        namespace=stack_config["namespace"],
        tail_lines=100,
    )
    if "Ansible playbook complete" in logs:
        logging.debug("pod=\"%s\" status=\"completed\"" % pod.metadata.name)
        return True
    else:
        logging.debug("pod=\"%s\" status=\"not_yet_completed\"" %
                      pod.metadata.name)
        return False
