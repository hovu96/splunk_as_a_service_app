import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import json
import fix_path
from base_handler import BaseRestHandler
import stacks
from kubernetes import client as kubernetes
import base64
import clusters


class CredentialsHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        admin_password = get_admin_password(self.splunk, stack_id)
        self.send_result({
            "admin": "%s" % admin_password,
        })


def get_admin_password(splunk, stack_id):
    stack = stacks.get_stack_config(splunk, stack_id)
    if stack["status"] != stacks.CREATED:
        raise Exception("State is not '%s'" % stacks.CREATED)

    api_client = clusters.create_client(
        splunk, stack["cluster"])
    core_api = kubernetes.CoreV1Api(api_client)

    secrets = core_api.read_namespaced_secret(
        "splunk-%s-secrets" % stack_id,
        namespace=stack["namespace"],
    )

    encoded_password = secrets.data["password"]
    decoded_password = base64.decodestring(
        encoded_password.encode("ascii")).decode("ascii")

    return decoded_password
