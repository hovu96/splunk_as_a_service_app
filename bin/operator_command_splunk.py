import fix_path
import sys
import os
import time
import yaml
import traceback
import logging
from kubernetes import client as kubernetes
import splunklib.client
import kubernetes_utils
import operator_controller
from operator_command_base import OperatorCommandBase
import errors


class OperatorCommandSplunk(OperatorCommandBase, object):

    def get_splunk(self):
        try:
            return self.custom_objects_api.get_namespaced_custom_object(
                group="enterprise.splunk.com",
                version="v1alpha1",
                plural="splunkenterprises",
                namespace="default",
                name=self.stack_id,
            )
        except kubernetes.rest.ApiException as e:
            if e.status == 404:
                return None
            raise

    def create_splunk(self):
        def str2bool(v):
            return v.lower() in ("yes", "true", "t", "1")
        splunk_defaults = {}
        if self.config["license_master_mode"] == "remote":
            splunk_defaults["splunk"] = {
                "conf": {
                    "server": {
                        "content": {
                            "license": {
                                "master_uri": self.cluster_config.license_master_url,
                            }
                        }
                    }
                }
            }
        if self.config["deployment_type"] == "standalone":
            topology = {
                "standalones": 1,
            }
        elif self.config["deployment_type"] == "distributed":
            topology = {
                "indexers": int(self.config["indexer_count"]),
                "searchHeads": int(self.config["search_head_count"]),
                "sparkWorkers": int(self.config["spark_worker_count"]),
            }
        else:
            raise errors.ApplicationError(
                "Unknown deployment type: '%s'" % (self.config["deployment_type"]))
        spec = {
            "splunkVolumes": [],
            "enableDFS": str2bool(self.config["data_fabric_search"]),
            "topology": topology,
            "splunkImage": self.cluster_config.default_splunk_image,
            "resources": {
                "splunkCpuRequest": self.config["cpu_per_instance"],
                "splunkCpuLimit": self.config["cpu_per_instance"],
                "splunkMemoryRequest": self.config["memory_per_instance"],
                "splunkMemoryLimit": self.config["memory_per_instance"],
                "sparkCpuRequest": self.config["cpu_per_instance"],
                "sparkCpuLimit": self.config["cpu_per_instance"],
                "sparkMemoryRequest": self.config["memory_per_instance"],
                "sparkMemoryLimit": self.config["memory_per_instance"],
            },
            "defaults": yaml.dump(splunk_defaults),
            # "affinity": {
            #    "nodeAffinity": {
            #        "requiredDuringSchedulingIgnoredDuringExecution": {
            #            "nodeSelectorTerms": [
            #                {
            #                    "matchExpressions": [
            #                        {
            #                            "key": "role",
            #                            "operator": "In",
            #                            "values": ["splunk"],
            #                        },
            #                    ],
            #                }
            #            ],
            #        }
            #    }
            # }
        }
        if self.config["license_master_mode"] == "local":
            spec["splunkVolumes"].append({
                "name": "licenses",
                "configMap": {
                    "name": self.stack_id,
                }
            })
            spec["licenseUrl"] = "/mnt/licenses/enterprise.lic"
        elif self.config["license_master_mode"] == "remote":
            spec["splunkVolumes"].append({
                "name": "licenses",
                "emptyDir": {
                    "name": self.stack_id,
                }
            })
            spec["licenseUrl"] = "/mnt/licenses/dummy.lic"
        if "storage_class" in self.cluster_config and self.cluster_config.storage_class:
            spec["storageClassName"] = self.cluster_config.storage_class
        self.custom_objects_api.create_namespaced_custom_object(
            group="enterprise.splunk.com",
            version="v1alpha1",
            namespace="default",
            plural="splunkenterprises",
            body={
                "apiVersion": "enterprise.splunk.com/v1alpha1",
                "kind": "SplunkEnterprise",
                "metadata": {
                    "name": self.stack_id,
                    "finalizers": ["enterprise.splunk.com/delete-pvc"]
                },
                "spec": spec,
            },
        )

    def delete_splunk(self):
        self.custom_objects_api.delete_namespaced_custom_object(
            group="enterprise.splunk.com",
            version="v1alpha1",
            name=self.stack_id,
            namespace="default",
            plural="splunkenterprises",
            body=kubernetes.V1DeleteOptions(),
        )
