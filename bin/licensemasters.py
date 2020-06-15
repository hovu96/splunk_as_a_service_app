import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from kubernetes import client as kuberneteslib
import yaml
import errors
import logging


def get_license_config_map(core_api, stack_id, stack_config):
    config_maps = core_api.list_namespaced_config_map(
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s,component=licenses" % stack_id,
    ).items
    if len(config_maps):
        return config_maps[0]
    return None


def deploy_license(core_api, stack_id, stack_config):
    config_map = get_license_config_map(core_api, stack_id, stack_config)
    if config_map:
        return
    enterprise_license = stack_config["enterprise_license"] if "enterprise_license" in stack_config else ""
    logging.info("deploying license ...")
    core_api.create_namespaced_config_map(
        stack_config["namespace"],
        kuberneteslib.V1ConfigMap(
            data={
                "enterprise.lic": enterprise_license,
            },
            api_version="v1",
            kind="ConfigMap",
            metadata=kuberneteslib.V1ObjectMeta(
                name="splunk-%s-licenses" % stack_id,
                namespace=stack_config["namespace"],
                labels={
                    "app": "saas",
                    "stack_id": stack_id,
                    "component": "licenses",
                }
            )
        )
    )


def get(splunk, kubernetes, stack_id, stack_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    license_masters = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="licensemasters",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(license_masters) > 1:
        raise Exception("found more than 1 license master: %s" % len(license_masters))
    if len(license_masters) == 0:
        return None
    license_master = license_masters[0]
    return license_master


def wait_until_ready(splunk, kubernetes, stack_id, stack_config):
    license_master = get(splunk, kubernetes, stack_id, stack_config)
    if not license_master:
        raise Exception("could not find license master")
    if not "status" in license_master:
        raise errors.RetryOperation("waiting for license master status")
    status = license_master["status"]
    phase = status["phase"]
    if phase != "Ready":
        raise errors.RetryOperation("waiting for license master to become ready (currently it's in %s phase)" % (
            phase
        ))


def deploy(splunk, kubernetes, stack_id, stack_config, cluster_config):
    license_master = get(splunk, kubernetes, stack_id, stack_config)
    if license_master:
        return
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    license_config_map = get_license_config_map(core_api, stack_id, stack_config)
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    splunk_defaults = {
        "splunk": {
            "conf": {
            }
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
        "varStorage": '%sGi' % stack_config["other_var_storage_in_gb"],
        "defaults": yaml.dump(splunk_defaults),
        "volumes": [{
            "name": "licenses",
            "configMap": {
                "name": license_config_map.metadata.name,
            }
        }],
        "licenseUrl": "/mnt/licenses/enterprise.lic",
    }
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
        plural="licensemasters",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha2",
            "kind": "LicenseMaster",
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
