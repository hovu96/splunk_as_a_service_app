import fix_path
import logging
import stacks
from operator_command import OperatorCommand
import services
import stack_deployment


class DownCommand(OperatorCommand):
    def run(self):
        # status = self.config["status"]
        self.save_config({
            "status": stacks.DELETING,
        })
        self.delete_stack()

    def delete_stack(self):

        try:
            services.delete_all_load_balancers(
                self.core_api, self.stack_id, self.config["namespace"])
            if stack_deployment.get_splunk(self.custom_objects_api, self.stack_id, self.config):
                stack_deployment.delete_splunk(
                    self.custom_objects_api, self.stack_id, self.config)
            if stack_deployment.license_exists(self.core_api, self.stack_id, self.config):
                stack_deployment.delete_license(
                    self.core_api, self.stack_id, self.config)
        except:
            if self.command != "kill":
                raise

        self.save_config({
            "status": stacks.DELETED,
        })
        self.stop()
