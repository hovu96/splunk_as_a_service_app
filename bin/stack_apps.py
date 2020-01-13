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
import stack_operation
import apps


def str2bool(v):
    v = "%s" % v
    return v.lower() in ("yes", "true", "t", "1")


def get_stack_apps_collection(splunk):
    return splunk.kvstore["stack_apps"].data


def get(splunk, stack_id, app_name):
    stack_apps_col = get_stack_apps_collection(splunk)
    stack_apps = stack_apps_col.query(
        query=json.dumps({
            "app_name": app_name,
            "stack_id": stack_id,
        }),
    )
    if len(stack_apps) == 0:
        raise Exception("Could not find app in stack")
    return stack_apps[0]


def get_apps_in_stack(splunk, stack_id):
    stack_apps_collection = get_stack_apps_collection(splunk)
    return stack_apps_collection.query(
        query=json.dumps({
            "stack_id": stack_id,
        }),
    )


class AppsInStack(BaseRestHandler):
    def handle_POST(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        if not stacks.stack_exists(self.splunk, stack_id):
            raise Exception("Stack with ID \"%s\" not found" % (stack_id))
        request_params = parse_qs(self.request['payload'])
        app_name = request_params["app_name"][0]
        app_version = request_params["app_version"][0]
        deploy_to = request_params["deploy_to"][0] if "deploy_to" in request_params else ""
        deploy_to = apps.format_deploy_to(apps.parse_deploy_to(deploy_to))
        stack_apps = get_stack_apps_collection(self.splunk)
        existing_apps = stack_apps.query(
            query=json.dumps({
                "app_name": app_name,
                "stack_id": stack_id,
            }),
        )
        if len(existing_apps) > 0:
            existing_app = existing_apps[0]
            raise Exception("App \"%s\" is already installed (Version %s)" % (app_name, existing_app["app_version"]))
        stack_app = {
            "stack_id": stack_id,
            "app_name": app_name,
            "app_version": app_version,
            "deploy_to": deploy_to,
        }
        stack_app.update({
            k: request_params[k][0]
            for k in request_params if k.startswith("conf_")
        })
        stack_app_id = stack_apps.insert(json.dumps(stack_app))["_key"]
        self.send_json_response({
            "stack_app_id": stack_app_id,
        })
        stack_operation.trigger(self.splunk, stack_id)

    def handle_GET(self):
        path = self.request['path']
        _, stack_id = os.path.split(path)
        stack_apps = get_apps_in_stack(self.splunk, stack_id)
        self.send_entries([{
            "app_name": stack_app["app_name"],
            "app_version": stack_app["app_version"],
            "deploy_to": apps.parse_deploy_to(stack_app["deploy_to"]),
        } for stack_app in stack_apps])


class AppInStack(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        path, app_name = os.path.split(path)
        _, stack_id = os.path.split(path)
        stack_app = get(self.splunk, stack_id, app_name)
        self.send_result({
            "app_name": stack_app["app_name"],
            "app_version": stack_app["app_version"],
            "deploy_to": apps.parse_deploy_to(stack_app["deploy_to"]),
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
        stack_operation.trigger(self.splunk, stack_id)

    def handle_POST(self):
        path = self.request['path']
        path, app_name = os.path.split(path)
        _, stack_id = os.path.split(path)
        stack_app = get(self.splunk, stack_id, app_name)
        request_params = parse_qs(self.request['payload'])
        deploy_to = request_params["deploy_to"][0] if "deploy_to" in request_params else ""
        deploy_to = apps.format_deploy_to(apps.parse_deploy_to(deploy_to))
        stack_app["deploy_to"] = deploy_to
        col = get_stack_apps_collection(self.splunk)
        stack_app_id = stack_app["_key"]
        stack_app = {k: v for k, v in stack_app.items() if not k.startswith('_')}
        col.update(stack_app_id, json.dumps(stack_app))
        stack_operation.trigger(self.splunk, stack_id)


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
