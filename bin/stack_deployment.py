import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from kubernetes import client as kuberneteslib
import yaml
import errors
import logging
import time
import services
import app_deployment
import instances


def create_deployment(splunk, kubernetes, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    if stack_config["license_master_mode"] == "local":
        if not license_exists(core_api, stack_id, stack_config):
            logging.info("deploying license ...")
            create_license(
                core_api, stack_id, stack_config)
    if not get_splunk(custom_objects_api, stack_id, stack_config):
        logging.info("deploying Splunk ...")
        create_splunk(
            custom_objects_api, stack_id, stack_config, cluster_config)

    verify_pods_created(splunk, core_api, stack_id, stack_config)
    create_load_balancers(core_api, stack_id, stack_config)
    verify_all_splunk_instance_completed_startup(
        core_api, stack_id, stack_config)
    app_deployment.update_apps(splunk, kubernetes, stack_id)


def verify_pods_created(splunk, core_api, stack_id, stack_config):
    expected_number_of_instances = 0
    if stack_config["deployment_type"] == "standalone":
        expected_number_of_instances += 1
    elif stack_config["deployment_type"] == "distributed":
        search_head_count = int(stack_config["search_head_count"])
        if search_head_count > 1:
            expected_number_of_instances += 1
        if search_head_count > 0:
            expected_number_of_instances += search_head_count
        expected_number_of_instances += 2
        indexer_count = int(stack_config["indexer_count"])
        if indexer_count > 0:
            expected_number_of_instances += indexer_count

    pods = core_api.list_namespaced_pod(
        namespace=stack_config["namespace"],
        label_selector="app=splunk,for=%s" % stack_id,
    ).items
    if len(pods) == expected_number_of_instances:
        return
    raise errors.RetryOperation("still waiting for pods (expecting %s, found %d) ..." %
                                (expected_number_of_instances, len(pods)))


def create_load_balancers(core_api, stack_id, stack_config):
    if stack_config["deployment_type"] == "standalone":
        services.create_load_balancers(
            core_api,
            stack_id,
            services.standalone_role,
            stack_config["namespace"],
        )
    elif stack_config["deployment_type"] == "distributed":
        if int(stack_config["search_head_count"]) > 1:
            services.create_load_balancers(
                core_api,
                stack_id,
                services.deployer_role,
                stack_config["namespace"],
            )
        if int(stack_config["search_head_count"]) > 0:
            services.create_load_balancers(
                core_api,
                stack_id,
                services.search_head_role,
                stack_config["namespace"],
            )
        services.create_load_balancers(
            core_api,
            stack_id,
            services.license_master_role,
            stack_config["namespace"],
        )
        if int(stack_config["indexer_count"]) > 0:
            services.create_load_balancers(
                core_api,
                stack_id,
                services.cluster_master_role,
                stack_config["namespace"],
            )
            services.create_load_balancers(
                core_api,
                stack_id,
                services.indexer_role,
                stack_config["namespace"],
            )
    # getaddrinfo(host, port, 0, SOCK_STREAM)


def verify_all_splunk_instance_completed_startup(core_api, stack_id, stack_config):
    pods = core_api.list_namespaced_pod(
        namespace=stack_config["namespace"],
        label_selector="app=splunk,for=%s" % stack_id,
    ).items
    number_of_pods_completed = 0
    for p in pods:
        if instances.check_instance_startup_complated(core_api, stack_config, p):
            number_of_pods_completed += 1
    if number_of_pods_completed != len(pods):
        not_completed = len(pods) - number_of_pods_completed
        raise errors.RetryOperation("waiting for %s (out of %s) pods to complete startup ..." %
                                    (not_completed, len(pods)))
    logging.info("all pods completed startup")


def license_exists(core_api, stack_id, stack_config):
    try:
        core_api.read_namespaced_config_map(
            namespace=stack_config["namespace"],
            name=stack_id,
        )
        return True
    except kuberneteslib.rest.ApiException as e:
        if e.status == 404:
            return False
        raise


def create_license(core_api, stack_id, stack_config):
    enterprise_license = stack_config["enterprise_license"] if "enterprise_license" in stack_config else ""
    core_api.create_namespaced_config_map(
        stack_config["namespace"],
        kuberneteslib.V1ConfigMap(
            data={
                "enterprise.lic": enterprise_license,
            },
            api_version="v1",
            kind="ConfigMap",
            metadata=kuberneteslib.V1ObjectMeta(
                name=stack_id,
                namespace=stack_config["namespace"],
            )
        )
    )


def delete_license(core_api, stack_id, stack_config):
    core_api.delete_namespaced_config_map(
        stack_id,
        stack_config["namespace"]
    )


def get_splunk(custom_objects_api, stack_id, stack_config):
    try:
        return custom_objects_api.get_namespaced_custom_object(
            group="enterprise.splunk.com",
            version="v1alpha1",
            plural="splunkenterprises",
            namespace=stack_config["namespace"],
            name=stack_id,
        )
    except kuberneteslib.rest.ApiException as e:
        if e.status == 404:
            return None
        raise


def create_splunk(custom_objects_api, stack_id, stack_config, cluster_config):
    def str2bool(v):
        v = "%s" % v
        return v.lower() in ("yes", "true", "t", "1")
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
                }
            }
        }
    if stack_config["deployment_type"] == "standalone":
        topology = {
            "standalones": 1,
        }
    elif stack_config["deployment_type"] == "distributed":
        topology = {
            "indexers": int(stack_config["indexer_count"]),
            "searchHeads": int(stack_config["search_head_count"]),
            "sparkWorkers": int(stack_config["spark_worker_count"]),
        }
    else:
        raise errors.ApplicationError(
            "Unknown deployment type: '%s'" % (stack_config["deployment_type"]))
    spec = {
        "splunkVolumes": [],
        "enableDFS": str2bool(stack_config["data_fabric_search"]),
        "topology": topology,
        "splunkImage": cluster_config.default_splunk_image,
        "resources": {
            "splunkCpuRequest": stack_config["cpu_per_instance"],
            "splunkCpuLimit": stack_config["cpu_per_instance"],
            "splunkMemoryRequest": stack_config["memory_per_instance"],
            "splunkMemoryLimit": stack_config["memory_per_instance"],
            "sparkCpuRequest": stack_config["cpu_per_instance"],
            "sparkCpuLimit": stack_config["cpu_per_instance"],
            "sparkMemoryRequest": stack_config["memory_per_instance"],
            "sparkMemoryLimit": stack_config["memory_per_instance"],
            "splunkEtcStorage": '%sGi' % stack_config["etc_storage_in_gb"],
            "splunkVarStorage": '%sGi' % stack_config["other_var_storage_in_gb"],
            "splunkIndexerStorage": '%sGi' % stack_config["indexer_var_storage_in_gb"],
        },
        "defaults": yaml.dump(splunk_defaults),
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
    if stack_config["license_master_mode"] == "local":
        spec["splunkVolumes"].append({
            "name": "licenses",
            "configMap": {
                "name": stack_id,
            }
        })
        spec["licenseUrl"] = "/mnt/licenses/enterprise.lic"
    elif stack_config["license_master_mode"] == "remote":
        spec["splunkVolumes"].append({
            "name": "licenses",
            "emptyDir": {
                "name": stack_id,
            }
        })
        spec["licenseUrl"] = "/mnt/licenses/dummy.lic"
    if "storage_class" in cluster_config and cluster_config.storage_class:
        spec["storageClassName"] = cluster_config.storage_class
    custom_objects_api.create_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha1",
        namespace=stack_config["namespace"],
        plural="splunkenterprises",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha1",
            "kind": "SplunkEnterprise",
            "metadata": {
                "name": stack_id,
                "finalizers": ["enterprise.splunk.com/delete-pvc"]
            },
            "spec": spec,
        },
    )


def delete_splunk(custom_objects_api, stack_id, stack_config):
    custom_objects_api.delete_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha1",
        name=stack_id,
        namespace=stack_config["namespace"],
        plural="splunkenterprises",
        body=kuberneteslib.V1DeleteOptions(),
    )
