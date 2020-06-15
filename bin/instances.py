import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
import services
import splunklib
import base64
import logging
from base_handler import BaseRestHandler
import stacks
import clusters
from kubernetes import client as kuberneteslib
import search_head_cluster
import re
import indexer_cluster
import standalones


def get_admin_password(core_api, stack_id, stack_config, role):
    if role == services.deployer_role:
        secret_role = services.search_head_role
    elif role == services.cluster_master_role:
        secret_role = services.indexer_role
    else:
        secret_role = role
    secret_name = "splunk-%s-%s-secrets" % (stack_id, secret_role)
    core_api.list_secret_for_all_namespaces()
    secrets = core_api.read_namespaced_secret(
        secret_name,
        namespace=stack_config["namespace"],
    )
    return base64.b64decode(secrets.data["password"]).decode()


def create_client(core_api, stack_id, stack_config, role):
    hosts = services.get_load_balancer_hosts(
        core_api, stack_id, role, stack_config["namespace"])
    if len(hosts) == 0:
        raise Exception(
            "could not get hostname for load balancer for role %s " % (role))
    password = get_admin_password(core_api, stack_id, stack_config, role)
    # logging.info("%s" % hosts[0])
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


class InstancesHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)

        stack_config = stacks.get_stack_config(self.splunk, stack_id)
        kubernetes = clusters.create_client(self.splunk, stack_config["cluster"])
        core_api = kuberneteslib.CoreV1Api(kubernetes)

        instances = {}

        pods = core_api.list_namespaced_pod(
            namespace=stack_config["namespace"],
            label_selector="app=saas,stack_id=%s" % stack_id,
        ).items
        for pod in pods:
            name = pod.metadata.name
            match = re.match('.*%s-(.+)-([0-9]+)$' % stack_id, name)
            if match:
                number = int(match.group(2)) + 1
                role = match.group(1)
            else:
                number = None
                match = re.match('.*%s-(.+)$' % stack_id, name)
                if match:
                    role = match.group(1)
                else:
                    role = None
            reasons = set()
            if pod.status:
                status = pod.status.phase
                is_ready = None
                if pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.status == "False":
                            if condition.reason:
                                reasons.add(condition.reason)
                        if condition.type == "Ready":
                            is_ready = condition.status == "True"
                if status == "Running":
                    if is_ready:
                        status = "ready"
                    else:
                        status = "running"
            else:
                status = "unknown"
            instances[name] = {
                "role": role.lower(),
                "number": number,
                "status": status.lower(),
                "reasons": list(reasons),
            }

        self.send_entries(instances.values())
