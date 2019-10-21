import json
import os
import fix_path
from base_handler import BaseRestHandler
import json
from urlparse import parse_qs
import splunklib
import time
import operator_controller
import services
import clusters

CREATING = "Creating"
CREATED = "Created"
DELETING = "Deleting"
DELETED = "Deleted"


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
        ])
        payload = parse_qs(self.request['payload'])
        stack_record.update(
            {
                k: payload[k][0] if k in payload
                else defaults[k] if k in defaults else ""
                for k in fields_names
            }
        )

        # save stack
        stack_id = self.stacks.insert(
            json.dumps(stack_record))["_key"]

        # start operator
        operator_controller.start_operator(self.service, stack_id)

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
            core_api, stack_id, services.search_head_role)
        if hosts:
            result.update({
                "search_head_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        if stack["license_master_mode"] == "file":
            hosts = services.get_load_balancer_hosts(
                core_api, stack_id, services.license_master_role)
            if hosts:
                result.update({
                    "license_master_endpoint": ["http://%s" % hostname for hostname in hosts],
                })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.cluster_master_role)
        if hosts:
            result.update({
                "cluster_master_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.deployer_role)
        if hosts:
            result.update({
                "deployer_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.standalone_role)
        if hosts:
            result.update({
                "standalone_endpoint": ["http://%s" % hostname for hostname in hosts],
            })
        hosts = services.get_load_balancer_hosts(
            core_api, stack_id, services.indexer_role)
        if hosts:
            result.update({
                "indexer_endpoint": ["%s:9997" % hostname for hostname in hosts],
            })
        self.send_result(result)

    def handle_DELETE(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        force = self.request["query"]["force"] == "true"
        operator_controller.stop_operator(
            self.service, stack_id, force=force)
        self.send_result({
            "stack_id": stack_id,
        })
