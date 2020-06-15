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
import instances
import ssl
import stacks
import clusters
import indexer_cluster
import search_head_cluster
import standalones
import licensemasters


def create_deployment(splunk, kubernetes, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    if stack_config["license_master_mode"] == "local":
        licensemasters.deploy_license(core_api, stack_id, stack_config)
    if stack_config["deployment_type"] == "standalone":
        standalones.deploy(splunk, kubernetes, stack_id, stack_config, cluster_config)
        standalones.wait_until_ready(splunk, kubernetes, stack_id, stack_config)
    elif stack_config["deployment_type"] == "distributed":
        if stack_config["license_master_mode"] == "local":
            licensemasters.deploy(splunk, kubernetes, stack_id, stack_config, cluster_config)
            deployed_license_master = True
        else:
            deployed_license_master = True
        indexer_cluster.deploy(splunk, kubernetes, stack_id, stack_config, cluster_config)
        search_head_cluster.deploy(splunk, kubernetes, stack_id, stack_config, cluster_config)
        indexer_cluster.wait_until_ready(splunk, kubernetes, stack_id, stack_config)
        search_head_cluster.wait_until_ready(splunk, kubernetes, stack_id, stack_config)
        if deployed_license_master:
            licensemasters.wait_until_ready(splunk, kubernetes, stack_id, stack_config)
    else:
        raise errors.ApplicationError("Unknown deployment type: '%s'" % (stack_config["deployment_type"]))
    create_load_balancers(core_api, stack_id, stack_config)
    verify_pods_created(splunk, core_api, stack_id, stack_config)
    verify_all_splunk_instance_completed_startup(core_api, stack_id, stack_config)
    verify_load_balancers_completed(core_api, stack_id, stack_config)


def update_deployment(splunk, kubernetes, stack_id):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_name = stack_config["cluster"]
    kubernetes = clusters.create_client(splunk, cluster_name)
    cluster_config = clusters.get_cluster(splunk, cluster_name)
    if stack_config["deployment_type"] == "distributed":
        indexer_cluster.update(splunk, kubernetes, stack_id, stack_config)
        search_head_cluster.update(splunk, kubernetes, stack_id, stack_config)
        indexer_cluster.wait_until_ready(splunk, kubernetes, stack_id, stack_config)
        search_head_cluster.wait_until_ready(splunk, kubernetes, stack_id, stack_config)


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
            raise errors.RetryOperation("Waiting for %s ingress connection (cannot resolve hostname)" % role)
        pass
    if role == services.standalone_role or role == services.deployer_role or role == services.search_head_role or role == services.cluster_master_role:
        try:
            instances.create_client(core_api, stack_id, stack_config, role)
        except ssl.SSLEOFError:
            raise errors.RetryOperation("Waiting for %s ingress connection (SSL protocol error)" % role)
        except TimeoutError:
            raise errors.RetryOperation("Waiting for %s ingress connection (timeout)" % role)


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


def delete_objects(kubernetes, stack_id, stack_config, cluster_config):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    search_heads = custom_objects_api.list_namespaced_custom_object(
        namespace=stack_config["namespace"],
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="searchheadclusters",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for search_head in search_heads:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="searchheadclusters",
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
        plural="indexerclusters",
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    for indexer in indexers:
        custom_objects_api.delete_namespaced_custom_object(
            namespace=stack_config["namespace"],
            group="enterprise.splunk.com",
            version="v1alpha2",
            plural="indexerclusters",
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
