import os
import sys
bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import json
import fix_path
from base_handler import BaseRestHandler
import json
from urllib.parse import parse_qs
import splunklib
import time
import stack_operation
import services
import clusters

CREATING = "Creating"
CREATED = "Created"
DELETING = "Deleting"
DELETED = "Deleted"


def get_stack_config(service, stack_id):
    stacks = service.kvstore["stacks"].data
    return stacks.query_by_id(stack_id)


def update_config(service, stack_id, updates):
    stacks = service.kvstore["stacks"].data
    config = stacks.query_by_id(stack_id)
    config.update(updates)
    stacks.update(stack_id, json.dumps(config))


class StacksHandler(BaseRestHandler):
    def handle_GET(self):
        query = self.stacks.query(query=json.dumps({
            "status": {"$ne": DELETED}
        }))

        def map(d):
            return {
                "id": d["_key"],
                "status": d["status"],
                "title": d["title"] if "title" in d else "",
                "cluster": d["cluster"],
            }
        self.send_entries([map(d) for d in query])

    def handle_POST(self):

        defaults = self.service.confs["defaults"]["general"]

        # create stack record
        stack_record = {
            "status": CREATING,
        }
        fields_names = set([
            "deployment_type",
            "license_master_mode",
            "enterprise_license",
            "indexer_count",
            "search_head_count",
            "cpu_per_instance",
            "memory_per_instance",
            "title",
            "data_fabric_search",
            "spark_worker_count",
            "cluster",
            "namespace",
        ])

        # apply request parameters
        request_params = parse_qs(self.request['payload'])
        stack_record.update({
            k: request_params[k][0]
            for k in fields_names if k in request_params
        })

        # apply missing fields from defaults
        stack_record.update(
            {
                k: defaults[k]
                for k in fields_names if k in defaults and k not in stack_record
            }
        )

        # apply missing fields from cluster config
        cluster_name = stack_record["cluster"]
        cluster_config = clusters.get_cluster_config(
            self.service, cluster_name)
        stack_record.update(
            {
                k: cluster_config[k]
                for k in fields_names if k in cluster_config and k not in stack_record
            }
        )

        # save stack
        stack_id = self.stacks.insert(
            json.dumps(stack_record))["_key"]

        # start operator
        stack_operation.start(self.service, stack_id)

        # return ID
        self.send_result({
            "stack_id": stack_id,
        })


class StackHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        stack = self.stacks.query_by_id(
            stack_id)
        result = {
            "status": stack["status"],
            "title": stack["title"] if "title" in stack else "",
        }

        api_client = clusters.create_client(
            self.service, stack["cluster"])
        from kubernetes import client as kubernetes
        core_api = kubernetes.CoreV1Api(api_client)

        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.search_head_role, stack["namespace"])
        if hosts:
            result.update({
                "search_head_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        if stack["license_master_mode"] == "local":
            hosts = services.get_load_balancer_hosts(
                core_api, stack_id, services.license_master_role, stack["namespace"])
            if hosts:
                result.update({
                    "license_master_endpoint": ["http://%s" % hostname for hostname in hosts],
                })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.cluster_master_role, stack["namespace"])
        if hosts:
            result.update({
                "cluster_master_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.deployer_role, stack["namespace"])
        if hosts:
            result.update({
                "deployer_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.standalone_role, stack["namespace"])
        if hosts:
            result.update({
                "standalone_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.indexer_role, stack["namespace"])
        if hosts:
            result.update({
                "indexer_endpoint": ["%s:9997" % hostname for hostname in hosts],
            })
        self.send_result(result)

    def handle_DELETE(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        force = self.request["query"]["force"] == "true"
        stack_operation.stop(
            self.service, stack_id, force=force)
        self.send_result({
            "stack_id": stack_id,
        })
