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
        deploy_license(core_api, stack_id, stack_config)
    if stack_config["deployment_type"] == "standalone":
        deploy_standalone(kubernetes, stack_id, stack_config, cluster_config)
    elif stack_config["deployment_type"] == "distributed":
        if stack_config["license_master_mode"] == "local":
            deploy_license_master(kubernetes, stack_id, stack_config, cluster_config)
        deploy_indexer_cluster(kubernetes, stack_id, stack_config, cluster_config)
        deploy_search_head_cluster(kubernetes, stack_id, stack_config, cluster_config)
        # if int(stack_config["spark_worker_count"]) > 0:
        #    deploy_spark_cluster(kubernetes, stack_id, stack_config, cluster_config)
        # str2bool(stack_config["data_fabric_search"]),
    else:
        raise errors.ApplicationError(
            "Unknown deployment type: '%s'" % (stack_config["deployment_type"]))
    create_load_balancers(core_api, stack_id, stack_config)
    verify_pods_created(splunk, core_api, stack_id, stack_config)
    verify_load_balancers_completed(core_api, stack_id, stack_config)
    verify_all_splunk_instance_completed_startup(
        core_api, stack_id, stack_config)
    app_deployment.update_apps(splunk, kubernetes, stack_id)


def verify_pods_created(splunk, core_api, stack_id, stack_config):
    expected_number_of_instances = 0
    if stack_config["deployment_type"] == "standalone":
        expected_number_of_instances += 1
    elif stack_config["deployment_type"] == "distributed":
        expected_number_of_instances += 1  # deployer
        search_head_count = int(stack_config["search_head_count"])
        expected_number_of_instances += search_head_count
        expected_number_of_instances += 1  # cluster master
        indexer_count = int(stack_config["indexer_count"])
        expected_number_of_instances += indexer_count
        if stack_config["license_master_mode"] == "local":
            expected_number_of_instances += 1

    pods = core_api.list_namespaced_pod(
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
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


def verify_load_balancer_completed(core_api, stack_id, stack_config, role):
    # getaddrinfo(host, port, 0, SOCK_STREAM)
    hosts = services.get_load_balancer_hosts(
        core_api,
        stack_id,
        role,
        stack_config["namespace"]
    )
    if not len(hosts):
        raise errors.RetryOperation("waiting for %s load balancer hostname" % role)
    for host in hosts:
        try:
            import socket
            socket.gethostbyname(host)
        except socket.error:
            raise errors.RetryOperation("Waiting for %s service load balancer ingress hostname to become resolvable" % role)


def verify_load_balancers_completed(core_api, stack_id, stack_config):
    if stack_config["deployment_type"] == "standalone":
        verify_load_balancer_completed(core_api, stack_id, stack_config, services.standalone_role)
    elif stack_config["deployment_type"] == "distributed":
        verify_load_balancer_completed(core_api, stack_id, stack_config, services.deployer_role)
        verify_load_balancer_completed(core_api, stack_id, stack_config, services.search_head_role)
        # verify_load_balancer_completed(core_api, stack_id, stack_config, services.license_master_role)
        if int(stack_config["indexer_count"]) > 0:
            verify_load_balancer_completed(core_api, stack_id, stack_config, services.cluster_master_role)
            verify_load_balancer_completed(core_api, stack_id, stack_config, services.indexer_role)


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
    logging.debug("all pods completed startup")


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


def delete_objects(api_client, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(api_client)
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
    search_heads = custom_objects_api.list_namespaced_custom_object(
        namespace=stack_config["namespace"],
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="searchheads",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for search_head in search_heads:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="searchheads",
            name=search_head["metadata"]["name"],
            body=kuberneteslib.V1DeleteOptions(),
        )
    standalones = custom_objects_api.list_namespaced_custom_object(
        namespace=stack_config["namespace"],
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="standalones",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for standalone in standalones:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="standalones",
            name=standalone["metadata"]["name"],
            body=kuberneteslib.V1DeleteOptions(),
        )
    indexers = custom_objects_api.list_namespaced_custom_object(
        namespace=stack_config["namespace"],
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="indexers",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for indexer in indexers:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="indexers",
            name=indexer["metadata"]["name"],
            body=kuberneteslib.V1DeleteOptions(),
        )
    license_masters = custom_objects_api.list_namespaced_custom_object(
        namespace=stack_config["namespace"],
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="licensemasters",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for license_master in license_masters:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="licensemasters",
            name=license_master["metadata"]["name"],
            body=kuberneteslib.V1DeleteOptions(),
        )
    config_maps = core_api.list_namespaced_config_map(
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    ).items
    for config_map in config_maps:
        core_api.delete_namespaced_config_map(
            namespace=stack_config["namespace"],
            name=config_map.metadata.name,
            body=kuberneteslib.V1DeleteOptions(),
        )


def deploy_license_master(api_client, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(api_client)
    license_config_map = get_license_config_map(core_api, stack_id, stack_config)
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
    license_masters = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="licensemasters",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(license_masters):
        return
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
        "indexerRef": {
            "name": "%s" % stack_id,
        },
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


def deploy_standalone(api_client, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(api_client)
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
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
        license_config_map = get_license_config_map(core_api, stack_id, stack_config)
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


def deploy_indexer_cluster(api_client, stack_id, stack_config, cluster_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
    indexers = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="indexers",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(indexers):
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
        "replicas": int(stack_config["indexer_count"]),
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
    if stack_config["license_master_mode"] == "local":
        spec["licenseMasterRef"] = {
            "name": stack_id
        }
    custom_objects_api.create_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        namespace=stack_config["namespace"],
        plural="indexers",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha2",
            "kind": "Indexer",
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


def deploy_search_head_cluster(api_client, stack_id, stack_config, cluster_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(api_client)
    search_heads = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="searchheads",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(search_heads):
        return
    splunk_defaults = {
        "splunk": {
            "conf": {

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
        "replicas": int(stack_config["search_head_count"]),
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
        "indexerRef": {
            "name": "%s" % stack_id,
        }
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
    if stack_config["license_master_mode"] == "local":
        spec["licenseMasterRef"] = {
            "name": stack_id
        }
    custom_objects_api.create_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        namespace=stack_config["namespace"],
        plural="searchheads",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha2",
            "kind": "SearchHead",
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
