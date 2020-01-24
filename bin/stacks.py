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


def get_stacks(splunk):
    return splunk.kvstore["stacks"].data


def stack_exists(splunk, stack_id):
    try:
        get_stack_config(splunk, stack_id)
        return True
    except splunklib.binding.HTTPError as e:
        if e.status == 404:
            return False
        else:
            raise


def get_stack_config(splunk, stack_id):
    stacks = get_stacks(splunk)
    return stacks.query_by_id(stack_id)


def update_config(splunk, stack_id, updates):
    stacks = get_stacks(splunk)
    config = stacks.query_by_id(stack_id)
    config.update(updates)
    stacks.update(stack_id, json.dumps(config))


class StacksHandler(BaseRestHandler):
    def handle_GET(self):
        stacks = get_stacks(self.splunk)
        request_query = self.request['query']
        phase = request_query.get("phase", "living")
        cluster = request_query.get("cluster", "*")
        deleted_after = int(request_query.get("deleted_after", time.time() - 60 * 60 * 24 * 30))
        deleted_before = int(request_query.get("deleted_before", time.time()))

        query = {}
        if phase == "living":
            query["status"] = {"$ne": DELETED}
        elif phase == "deleted":
            query["status"] = DELETED
            query["$and"] = [
                {"deleted_time": {"$gt": deleted_after}},
                {"deleted_time": {"$lt": deleted_before}}
            ]
        if cluster and cluster != "*":
            query["cluster"] = cluster
        query = stacks.query(query=json.dumps(query))

        def map(d):
            return {
                "id": d["_key"],
                "status": d["status"],
                "title": d["title"] if "title" in d else "",
                "cluster": d["cluster"],
            }
        self.send_entries([map(d) for d in query if "deleted_time" in d])

    def handle_POST(self):
        stacks = get_stacks(self.splunk)
        defaults = self.splunk.confs["defaults"]["general"]

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
            "etc_storage_in_gb",
            "other_var_storage_in_gb",
            "indexer_var_storage_in_gb",
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

        # add missing fields
        if "data_fabric_search" not in stack_record:
            stack_record["data_fabric_search"] = "false"
        if "spark_worker_count" not in stack_record:
            stack_record["spark_worker_count"] = "0"
        if "cpu_per_instance" not in stack_record:
            stack_record["cpu_per_instance"] = "1"
        if "memory_per_instance" not in stack_record:
            stack_record["memory_per_instance"] = "4Gi"

        # save stack
        stack_id = stacks.insert(json.dumps(stack_record))["_key"]

        # start operator
        stack_operation.start(self.service, stack_id)

        # return ID
        self.send_result({
            "stack_id": stack_id,
        })


class StackHandler(BaseRestHandler):
    def handle_GET(self):
        stacks = get_stacks(self.splunk)
        path = self.request['path']
        _, stack_id = os.path.split(path)
        stack = stacks.query_by_id(stack_id)

        result = {
            "status": stack["status"],
            "title": stack["title"] if "title" in stack else "",
            "deployment_type": stack["deployment_type"],
            "license_master_mode": stack["license_master_mode"],
            "cluster": stack["cluster"],
            "namespace": stack["namespace"],
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

    def handle_POST(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        get_stack_config(self.splunk, stack_id)
        fields_names = set([
            "title",
        ])
        request_params = parse_qs(self.request['payload'])
        stack_updates = {
            k: request_params[k][0]
            for k in fields_names if k in request_params
        }
        update_config(self.splunk, stack_id, stack_updates)

    def handle_DELETE(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        if "force" in self.request["query"]:
            force = self.request["query"]["force"] == "true"
        else:
            force = False
        stack_operation.stop(
            self.service, stack_id, force=force)
        self.send_result({
            "stack_id": stack_id,
        })
