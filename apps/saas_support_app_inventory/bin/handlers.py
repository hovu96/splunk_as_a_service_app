import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from urllib.parse import parse_qs
import splunk.rest
import splunklib.client as client
import json
from configparser import SafeConfigParser


class BaseRestHandler(splunk.rest.BaseRestHandler):
    _splunk = None
    _payload = None

    @property
    def payload(self):
        if self._payload != None:
            return self._payload
        _payload = parse_qs(self.request['payload'])
        return _payload

    def send_json_response(self, object):
        self.response.setStatus(200)
        self.response.setHeader('content-type', 'application/json')
        self.response.write(json.dumps(object))


def get_app_info(app_path):
    if not os.path.isdir(app_path):
        return {
            "installed": False,
        }
    app_conf_path = os.path.join(app_path, "default", "app.conf")
    if os.path.exists(app_conf_path):
        conf_parser = SafeConfigParser()
        conf_parser.read(app_conf_path)
        app_version = conf_parser.get(
            "launcher", "version", fallback="")
        if not app_version:
            app_version = conf_parser.get(
                "id", "version", fallback="")
    else:
        app_version = ""
    return {
        "version": app_version,
        "installed": True,
    }


def get_bundle_path(handler):
    payload = parse_qs(handler.request['payload'])
    if "bundle_type" in handler.request["query"]:
        bundle_type = handler.request["query"]["bundle_type"]
    elif "bundle_type" in payload:
        bundle_type = payload["bundle_type"][0]
    else:
        raise Exception("missing bundle type")
    if bundle_type == "deployer":
        folder_path = "/opt/splunk/etc/shcluster/apps"
    elif bundle_type == "cluster-master":
        folder_path = "/opt/splunk/etc/master-apps"
    else:
        raise Exception("unexpected bundle type '%s'" % (bundle_type))
    return folder_path


class AppsHandler(BaseRestHandler):
    def handle_GET(self):
        folder_path = get_bundle_path(self)
        app_names = [name for name in os.listdir(
            folder_path) if os.path.isdir(os.path.join(folder_path, name))]
        app_paths = [os.path.join(folder_path, name) for name in app_names]
        app_infos = [get_app_info(path) for path in app_paths]
        self.send_json_response(app_infos)


class AppHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, app_name = os.path.split(path)
        folder_path = get_bundle_path(self)
        app_path = os.path.join(folder_path, app_name)
        app_info = get_app_info(app_path)
        self.send_json_response(app_info)
