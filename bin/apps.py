import fix_path
from base_handler import BaseRestHandler
import tarfile
import os
import json
from ConfigParser import SafeConfigParser
import base64
import urllib2

app_config_fields = set([
    "title",
])


def create_stanza_name(name, version):
    if version:
        return name+":"+version
    else:
        return name


def parse_stanza_name(stanza_name):
    i = stanza_name.find(":")
    if i < 0:
        return stanza_name, None
    else:
        return stanza_name[:i], stanza_name[i+1:]


class AppsHandler(BaseRestHandler):
    def handle_GET(self):
        def item(app):
            entry = {
                k: app[k] for k in app_config_fields if k in app
            }
            name, version = parse_stanza_name(app.name)
            entry.update({
                "name": name,
                "version": version,
            })
            return entry
        self.send_entries([
            item(app)
            for app in self.splunk.confs["apps"]
        ])


class AppHandler(BaseRestHandler):
    @property
    def app(self):
        path = self.request['path']
        path, app_version = os.path.split(path)
        _, app_name = os.path.split(path)
        return urllib2.unquote(app_name), urllib2.unquote(app_version)

    def handle_GET(self):
        app_name, app_version = self.app
        stanza_name = create_stanza_name(app_name, app_version)
        app_config = self.splunk.confs["apps"][stanza_name]
        entry = {
            k: app_config[k] for k in app_config_fields if k in app_config
        }
        self.send_json_response(entry)

    def handle_DELETE(self):
        app_name, app_version = self.app
        remove_app(self.splunk, app_name, app_version)


# class AppStacksHandler(BaseRestHandler):
#    @property
#    def app(self):
#        path = self.request['path']
#        path, app_version = os.path.split(path)
#        _, app_name = os.path.split(path)
#        return urllib2.unquote(app_name), urllib2.unquote(app_version)
#
#    def handle_GET(self):
#        self.send_entries([])

def add_app(splunk, path):
    app_name_from_manifest = None
    app_name_from_conf = None
    app_version_from_manifest = False
    app_version_from_conf = False
    app_title_from_manifest = False
    app_title_from_conf = False
    top_level_dir_names = set()
    with tarfile.open(path) as archive:
        for info in archive:
            if info.name.endswith(os.sep + "app.manifest"):
                manifest_file = archive.extractfile(info)
                manifest = json.load(manifest_file)
                if "info" in manifest:
                    app_info = manifest["info"]
                    if "id" in app_info:
                        app_info_id = app_info["id"]
                        if "name" in app_info_id:
                            app_name_from_manifest = app_info_id["name"]
                        if "version" in app_info_id:
                            app_version_from_manifest = app_info_id["version"]
                    if "title" in app_info:
                        app_title_from_manifest = app_info["title"]
            if info.name.endswith(os.sep + "default" + os.sep + "app.conf"):
                conf_file = archive.extractfile(info)
                conf_parser = SafeConfigParser()
                conf_parser.readfp(conf_file)
                if conf_parser.has_section("id") and conf_parser.has_option("id", "name"):
                    app_name_from_conf = conf_parser.get("id", "name")
                elif conf_parser.has_section("package") and conf_parser.has_option("package", "id"):
                    app_name_from_conf = conf_parser.get("package", "id")
                if conf_parser.has_section("id") and conf_parser.has_option("id", "version"):
                    app_version_from_conf = conf_parser.get("id", "version")
                elif conf_parser.has_section("launcher") and conf_parser.has_option("launcher", "version"):
                    app_version_from_conf = conf_parser.get(
                        "launcher", "version")
                if conf_parser.has_section("launcher") and conf_parser.has_option("launcher", "description"):
                    app_title_from_conf = conf_parser.get(
                        "launcher", "description")
            parent_path_sep = info.name.strip().find(os.sep)
            if parent_path_sep > 0:
                parent_path = info.name.strip()[:parent_path_sep]
            else:
                parent_path = info.name.strip()
            if parent_path not in top_level_dir_names:
                top_level_dir_names.add(parent_path)

    if app_name_from_manifest:
        app_name = app_name_from_manifest
    elif app_name_from_conf:
        app_name = app_name_from_conf
    elif len(top_level_dir_names) == 1:
        app_name = list(top_level_dir_names)[0]
    else:
        raise Exception("Unable to find app name")

    if app_version_from_manifest:
        app_version = app_version_from_manifest
    elif app_version_from_conf:
        app_version = app_version_from_conf
    else:
        app_version = None

    if app_title_from_manifest:
        app_title = app_title_from_manifest
    elif app_title_from_conf:
        app_title = app_title_from_conf
    else:
        app_title = ""

    remove_chunks(splunk, app_name, app_version)
    chunk_count = add_chunks(splunk, path, app_name, app_version)

    stanza_name = create_stanza_name(app_name, app_version)
    apps = splunk.confs["apps"]
    if stanza_name in apps:
        app = apps[stanza_name]
    else:
        app = apps.create(stanza_name)
    app.submit({
        "title": app_title,
        "chunks": chunk_count,
    })
    
    return app_name, app_version


def remove_app(splunk, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    splunk.confs["apps"].delete(stanza_name)
    remove_chunks(splunk, app_name, app_version)


def add_chunks(splunk, path, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    chunk_collection = splunk.kvstore["app_chunk"].data
    CHUNK_SIZE = 1024*100
    chunk_index = 0
    with open(path) as f:
        chunk = f.read(CHUNK_SIZE)
        while chunk:
            chunk_collection.insert(json.dumps({
                "index": chunk_index,
                "app": stanza_name,
                "data": base64.b64encode(chunk),
            }))
            chunk_index += 1
            chunk = f.read(CHUNK_SIZE)
    return chunk_index+1


def remove_chunks(splunk, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    chunk_collection = splunk.kvstore["app_chunk"].data
    chunk_collection.delete(query=json.dumps({
        "app": stanza_name,
    }))
