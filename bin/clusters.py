import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
import splunklib
import errors
from urllib.parse import unquote
import traceback

name_cluster_field = "name"

cluster_fields = set([
    name_cluster_field,
    "auth_mode",
    "cluster_url",
    "cluster_ca",
    "client_cert",
    "client_key",
    "user_token",
    "aws_cluster_name",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_region_name",
    "storage_class",
    "default_splunk_image",
    "indexer_server",
    "license_master_url",
    "license_master_mode",
    "deployment_type",
    "indexer_count",
    "indexer_scaling_mode",
    "max_indexer_count",
    "search_head_count",
    "search_head_scaling_mode",
    "max_search_head_count",
    "namespace",
    "node_selector",
])

cluster_status_connected = "connected"
cluster_status_disconnected = "disconnected"
cluster_status_unknown = "unknown"


def get_cluster_config(service, cluster_name):
    clusters = service.confs["clusters"]
    return clusters[cluster_name]


def get_cluster_defaults(service):
    clusters = service.confs["clusters"]
    defaults = clusters.create("__default__", disabled="1").content
    clusters.delete("__default__")
    return {
        k: defaults[k] if k in defaults else ""
        for k in cluster_fields
    }


def create_client(service, cluster_name):
    import kubernetes_utils
    from kubernetes import client
    cluster = get_cluster_config(service, cluster_name)
    config = kubernetes_utils.create_client_configuration(cluster)
    api_client = client.ApiClient(config)
    return api_client


def validate_cluster(service, record):
    from kubernetes import client
    import kubernetes_utils
    try:
        connection_stanza = splunklib.client.Stanza(
            service, "", skip_refresh=True)
        connection_stanza.refresh(state=splunklib.data.record({
            "content": record
        }))
        config = kubernetes_utils.create_client_configuration(
            connection_stanza)
        api_client = client.ApiClient(config)
        version_api = client.VersionApi(api_client)
        version_api.get_code()
    except errors.ApplicationError as e:
        raise Exception("Could not connect to Kubernetes.\n\n%s" % e)
    except Exception:
        raise Exception(traceback.format_exc())
    try:
        extensions_api = client.ApiextensionsV1beta1Api(api_client)
        crd = extensions_api.read_custom_resource_definition(
            "splunkenterprises.enterprise.splunk.com")
        if crd.spec.version != "v1alpha1":
            raise errors.ApplicationError(
                "Unexpected Splunk Operator version: %s" % crd.spec.version)
    except client.rest.ApiException as e:
        if e.status == 404:
            raise errors.ApplicationError("Could not find Splunk Operator.")
        raise
    except errors.ApplicationError:
        raise
    except Exception:
        raise Exception(traceback.format_exc())
    try:
        indexer_server_count = 0
        for server in record.indexer_server.split(","):
            components = server.split(":")
            if len(components) != 2:
                raise errors.ApplicationError(
                    "Expect format \"<server>:<port>,...\" for indexer server. Got \"%s\"" % (server))
            hostname = components[0].strip()
            port = int(components[1].strip())
            import socket
            s = socket.socket()
            try:
                s.connect((hostname, port))
            except Exception as e:
                raise errors.ApplicationError(
                    "Could not connect to indexer server \"%s\": %s" % (server, e))
            finally:
                s.close()
            indexer_server_count += 1
        if indexer_server_count == 0:
            raise errors.ApplicationError(
                "Invalid or misssing indexer server")
    except errors.ApplicationError:
        raise
    except Exception:
        raise Exception(traceback.format_exc())


class BaseClusterHandler(BaseRestHandler):

    @property
    def clusters(self):
        return self.service.confs.create("clusters")
        # return self.service.confs["clusters"]

    def create_cluster_record_from_payload(self):
        defaults = get_cluster_defaults(self.service)
        return splunklib.data.record({
            k: self.payload[k][0] if k in self.payload else defaults[k] if k in defaults else ""
            for k in cluster_fields if k != name_cluster_field
        })

    def get_cluster_record(self, name):
        cluster = self.clusters[name]
        return splunklib.data.record({
            k: cluster[k] if k in cluster else ""
            for k in cluster_fields
        })


class ClustersHandler(BaseClusterHandler):

    def handle_GET(self):
        def map(d):
            return {
                "name": d.name,
                "status": d["status"] if "status" in d else cluster_status_unknown,
                "error": d["error"] if "error" in d else "",
            }
        self.send_entries([map(c) for c in self.clusters])

    def handle_POST(self):
        cluster_name = self.payload[name_cluster_field][0] if name_cluster_field in self.payload else ""
        if not cluster_name:
            raise Exception("Name missing")
        if cluster_name in self.clusters:
            raise Exception("Cluster name already exists.")
        cluster_record = self.create_cluster_record_from_payload()
        validate_cluster(self.service, cluster_record)
        cluster = self.clusters.create(cluster_name)
        cluster_record.status = cluster_status_connected
        cluster.submit(cluster_record)


class ClusterHandler(BaseClusterHandler):

    @property
    def cluster_name(self):
        path = self.request['path']
        _, cluster_name = os.path.split(path)
        return unquote(cluster_name)

    def handle_GET(self):
        cluster = self.clusters[self.cluster_name]
        result = {
            k: cluster[k] if k in cluster else ""
            for k in cluster_fields
        }
        result.update({
            "name": self.cluster_name,
            "status": cluster["status"] if "status" in cluster else cluster_status_unknown,
        })
        self.send_json_response(result)

    def handle_POST(self):
        cluster_record = self.create_cluster_record_from_payload()
        validate_cluster(self.service, cluster_record)
        cluster = self.clusters[self.cluster_name]
        cluster_record.status = cluster_status_connected
        cluster_record.error = ""
        cluster.submit(cluster_record)

    def handle_DELETE(self):
        self.clusters.delete(self.cluster_name)


class CheckClustersHandler(BaseClusterHandler):
    def handle_POST(self):
        def map(c):
            cluster_record = self.get_cluster_record(c.name)
            try:
                validate_cluster(self.service, cluster_record)
                error = ""
                status = cluster_status_connected
            except Exception as e:
                error = "%s" % e
                status = cluster_status_disconnected
            c.submit({
                "error": error,
                "status": status,
            })
            return {
                "name": c.name,
                "status": status,
                "error": error,
            }
        self.send_entries([map(c) for c in self.clusters])


class ClusterDefaultsHandler(BaseClusterHandler):

    def handle_GET(self):
        defaults = get_cluster_defaults(self.service)
        self.send_json_response(defaults)
