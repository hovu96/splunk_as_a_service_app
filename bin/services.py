import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
import logging
import time
from kubernetes import client as kubernetes

standalone_role = "standalone"
deployer_role = "deployer"
search_head_role = "search-head"
indexer_role = "indexer"
cluster_master_role = "cluster-master"
license_master_role = "license-master"


def get(core_api, service_name, namespace):
    try:
        return core_api.read_namespaced_service(
            service_name, namespace=namespace)
    except kubernetes.rest.ApiException as e:
        if e.status == 404:
            return None
        raise


def delete(core_api, service_name, namespace):
    core_api.delete_namespaced_service(
        service_name, namespace)


def delete_if_exists(core_api, service_name, namespace):
    if get(core_api, service_name, namespace):
        logging.info("deleting service '%s' ..." % service_name)
        delete(core_api, service_name, namespace)


def create_load_balancers(core_api, stack_id, role, namespace):
    web = False
    mgmt = False
    splunktcp = False
    tcp = False
    selector = {
        "app": "saas",
        "stack_id": stack_id,
    }
    if role == standalone_role:
        selector["app.kubernetes.io/name"] = "standalone"
        web = mgmt = splunktcp = tcp = True
    elif role == indexer_role:
        selector["app.kubernetes.io/name"] = "indexer"
        splunktcp = tcp = True
    elif role == cluster_master_role:
        selector["app.kubernetes.io/name"] = "cluster-master"
        web = mgmt = True
    elif role == deployer_role:
        selector["app.kubernetes.io/name"] = "deployer"
        web = mgmt = True
    elif role == license_master_role:
        selector["app.kubernetes.io/name"] = "license-master"
        web = mgmt = True
    elif role == search_head_role:
        selector["app.kubernetes.io/name"] = "search-head"
        web = mgmt = True
    else:
        raise Exception("unexpected role")
    ports = []
    if web:
        ports.append(kubernetes.V1ServicePort(
            name="web",
            port=80,
            protocol="TCP",
            target_port=8000,
        ))
    if mgmt:
        ports.append(kubernetes.V1ServicePort(
            name="mgmt",
            port=8089,
            protocol="TCP",
            target_port=8089,
        ))
    if splunktcp:
        ports.append(kubernetes.V1ServicePort(
            name="splunktcp",
            port=9997,
            protocol="TCP",
            target_port=9997,
        ))
    if tcp:
        ports.append(kubernetes.V1ServicePort(
            name="tcp",
            port=9996,
            protocol="TCP",
            target_port=9996,
        ))
    if role == indexer_role:
        logging.debug("creating load balancers for '%s' ..." % (role))
        label_selector = ",".join([k + "=" + v for k, v in selector.items()])
        logging.debug("label_selector: " + label_selector)
        pods = core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=",".join(
                [k + "=" + v for k, v in selector.items()]),
        ).items
        existing_lbs = core_api.list_namespaced_service(
            namespace=namespace,
            label_selector="app=saas,stack_id=%s,role=%s" % (
                stack_id, indexer_role),
        ).items
        lbs_to_delete = set([lb.metadata.name for lb in existing_lbs])
        for pod in pods:
            load_balancer_name = pod.metadata.name + "-lb"
            if load_balancer_name in lbs_to_delete:
                lbs_to_delete.remove(load_balancer_name)
            if not get(core_api, load_balancer_name, namespace):
                selector["statefulset.kubernetes.io/pod-name"] = pod.metadata.name
                logging.info("creating load balancer for '%s' ..." %
                             (pod.metadata.name))
                core_api.create_namespaced_service(
                    namespace=namespace,
                    body=kubernetes.V1Service(
                        api_version="v1",
                        kind="Service",
                        metadata=kubernetes.V1ObjectMeta(
                            name=load_balancer_name,
                            namespace=namespace,
                            labels={
                                "app": "saas",
                                "stack_id": stack_id,
                                "role": role,
                                "pod": pod.metadata.name,
                            },
                        ),
                        spec=kubernetes.V1ServiceSpec(
                            type="LoadBalancer",
                            selector=selector,
                            ports=ports,
                            external_traffic_policy="Local",
                        ),
                    ),
                )
        for load_balancer_name in lbs_to_delete:
            delete(core_api, load_balancer_name, namespace)
    else:
        load_balancer_name = "splunk-%s-%s-lb" % (stack_id, role)
        if not get(core_api, load_balancer_name, namespace):
            logging.info("creating load balancer for '%s' ..." % (role))
            core_api.create_namespaced_service(
                namespace=namespace,
                body=kubernetes.V1Service(
                    api_version="v1",
                    kind="Service",
                    metadata=kubernetes.V1ObjectMeta(
                        name=load_balancer_name,
                        namespace=namespace,
                        labels={
                            "app": "saas",
                            "stack_id": stack_id,
                            "role": role,
                        },
                    ),
                    spec=kubernetes.V1ServiceSpec(
                        type="LoadBalancer",
                        selector=selector,
                        ports=ports,
                    ),
                ),
            )


def delete_all_load_balancers(core_api, stack_id, namespace):
    load_balancers = core_api.list_namespaced_service(
        namespace=namespace,
        label_selector="app=saas,stack_id=%s" % (stack_id),
    ).items
    for lb in load_balancers:
        delete(core_api, lb.metadata.name, namespace)


def get_load_balancer_hosts(core_api, stack_id, role, namespace):
    result = []
    load_balancers = core_api.list_namespaced_service(
        namespace=namespace,
        label_selector="app=saas,stack_id=%s,role=%s" % (
            stack_id, role),
    ).items
    for service in load_balancers:
        if not service.status:
            continue
        if not service.status.load_balancer:
            continue
        if not service.status.load_balancer.ingress:
            continue
        for ingress in service.status.load_balancer.ingress:
            if ingress.hostname:
                result.append(ingress.hostname)
            if ingress.ip:
                result.append(ingress.ip)
    return result

