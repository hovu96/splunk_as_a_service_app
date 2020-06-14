import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from kubernetes import client as kuberneteslib
import yaml
import errors


def wait_until_ready(splunk, kubernetes, stack_id, stack_config):
    indexer_cluster = get(splunk, kubernetes, stack_id, stack_config)
    if not indexer_cluster:
        raise Exception("could not find indexer cluster")
    # {
    # 'clusterMasterPhase': 'Ready',
    # 'indexing_ready_flag': True,
    # 'initialized_flag': True,
    # 'maintenance_mode': False,
    # 'peers': [...],
    # 'phase': 'Error',
    # 'readyReplicas': 3,
    # 'replicas': 2,
    # 'selector': 'app.kubernetes.io/instance=splunk-5ee3910afe797e1d1d6e4898-indexer',
    # 'service_ready_flag': True
    # }
    status = indexer_cluster["status"]
    target_indexer_count = int(stack_config["indexer_count"])
    actualy_ready_replica = status["readyReplicas"]
    if target_indexer_count != actualy_ready_replica:
        raise errors.RetryOperation("waiting for target number of indexers (expected %s, got %s)" % (
            target_indexer_count,
            actualy_ready_replica,
        ))
    cluster_master_phase = status["clusterMasterPhase"]
    if cluster_master_phase != "Ready":
        raise errors.RetryOperation("waiting for cluster master to become ready (currently it's in %s phase)" % (
            cluster_master_phase
        ))
    phase = status["phase"]
    if phase != "Ready":
        raise errors.RetryOperation("waiting for indexer cluster to become ready (currently it's in %s phase)" % (
            phase
        ))


def get(splunk, kubernetes, stack_id, stack_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    indexer_clusters = custom_objects_api.list_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        plural="indexerclusters",
        namespace=stack_config["namespace"],
        label_selector="app=saas,stack_id=%s" % stack_id,
    )["items"]
    if len(indexer_clusters) > 1:
        raise Exception("found more than 1 indexer cluster: %s" % len(indexer_clusters))
    if len(indexer_clusters) == 0:
        return None
    indexer_cluster = indexer_clusters[0]
    return indexer_cluster


def update(splunk, kubernetes, stack_id, stack_config):
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    indexer_cluster = get(splunk, kubernetes, stack_id, stack_config)
    if not indexer_cluster:
        raise Exception("could not find indexer cluster")
    indexer_cluster_spec = indexer_cluster["spec"]
    operations = []
    target_replica = int(stack_config["indexer_count"])
    if indexer_cluster_spec["replicas"] != target_replica:
        operations.append({
            "op": "replace",
            "path": "/spec/replicas",
            "value": target_replica,
        })
    if len(operations) > 0:
        custom_objects_api.patch_namespaced_custom_object(
            group="enterprise.splunk.com",
            version="v1alpha2",
            namespace=stack_config["namespace"],
            name=indexer_cluster["metadata"]["name"],
            plural="indexerclusters",
            body=operations,
        )


def deploy(splunk, kubernetes, stack_id, stack_config, cluster_config):
    indexer_cluster = get(splunk, kubernetes, stack_id, stack_config)
    if indexer_cluster:
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
    custom_objects_api = kuberneteslib.CustomObjectsApi(kubernetes)
    custom_objects_api.create_namespaced_custom_object(
        group="enterprise.splunk.com",
        version="v1alpha2",
        namespace=stack_config["namespace"],
        plural="indexerclusters",
        body={
            "apiVersion": "enterprise.splunk.com/v1alpha2",
            "kind": "IndexerCluster",
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
