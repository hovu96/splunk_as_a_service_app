import json
import os
import fix_path
from base_handler import BaseRestHandler
import stacks
from kubernetes import client as kubernetes
import kubernetes_utils
import base64
import clusters


class CredentialsHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        stack = self.stacks.query_by_id(
            stack_id)
        if stack["status"] != stacks.CREATED:
            raise Exception("State is not '%s'" % stacks.CREATED)

        api_client = clusters.create_client(
            self.service, stack["cluster"])
        core_api = kubernetes.CoreV1Api(api_client)

        secrets = core_api.read_namespaced_secret(
            "splunk-%s-secrets" % stack_id,
            namespace=stack["namespace"],
        )

        decoded_password = base64.b64decode(secrets.data["password"])

        result = {
            "admin": "%s" % decoded_password,
        }
        self.send_result(result)
