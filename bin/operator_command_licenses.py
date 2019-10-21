import fix_path
import sys
import os
import time
import json
import traceback
import logging
from kubernetes import client as kubernetes
import splunklib.client
import kubernetes_utils
import operator_controller
from operator_command_base import OperatorCommandBase


class OperatorCommandLicenses(OperatorCommandBase, object):

    def license_exists(self):
        try:
            self.core_api.read_namespaced_config_map(
                namespace="default",
                name=self.stack_id,
            )
            return True
        except kubernetes.rest.ApiException as e:
            if e.status == 404:
                return False
            raise

    def create_license(self):
        enterprise_license = self.config["enterprise_license"] if "enterprise_license" in self.config else ""
        self.core_api.create_namespaced_config_map(
            "default",
            kubernetes.V1ConfigMap(
                data={
                    "enterprise.lic": enterprise_license,
                },
                api_version="v1",
                kind="ConfigMap",
                metadata=kubernetes.V1ObjectMeta(
                    name=self.stack_id,
                    namespace="default",
                )
            )
        )

    def delete_license(self):
        self.core_api.delete_namespaced_config_map(
            self.stack_id,
            "default"
        )
