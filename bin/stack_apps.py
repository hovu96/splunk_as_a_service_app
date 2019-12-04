import os
import sys
bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
from urllib.parse import parse_qs
import json
import stacks


def get_stack_apps_collection(splunk):
    return splunk.kvstore["stack_apps"].data


class AppsInStack(BaseRestHandler):
    def handle_POST(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        if not stacks.stack_exists(self.splunk, stack_id):
            raise Exception("Stack with ID \"%s\" not found" % (stack_id))
        request_params = parse_qs(self.request['payload'])
        app_name = request_params["app_name"][0]
        app_version = request_params["app_version"][0]
        stack_apps = get_stack_apps_collection(self.splunk)
        existing_apps = stack_apps.query(
            query=json.dumps({
                "app_name": app_name,
            }),
        )
        if len(existing_apps) > 0:
            existing_app = existing_apps[0]
            raise Exception(
                "App \"%s\" is already installed (Version %s)" % (app_name, existing_app["app_version"]))
        stack_app = {
            "stack_id": stack_id,
            "app_name": app_name,
            "app_version": app_version,
        }
        stack_app.update({
            k: request_params[k][0]
            for k in request_params if k.startswith("conf_")
        })
        stack_app_id = stack_apps.insert(json.dumps(stack_app))["_key"]
        self.send_json_response({
            "stack_app_id": stack_app_id,
        })

    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        stack_apps_collection = get_stack_apps_collection(self.splunk)
        stack_apps = stack_apps_collection.query(
            query=json.dumps({
                "stack_id": stack_id,
            }),
        )
        self.send_entries([{
            "app_name": stack_app["app_name"],
            "app_version": stack_app["app_version"],
        } for stack_app in stack_apps])


class AppInStack(BaseRestHandler):
    def handle_GET(self):
        self.send_result({
            "test": "hallo",
        })

    def handle_DELETE(self):
        path = self.request['path']
        path, app_name = os.path.split(path)
        _, stack_id = os.path.split(path)
        stack_apps_collection = get_stack_apps_collection(self.splunk)
        stack_apps_collection.delete(
            query=json.dumps({
                "stack_id": stack_id,
                "app_name": app_name,
            }),
        )


class StacksHavingApp(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        path, app_version = os.path.split(path)
        _, app_name = os.path.split(path)
        stack_apps_collection = get_stack_apps_collection(self.splunk)
        stack_apps = stack_apps_collection.query(
            query=json.dumps({
                "app_name": app_name,
                "app_version": app_version,
            }),
        )
        self.send_entries([{
            "stack_id": stack_app["stack_id"],
        } for stack_app in stack_apps])
