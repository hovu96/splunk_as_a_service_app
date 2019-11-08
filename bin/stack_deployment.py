from kubernetes import client as kubernetes
import yaml
import errors
import logging
import time
import services
import app_deployment


def create_deployment(splunk, core_api, custom_objects_api, stack_id, stack_config, cluster_config):
    if stack_config["license_master_mode"] == "local":
        if not license_exists(core_api, stack_id, stack_config):
            logging.info("deploying license ...")
            create_license(
                core_api, stack_id, stack_config)
    if not get_splunk(custom_objects_api, stack_id, stack_config):
        logging.info("deploying Splunk ...")
        create_splunk(
            custom_objects_api, stack_id, stack_config, cluster_config)

    if not wait_until_pod_created(splunk, core_api, stack_id, stack_config):
        logging.warning("could not find all pods")
        raise errors.RetryOperation()

    create_load_balancers(core_api, stack_id, stack_config)

    if not wait_until_splunk_instance_completed(core_api, stack_id, stack_config):
        logging.warning("splunk could not complete startup")
        raise errors.RetryOperation()

    app_deployment.install_base_apps(
        splunk, core_api, stack_id)


def wait_until_pod_created(splunk, core_api, stack_id, stack_config, timeout=60*15):
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

    logging.info("waiting for pod beeing created...")
    t_end = time.time() + timeout
    while time.time() < t_end:
        pods = core_api.list_namespaced_pod(
            namespace=stack_config["namespace"],
            label_selector="app=splunk,for=%s" % stack_id,
        ).items
        if len(pods) == expected_number_of_instances:
            return True
        logging.info("expecting %s pods (found %d)" %
                     (expected_number_of_instances, len(pods)))
        time.sleep(1)
    return False


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
    #getaddrinfo(host, port, 0, SOCK_STREAM)


def wait_until_splunk_instance_completed(core_api, stack_id, stack_config, timeout=60*15):
    logging.info("waiting for splunk instances to complete...")
    t_end = time.time() + timeout
    while time.time() < t_end:
        pods = core_api.list_namespaced_pod(
            namespace=stack_config["namespace"],
            label_selector="app=splunk,for=%s" % stack_id,
        ).items
        number_of_pods_completed = 0
        for p in pods:
            if check_splunk_instance_completed(core_api, stack_config, p):
                number_of_pods_completed += 1
        if number_of_pods_completed == len(pods):
            logging.info("all pods completed startup")
            return True
        else:
            logging.info("Waiting for %d (out of %d) remaining pod(s) to complete startup ...",
                         (len(pods)-number_of_pods_completed), len(pods))
            time.sleep(5)
    return False


def check_splunk_instance_completed(core_api, stack_config, pod):
    #logging.info("pod %s" % (pod.metadata.name))
    if pod.status.phase != "Running":
        logging.info("pod=\"%s\" not yet running (still %s)" %
                     (pod.metadata.name, pod.status.phase))
        return False
    logs = core_api.read_namespaced_pod_log(
        name=pod.metadata.name,
        namespace=stack_config["namespace"],
        tail_lines=100,
    )
    if "Ansible playbook complete" in logs:
        logging.info("pod=\"%s\" status=\"completed\"" % pod.metadata.name)
        return True
    else:
        logging.info("pod=\"%s\" status=\"not_yet_completed\"" %
                     pod.metadata.name)
        return False


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
