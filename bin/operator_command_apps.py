import fix_path
from operator_command_base import OperatorCommandBase
import logging
import kubernetes_utils
import base64
import splunklib.client
import os
import services
import tempfile
import app_deployment


class OperatorCommandApps(OperatorCommandBase, object):

    def create_service_for_load_balancer(self, role):
        hostnames = services.get_load_balancer_hostnames(
            self.core_api, self.stack_id, role)
        if len(hostnames) == 0:
            raise Exception(
                "could not get hostname for load balancer for role %s " % (role))
        secrets = self.core_api.read_namespaced_secret(
            "splunk-%s-secrets" % self.stack_id,
            namespace="default",
        )
        password = base64.b64decode(secrets.data["password"])
        service = splunklib.client.Service(
            port=8089,
            scheme="https",
            host=hostnames[0],
            username="admin",
            password=password
        )
        service.login()
        return service

    def install_base_apps(self):
        self.install_indexer_apps()
        self.install_search_head_apps()
        self.install_deployment_server_apps()

    def install_indexer_apps(self):
        if self.config["deployment_type"] == "standalone":
            standalone_pods = self.core_api.list_namespaced_pod(
                namespace="default",
                label_selector="app=splunk,for=%s,type=standalone" % self.stack_id,
            ).items
            if len(standalone_pods) != 1:
                logging.warning("expected 1 standalone pod (got %d)" %
                                (len(standalone_pods)))
            else:
                pod = standalone_pods[0]
                path = app_deployment.tar_app(
                    self.core_api, self.config, pod, "indexer_base")
                self.install_local_app(pod, path, "indexer_base")
        elif self.config["deployment_type"] == "distributed":
            cluster_master_pods = self.core_api.list_namespaced_pod(
                namespace="default",
                label_selector="app=splunk,for=%s,type=cluster-master" % self.stack_id,
            ).items
            if len(cluster_master_pods) != 1:
                logging.warning("expected 1 cluster master (got %d)" %
                                (len(cluster_master_pods)))
            else:
                pod = cluster_master_pods[0]
                app_deployment.copy_app(
                    self.core_api, self.config, pod, "indexer_base", "master-apps")
                self.apply_cluster_bundle()

    def install_local_app(self, pod, pod_local_path, name):
        service = self.create_service_for_load_balancer(
            services.standalone_role)
        try:
            service.post(
                "apps/local",
                filename=True,
                name=pod_local_path,
                update=True,
                explicit_appname=name,
            )
            logging.info("cluster bundle updated")
            # https://docs.splunk.com/Documentation/Splunk/7.3.1/RESTREF/RESTapps#apps.2Flocal
            # state_change_requires_restart
        except splunklib.binding.HTTPError:
            raise

    def apply_cluster_bundle(self):
        service = self.create_service_for_load_balancer(
            services.cluster_master_role)
        try:
            service.post("cluster/master/control/default/apply",
                         ignore_identical_bundle=False)
            logging.info("cluster bundle updated")
        except splunklib.binding.HTTPError as e:
            if e.status == 404:
                logging.info("cluster bundle did not change")
            else:
                raise

    def install_search_head_apps(self):
        deployer_pods = self.core_api.list_namespaced_pod(
            namespace="default",
            label_selector="app=splunk,for=%s,type=deployer" % self.stack_id,
        ).items
        if len(deployer_pods) > 1:
            logging.warning("expected max. 1 deployer (got %d)" %
                            (len(deployer_pods)))
        elif len(deployer_pods) == 1:
            pod = deployer_pods[0]
            app_deployment.copy_app(
                self.core_api, self.config, pod, "search_head_base", "shcluster/apps")

    def install_deployment_server_apps(self):
        pass
