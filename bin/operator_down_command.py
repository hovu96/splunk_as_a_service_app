import fix_path
import logging
import stacks
from operator_command import OperatorCommand
import services


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
            if self.get_splunk():
                self.delete_splunk()
            if self.license_exists():
                self.delete_license()
        except:
            if self.command != "kill":
                raise

        self.save_config({
            "status": stacks.DELETED,
        })
        self.stop()
