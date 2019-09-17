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
import clusters


class OperatorCommandBase(object):
    _api_client = None
    _custom_objects_api = None
    _core_api = None

    def __init__(self, service, stack_id, command):
        self.service = service
        self.stack_id = stack_id
        self.command = command

        self.stacks = self.service.kvstore["stacks"].data
        self.config = self.stacks.query_by_id(self.stack_id)

    def stop(self):
        operator_controller.stop_command(
            self.service, self.stack_id, self.command)

    @property
    def api_client(self):
        if not self._api_client:
            self._api_client = clusters.create_client(
                self.service, self.config["cluster"])
        return self._api_client

    @property
    def custom_objects_api(self):
        if not self._custom_objects_api:
            self._custom_objects_api = kubernetes.CustomObjectsApi(
                self.api_client)
        return self._custom_objects_api

    @property
    def core_api(self):
        if not self._core_api:
            self._core_api = kubernetes.CoreV1Api(self.api_client)
        return self._core_api

    def run(self):
        pass

    def save_config(self, updates=None):
        if updates:
            self.config.update(updates)
        self.stacks.update(self.stack_id, json.dumps(self.config))
