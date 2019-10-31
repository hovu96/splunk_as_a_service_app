from kubernetes import client as kubernetes
import yaml
import errors


def license_exists(core_api, stack_id, stack_config):
    try:
        core_api.read_namespaced_config_map(
            namespace=stack_config["namespace"],
            name=stack_id,
        )
        return True
    except kubernetes.rest.ApiException as e:
        if e.status == 404:
            return False
        raise


def create_license(core_api, stack_id, stack_config):
    enterprise_license = stack_config["enterprise_license"] if "enterprise_license" in stack_config else ""
    core_api.create_namespaced_config_map(
        stack_config["namespace"],
        kubernetes.V1ConfigMap(
            data={
                "enterprise.lic": enterprise_license,
            },
            api_version="v1",
            kind="ConfigMap",
            metadata=kubernetes.V1ObjectMeta(
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
    except kubernetes.rest.ApiException as e:
        if e.status == 404:
            return None
        raise


def create_splunk(custom_objects_api, stack_id, stack_config, cluster_config):
    def str2bool(v):
        return v.lower() in ("yes", "true", "t", "1")
    splunk_defaults = {}
    if stack_config["license_master_mode"] == "remote":
        splunk_defaults["splunk"] = {
            "conf": {
                "server": {
                    "content": {
                        "license": {
                            "master_uri": cluster_config.license_master_url,
                        }
                    }
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
        body=kubernetes.V1DeleteOptions(),
    )
