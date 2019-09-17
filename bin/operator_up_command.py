import fix_path
import logging
import stacks
from operator_command import OperatorCommand
import services
import time


class UpCommand(OperatorCommand):
    def run(self):
        status = self.config["status"]
        if status == stacks.CREATING:
            self.create_deployment()
        elif status == stacks.CREATED:
            self.check_deployment()
        else:
            self.stop()

    def create_deployment(self):
        if not self.license_exists():
            logging.info("deploying license ...")
            self.create_license()
        if not self.get_splunk():
            logging.info("deploying Splunk ...")
            self.create_splunk()

        if not self.wait_until_pod_created():
            logging.warning("could not find all pods")
            return

        self.create_load_balancers()

        if not self.wait_until_splunk_instance_completed():
            logging.warning("splunk could not complete startup")
            return

        self.install_base_apps()

        logging.info("created")
        self.save_config({
            "status": stacks.CREATED,
        })

    def wait_until_pod_created(self, timeout=60*15):
        expected_number_of_instances = 0
        if self.config["deployment_type"] == "standlone":
            expected_number_of_instances += 1
        elif self.config["deployment_type"] == "distributed":
            search_head_count = int(self.config["search_head_count"])
            if search_head_count > 1:
                expected_number_of_instances += 1
            if search_head_count > 0:
                expected_number_of_instances += search_head_count
            expected_number_of_instances += 2
            indexer_count = int(self.config["indexer_count"])
            if indexer_count > 0:
                expected_number_of_instances += indexer_count

        logging.info("waiting for pod beeing created...")
        t_end = time.time() + timeout
        while time.time() < t_end:
            pods = self.core_api.list_namespaced_pod(
                namespace="default",
                label_selector="app=splunk,for=%s" % self.stack_id,
            ).items
            if len(pods) == expected_number_of_instances:
                return True
            logging.info("expecting %s pods (found %d)" %
                         (expected_number_of_instances, len(pods)))
            time.sleep(1)
        return False

    def create_load_balancers(self):
        if self.config["deployment_type"] == "standlone":
            services.create_load_balancers(
                self.core_api,
                self.stack_id,
                services.standalone_role,
            )
        elif self.config["deployment_type"] == "distributed":
            if int(self.config["search_head_count"]) > 1:
                services.create_load_balancers(
                    self.core_api,
                    self.stack_id,
                    services.deployer_role,
                )
            if int(self.config["search_head_count"]) > 0:
                services.create_load_balancers(
                    self.core_api,
                    self.stack_id,
                    services.search_head_role,
                )
            services.create_load_balancers(
                self.core_api,
                self.stack_id,
                services.license_master_role,
            )
            if int(self.config["indexer_count"]) > 0:
                services.create_load_balancers(
                    self.core_api,
                    self.stack_id,
                    services.cluster_master_role,
                )
                services.create_load_balancers(
                    self.core_api,
                    self.stack_id,
                    services.indexer_role,
                )
        #getaddrinfo(host, port, 0, SOCK_STREAM)

    def wait_until_splunk_instance_completed(self, timeout=60*15):
        logging.info("waiting for splunk instances to complete...")
        t_end = time.time() + timeout
        while time.time() < t_end:
            pods = self.core_api.list_namespaced_pod(
                namespace="default",
                label_selector="app=splunk,for=%s" % self.stack_id,
            ).items
            number_of_pods_completed = 0
            for p in pods:
                if self.check_splunk_instance_completed(p):
                    number_of_pods_completed += 1
            if number_of_pods_completed == len(pods):
                logging.info("all pods completed startup")
                return True
            else:
                logging.info("Waiting for %d (out of %d) remaining pod(s) to complete startup ...",
                             (len(pods)-number_of_pods_completed), len(pods))
                time.sleep(5)
        return False

    def check_splunk_instance_completed(self, pod):
        #logging.info("pod %s" % (pod.metadata.name))
        if pod.status.phase != "Running":
            logging.info("pod=\"%s\" not yet running (still %s)" %
                         (pod.metadata.name, pod.status.phase))
            return False
        logs = self.core_api.read_namespaced_pod_log(
            name=pod.metadata.name,
            namespace="default",
            tail_lines=100,
        )
        if "Ansible playbook complete" in logs:
            logging.info("pod=\"%s\" status=\"completed\"" % pod.metadata.name)
            return True
        else:
            logging.info("pod=\"%s\" status=\"not_yet_completed\"" %
                         pod.metadata.name)
            return False

    def check_deployment(self):
        pass
