import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
from urllib.parse import unquote
import tarfile
import tempfile
import apps

conf_name = "app_bundles"


class Bundles(BaseRestHandler):
    def handle_GET(self):
        bundles = self.splunk.confs[conf_name]

        def item(bundle):
            entry = {
                "name": bundle.name,
                "apps": len(bundle.apps.split(","))
            }
            return entry
        self.send_entries([
            item(bundle)
            for bundle in bundles
        ])


class BundleApps(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, bundle_name = os.path.split(path)
        bundle = self.splunk.confs[conf_name][bundle_name]
        app_stanza_names = bundle.apps.split(",")

        def item(app_stanza_name):
            name, version = apps.parse_stanza_name(app_stanza_name)
            entry = {
                "name": name,
                "version": version,
            }
            return entry
        self.send_entries([
            item(app_stanza_name.strip())
            for app_stanza_name in app_stanza_names
            if app_stanza_name.strip()])


def iterate_app_paths(archive):
    app_paths = set()
    for info in archive:
        is_path_within_app = False
        app_path_index = info.name.find(os.sep + "default" + os.sep)
        if app_path_index >= 0:
            is_path_within_app = True
        else:
            app_path_index = info.name.find(os.sep + "local" + os.sep)
            if app_path_index >= 0:
                is_path_within_app = True
        if is_path_within_app:
            app_path = info.name[:app_path_index]
            if app_path not in app_paths:
                app_paths.add(app_path)
                yield app_path


def is_bundle(path):
    app_count = 0
    with tarfile.open(path) as archive:
        for path in iterate_app_paths(archive):
            app_count += 1
            if app_count > 1:
                return True
    return False


def extract_app_from_bundle(bundle, app_path, app_file):
    with tarfile.open(fileobj=app_file, mode='w') as app:
        for file_info in bundle.getmembers():
            if file_info.path.startswith(app_path):
                fileobj = bundle.extractfile(file_info)
                app.addfile(file_info, fileobj)


def add_bundle(splunk, bundle_path, name):
    bundle_apps = []
    with tarfile.open(bundle_path) as bundle:
        for app_path in iterate_app_paths(bundle):
            with tempfile.NamedTemporaryFile() as app_file:
                extract_app_from_bundle(bundle, app_path, app_file)
                app_file.seek(0)
                app_name, app_version = apps.add_app(splunk, app_file.name)
                app_stanza_name = apps.create_stanza_name(app_name, app_version)
                bundle_apps.append(app_stanza_name)
    bundle_name = name
    bundle = splunk.confs[conf_name].create(bundle_name)
    bundle.submit({
        "apps": ",".join(bundle_apps),
    })
    return bundle_name
