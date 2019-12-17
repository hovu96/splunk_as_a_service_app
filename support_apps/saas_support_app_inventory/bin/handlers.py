import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from urllib.parse import parse_qs
import splunk.rest
import splunklib.client as client
import json
from configparser import ConfigParser
import shutil

this_app_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))


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

    @property
    def splunk(self):
        if self._splunk != None:
            return self._splunk
        self._splunk = client.Service(
            token=self.request["systemAuth"],  # self.sessionKey,
            sharing="app",
            app=this_app_name,
        )
        return self._splunk


def is_saas_managed(app_path):
    if not os.path.isdir(app_path):
        return False
    app_conf_path = os.path.join(app_path, "local", "app.conf")
    if not os.path.exists(app_conf_path):
        return False
    conf_parser = ConfigParser()
    conf_parser.read(app_conf_path)
    saas_managed_str = conf_parser.get(
        "install", "saas_managed", fallback="0")

    def str2bool(v):
        v = "%s" % v
        return v.lower() in ("yes", "true", "t", "1")
    return str2bool(saas_managed_str)


def get_app_info(app_path):
    if not os.path.isdir(app_path):
        return {
            "installed": False,
        }
    app_conf_path = os.path.join(app_path, "default", "app.conf")
    _, app_name = os.path.split(app_path)
    if os.path.exists(app_conf_path):
        conf_parser = ConfigParser()
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
        "name": app_name,
        "installed": True,
    }


def get_app_location(handler):
    payload = parse_qs(handler.request['payload'])
    if "location" in handler.request["query"]:
        location = handler.request["query"]["location"]
    elif "location" in payload:
        location = payload["location"][0]
    else:
        raise Exception("missing location")
    return location


def get_apps_path(handler):
    location = get_app_location(handler)
    if location == "shcluster/apps":
        folder_path = "/opt/splunk/etc/shcluster/apps"
    elif location == "master-apps":
        folder_path = "/opt/splunk/etc/master-apps"
    elif location == "apps":
        folder_path = "/opt/splunk/etc/apps"
    else:
        raise Exception("unexpected location '%s'" % (location))
    return folder_path


class AppsHandler(BaseRestHandler):
    def handle_GET(self):
        folder_path = get_apps_path(self)
        app_names = [name for name in os.listdir(
            folder_path) if os.path.isdir(os.path.join(folder_path, name))]
        app_paths = [os.path.join(folder_path, name) for name in app_names]
        app_infos = [get_app_info(path) for path in app_paths if is_saas_managed(path)]
        self.send_json_response(app_infos)


class AppHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, app_name = os.path.split(path)
        folder_path = get_apps_path(self)
        app_path = os.path.join(folder_path, app_name)
        app_info = get_app_info(app_path)
        self.send_json_response(app_info)

    def handle_DELETE(self):
        path = self.request['path']
        _, app_name = os.path.split(path)
        location = get_app_location(self)
        requires_update = False
        if location == "apps":
            app = self.splunk.apps[app_name]
            app.delete()
            requires_update = self.splunk.restart_required
        else:
            folder_path = get_apps_path(self)
            app_path = os.path.join(folder_path, app_name)
            if not is_saas_managed(app_path):
                raise Exception("is not saas-managed app")
            shutil.rmtree(app_path)
            requires_update = True
        self.send_json_response({
            "requires_update": requires_update,
        })
