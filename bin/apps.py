import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
import tarfile
import json
from configparser import ConfigParser
import base64
from urllib.parse import unquote
from urllib.parse import parse_qs
import io
import re
import services


def create_stanza_name(name, version):
    if version:
        return name + ":" + version
    else:
        return name


def parse_stanza_name(stanza_name):
    i = stanza_name.find(":")
    if i < 0:
        return stanza_name, None
    else:
        return stanza_name[:i], stanza_name[i + 1:]


def parse_deploy_to(deploy_to):
    if not deploy_to:
        return []
    roles = set()
    for name in deploy_to.split(","):
        s = name.strip()
        if s:
            roles.add(s)
    return list(roles)


def format_deploy_to(roles):
    return ", ".join(roles)


class AppsHandler(BaseRestHandler):
    def handle_GET(self):
        def item(app):
            name, version = parse_stanza_name(app.name)
            entry = {
                "name": name,
                "version": version,
                "title": app["title"],
                "standalone_deploy_to": parse_deploy_to(app["standalone_deploy_to"]),
                "distributed_deploy_to": parse_deploy_to(app["distributed_deploy_to"]),
            }
            return entry
        self.send_entries([
            item(app)
            for app in self.splunk.confs["apps"]
        ])


def get_app_from_path(path, parent_path_segment):
    app_segment_index = path.index(os.sep + parent_path_segment + os.sep)
    name_version_segments_path = path[app_segment_index +
                                      len(parent_path_segment) + 2:]
    name_version_sep_index = name_version_segments_path.find(os.sep)
    if name_version_sep_index >= 0:
        app_name = name_version_segments_path[: name_version_sep_index]
        app_version = name_version_segments_path[name_version_sep_index + 1:]
    else:
        app_name = name_version_segments_path
        app_version = ""
    return unquote(app_name), unquote(app_version)


class AppHandler(BaseRestHandler):

    def handle_GET(self):
        app_name, app_version = get_app_from_path(self.request['path'], "app")
        stanza_name = create_stanza_name(app_name, app_version)
        app_config = self.splunk.confs["apps"][stanza_name]
        entry = {
            "name": app_name,
            "version": app_version,
            "title": app_config["title"],
            "standalone_deploy_to": parse_deploy_to(app_config["standalone_deploy_to"]),
            "distributed_deploy_to": parse_deploy_to(app_config["distributed_deploy_to"]),
        }
        self.send_result(entry)

    def handle_POST(self):
        app_name, app_version = get_app_from_path(self.request['path'], "app")
        stanza_name = create_stanza_name(app_name, app_version)
        app_config = self.splunk.confs["apps"][stanza_name]
        request_params = parse_qs(self.request['payload'])
        app_config.submit({
            "standalone_deploy_to": request_params["standalone_deploy_to"][0] if "standalone_deploy_to" in request_params else "",
            "distributed_deploy_to": request_params["distributed_deploy_to"][0] if "distributed_deploy_to" in request_params else "",
        })

    def handle_DELETE(self):
        app_name, app_version = get_app_from_path(self.request['path'], "app")
        remove_app(self.splunk, app_name, app_version)


class AppFilesHandler(BaseRestHandler):

    def handle_GET(self):
        app_name, app_version = get_app_from_path(
            self.request['path'], "app_config")
        response = {}
        with open_app(self.splunk, app_name, app_version) as file:
            with tarfile.open(fileobj=file) as archive:
                for info in archive:
                    match = re.match(
                        r'^[^/]+/default/([^/]+\.conf)$', info.name)
                    if not match:
                        continue
                    conf_name = match.group(1)
                    conf_file = archive.extractfile(info)
                    conf_file_data = conf_file.read().decode("utf-8")
                    response[conf_name] = conf_file_data
        self.send_json_response(response)


def add_app(splunk, path):
    app_name, app_version, app_title, target_roles = parse_app_metadata(path)

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
        "distributed_deploy_to": format_deploy_to(target_roles),
        # "standalone_deploy_to": "",
    })

    return app_name, app_version


def parse_app_metadata(path):
    app_name_from_manifest = None
    app_name_from_conf = None
    app_version_from_manifest = False
    app_version_from_conf = False
    app_title_from_manifest = False
    app_title_from_conf = False
    top_level_dir_names = set()
    target_roles_from_manifest = set()
    target_roles_interred_from_confs = set()
    target_roles_interred_from_name = set()
    with tarfile.open(path) as archive:
        for info in archive:
            if info.name.endswith(os.sep + "app.manifest"):
                manifest_file = archive.extractfile(info)
                try:
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
                    if "targetWorkloads" not in manifest:
                        manifest["targetWorkloads"] = ["*"]
                    target_workloads = manifest["targetWorkloads"]
                    for target_workload in target_workloads:
                        if target_workload == "_search_heads":
                            target_roles_from_manifest.add(services.search_head_role)
                        if target_workload == "_indexers":
                            target_roles_from_manifest.add(services.indexer_role)
                        if target_workload == "_forwarders":
                            # target_roles_from_manifest.add(services.forwarder_role)
                            pass
                        if target_workload == "*":
                            target_roles_from_manifest.add(services.search_head_role)
                            target_roles_from_manifest.add(services.indexer_role)
                            # target_roles_from_manifest.add(services.forwarder_role)
                except json.decoder.JSONDecodeError:
                    pass
            if info.name.endswith(os.sep + "default" + os.sep + "app.conf"):
                conf_file = archive.extractfile(info)
                conf_file_data = conf_file.read().decode("utf-8")
                conf_parser = ConfigParser()
                conf_parser.read_string(conf_file_data)
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

    if app_name.upper().startswith("DA_") or app_name.upper().startswith("DA-"):
        target_roles_interred_from_name.add(services.search_head_role)
    if app_name.upper().startswith("SA_") or app_name.upper().startswith("SA-"):
        target_roles_interred_from_name.add(services.search_head_role)

    if len(target_roles_from_manifest):
        target_roles = list(target_roles_from_manifest)
    elif len(target_roles_interred_from_name):
        target_roles = list(target_roles_interred_from_name)
    else:
        target_roles = list(target_roles_interred_from_confs)

    return app_name, app_version, app_title, target_roles


def remove_app(splunk, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    splunk.confs["apps"].delete(stanza_name)
    remove_chunks(splunk, app_name, app_version)


def get_app_chunk_collection(splunk):
    return splunk.kvstore["app_chunks"].data


def get_app_chunk_id(app_name, app_version, chunk_index):
    return "app-%s_version-%s_index-%s" % (app_name, app_version, chunk_index)


def add_chunks(splunk, path, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    chunk_collection = get_app_chunk_collection(splunk)
    CHUNK_SIZE = 1024 * 1000
    chunk_count = 0
    with open(path, 'rb') as f:
        chunk = f.read(CHUNK_SIZE)
        while chunk:
            chunk_encoded = base64.encodestring(chunk)
            chunk_ascii = chunk_encoded.decode('ascii')
            chunk_id = get_app_chunk_id(app_name, app_version, chunk_count)
            chunk_record = json.dumps({
                "index": chunk_count,
                "app": stanza_name,
                "data": chunk_ascii,
                "_key": chunk_id
            })
            chunk_collection.insert(chunk_record)
            chunk_count += 1
            chunk = f.read(CHUNK_SIZE)
    return chunk_count


def remove_chunks(splunk, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    chunk_collection = get_app_chunk_collection(splunk)
    chunk_collection.delete(query=json.dumps({
        "app": stanza_name,
    }))


def open_app(splunk, app_name, app_version):
    stanza_name = create_stanza_name(app_name, app_version)
    app_config = splunk.confs["apps"][stanza_name]
    chunk_count = int(app_config["chunks"])
    chunk_collection = get_app_chunk_collection(splunk)
    app_file = io.BytesIO()
    for chunk_index in range(chunk_count):
        chunk_id = get_app_chunk_id(app_name, app_version, chunk_index)
        chunk = chunk_collection.query_by_id(chunk_id)
        data_encoded = chunk["data"].encode("ascii")
        data_decoded = base64.decodebytes(data_encoded)
        app_file.write(data_decoded)
    app_file.seek(0)
    # TODO validate of chunks
    return app_file
