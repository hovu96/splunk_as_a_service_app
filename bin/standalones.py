import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from kubernetes import client as kuberneteslib
import yaml
import errors
import licensemasters


def wait_until_ready(splunk, kubernetes, stack_id, stack_config):
    standalone = get(splunk, kubernetes, stack_id, stack_config)
    if not standalone:
        raise Exception("could not find standalone")
    if not "status" in standalone:
        raise errors.RetryOperation("waiting for standalone status")
    status = standalone["status"]
    phase = status["phase"]
    if phase != "Ready":
        raise errors.RetryOperation("waiting for standalone to become ready (currently it's in %s phase)" % (
            phase
        ))


def get(splunk, kubernetes, stack_id, stack_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    standalones = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="standalones",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(standalones) > 1:
        raise Exception("found more than 1 standalone: %s" % len(standalones))
    if len(standalones) == 0:
        return None
    standalone = standalones[0]
    return standalone


def update(splunk, kubernetes, stack_id, stack_config):
    pass


def deploy(splunk, kubernetes, stack_id, stack_config, cluster_config):
    standalone = get(splunk, kubernetes, stack_id, stack_config)
    if standalone:
        return
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    standalones = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="standalones",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(standalones):
        return
    splunk_defaults = {
        "splunk": {
            "conf": {
                "inputs": {
                    "content": {
                        "tcp://:9996": {
                            "connection_host": "dns",
                            "source": "tcp:9996",
                        }
                    }
                }
            }
        }
    }
    if stack_config["license_master_mode"] == "remote":
        splunk_defaults["splunk"]["conf"]["server"] = {
            "content": {
                "license": {
                    "master_uri": cluster_config.license_master_url,
                },
                "general": {
                    "pass4SymmKey": cluster_config.license_master_pass4symmkey,
                },
            }
        }
    spec = {
        "image": cluster_config.default_splunk_image,
        "imagePullPolicy": "Always",
        "resources": {
            "requests": {
                "memory": stack_config["memory_per_instance"],
                "cpu": stack_config["cpu_per_instance"],
            },
            "limits": {
                "memory": stack_config["memory_per_instance"],
                "cpu": stack_config["cpu_per_instance"],
            },
        },
        "etcStorage": '%sGi' % stack_config["etc_storage_in_gb"],
        "varStorage": '%sGi' % stack_config["indexer_var_storage_in_gb"],
        "defaults": yaml.dump(splunk_defaults),
    }
    if stack_config["license_master_mode"] == "local":
        license_config_map = licensemasters.get_license_config_map(core_api, stack_id, stack_config)
        spec.update({
            "volumes": [{
                "name": "licenses",
                "configMap": {
                    "name": license_config_map.metadata.name,
                }
            }],
            "licenseUrl": "/mnt/licenses/enterprise.lic"
        })

    if cluster_config.node_selector:
        labels = cluster_config.node_selector.split(",")
        match_expressions = []
        for label in labels:
            if label:
                kv = label.split("=")
                if len(kv) != 2:
                    raise errors.ApplicationError(
                        "invalid node selector format (%s)" % cluster_config.node_selector)
                match_expressions.append({
                    "key": kv[0],
                    "operator": "In",
                    "values": [kv[1]],
                })
        spec["affinity"] = {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": match_expressions,
                        }
                    ],
                }
            }
        }
    if "storage_class" in cluster_config and cluster_config.storage_class:
        spec["storageClassName"] = cluster_config.storage_class
    custom_objects_api.create_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        namespace=stack_config["namespace"],
        plural="standalones",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha2",
            "kind": "Standalone",
            "metadata": {
                "name": stack_id,
                "finalizers": ["enterprise.splunk.com/delete-pvc"],
                "labels": {
                    "app": "saas",
                    "stack_id": stack_id,
                }
            },
            "spec": spec,
        },
    )
