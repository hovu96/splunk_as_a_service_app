import fix_path
import os
import logging
import tempfile
import kubernetes_utils
import services
import base64
import splunklib
import clusters
import stacks
import instances
from kubernetes import client as kuberneteslib
import errors
import json
from configparser import SafeConfigParser
import apps
import stack_apps
import shutil
import tarfile
import io
import pathlib


def update_apps(splunk, kubernetes, stack_id):
    apps = [
        SupportApp(
            "saas_support_app_inventory",
            deployer=True,
            cluster_master=True,
        ),
        SupportApp(
            "saas_support_outputs",
            indexers=True,
        ),
    ]
    for stack_app in stack_apps.get_apps_in_stack(splunk, stack_id):
        apps.append(UserApp(splunk, stack_app))
    deploy_apps(splunk, kubernetes, stack_id, apps)


def deploy_apps(
    splunk,
    kubernetes,
    stack_id,
    apps,
):
    updated_deployer_bundle = False
    updated_master_bundle = False
    for app in apps:
        updated_deployer_bundle_, updated_master_bundle_ = deploy_app(
            splunk,
            kubernetes,
            stack_id,
            app
        )
        updated_deployer_bundle = updated_deployer_bundle or updated_deployer_bundle_
        updated_master_bundle = updated_master_bundle or updated_master_bundle_
    if updated_master_bundle:
        stack_config = stacks.get_stack_config(splunk, stack_id)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        apply_cluster_bundle(core_api, stack_id, stack_config)
    if updated_deployer_bundle:
        stack_config = stacks.get_stack_config(splunk, stack_id)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        push_deployer_bundle(core_api, stack_id, stack_config)


class App(object):
    name = None
    version = None
    search_heads = False
    indexers = False
    deployer = False
    cluster_master = False

    def open_file(self, path, mode):
        raise Exception("not implemented")

    def render_file(self, src_file_path, dest_file_path, cluster_config, stack_config):
        dir_name = os.path.dirname(dest_file_path)
        if not os.path.isdir(dir_name):
            os.makedirs(dir_name)
        if src_file_path.endswith(".conf"):
            with self.open_file(src_file_path, "r") as src_file:
                with open(dest_file_path, "w") as dest_file:
                    for line in src_file:
                        line = line.replace(
                            "$saas.cluster.indexer_server$",
                            cluster_config["indexer_server"]
                        )
                        dest_file.write(line)  # +"\n")
        else:
            with self.open_file(src_file_path, "rb") as src:
                with open(dest_file_path, "wb") as dest:
                    shutil.copyfileobj(src, dest)

    def render(self, cluster_config, stack_config, target_dir):
        raise Exception("not implemented")


class UserApp(App):
    splunk = None
    archive = None

    def __init__(self, splunk, stack_app):
        self.name = stack_app["app_name"]
        self.version = stack_app["app_version"]
        self.splunk = splunk
        self.search_heads = stack_app["deploy_to_search_heads"]
        self.indexers = stack_app["deploy_to_indexers"]
        self.deployer = stack_app["deploy_to_deployer"]
        self.cluster_master = stack_app["deploy_to_cluster_master"]

    def open_file(self, path, mode):
        if mode != "r" and mode != "rb":
            raise Exception("mode not supported")
        file_obj = self.archive.extractfile(path)
        if mode == "rb":
            return file_obj
        memory_file = io.StringIO()
        memory_file.write(file_obj.read().decode("utf-8"))
        memory_file.seek(0)
        return memory_file

    def render(self, cluster_config, stack_config, target_dir):
        with apps.open_app(self.splunk, self.name, self.version) as f:
            with tarfile.open(fileobj=f) as archive:
                self.archive = archive
                try:
                    for info in archive:
                        if not info.isfile():
                            continue
                        rel_src_path = str(pathlib.Path(
                            *pathlib.Path(info.name).parts[1:]))
                        dest_path = os.path.join(target_dir, rel_src_path)
                        self.render_file(
                            info.name, dest_path, cluster_config, stack_config)
                finally:
                    self.archive = None


class SupportApp(App):
    def __init__(self, name,
                 search_heads=False,
                 indexers=False,
                 deployer=False,
                 cluster_master=False
                 ):
        self.name = name
        self.version = self.get_app_version(name)
        self.search_heads = search_heads
        self.indexers = indexers
        self.deployer = deployer
        self.cluster_master = cluster_master

    def get_app_version(self, app_name):
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        app_version = ""
        default_app_conf_path = os.path.join(app_path, "default", "app.conf")
        local_app_conf_path = os.path.join(app_path, "local", "app.conf")
        if os.path.exists(default_app_conf_path):
            conf_parser = SafeConfigParser()
            conf_parser.read(default_app_conf_path)
            app_version = conf_parser.get(
                "launcher", "version", fallback="")
        if not app_version:
            if os.path.exists(local_app_conf_path):
                conf_parser = SafeConfigParser()
                conf_parser.read(local_app_conf_path)
                app_version = conf_parser.get(
                    "launcher", "version", fallback="")
        if not app_version and os.path.exists(default_app_conf_path):
            conf_parser = SafeConfigParser()
            conf_parser.read(default_app_conf_path)
            app_version = conf_parser.get(
                "id", "version", fallback="")
        if not app_version:
            if os.path.exists(local_app_conf_path):
                conf_parser = SafeConfigParser()
                conf_parser.read(local_app_conf_path)
                app_version = conf_parser.get(
                    "id", "version", fallback="")
        return app_version

    def open_file(self, path, mode):
        return open(path, mode)

    def render(self, cluster_config, stack_config, target_dir):
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", self.name)

        def recursive_overwrite(src, dest):
            if os.path.isdir(src):
                if not os.path.isdir(dest):
                    os.makedirs(dest)
                files = os.listdir(src)
                for f in files:
                    recursive_overwrite(os.path.join(
                        src, f), os.path.join(dest, f))
            else:
                self.render_file(src, dest, cluster_config, stack_config)
        recursive_overwrite(app_path, target_dir)


def deploy_app(
    splunk,
    kubernetes,
    stack_id,
    app,
):
    updated_deployer_bundle = False
    updated_cluster_master_bundle = False
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        if not is_app_installed_locally(
                splunk, kubernetes, stack_id, services.standalone_role, app):
            # logging.warning("will install app %s ..." % app.name)
            pod = get_pod(splunk, kubernetes, stack_id, "standalone")
            install_app_into_pod(splunk, kubernetes, stack_id, pod, app)
        else:
            # logging.warning("app %s is already installed" % app.name)
            pass
    elif stack_config["deployment_type"] == "distributed":
        if app.cluster_master:
            if not is_app_installed_locally(splunk, kubernetes, stack_id, services.cluster_master_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                install_app_into_pod(splunk, kubernetes, stack_id, pod, app)
        if app.deployer:
            if not is_app_installed_locally(splunk, kubernetes, stack_id, services.deployer_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                install_app_into_pod(splunk, kubernetes, stack_id, pod, app)
        if app.indexers:
            if not is_app_installed_in_folder(splunk, kubernetes, stack_id, services.cluster_master_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                core_api = kuberneteslib.CoreV1Api(kubernetes)
                cluster_config = clusters.get_cluster_config(
                    splunk, stack_config["cluster"])
                copy_app(splunk, core_api, cluster_config, stack_config,
                         pod, app, "master-apps")
                updated_cluster_master_bundle = True
        if app.search_heads:
            if not is_app_installed_in_folder(splunk, kubernetes, stack_id, services.deployer_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                core_api = kuberneteslib.CoreV1Api(kubernetes)
                cluster_config = clusters.get_cluster_config(
                    splunk, stack_config["cluster"])
                copy_app(splunk, core_api, cluster_config, stack_config, pod,
                         app, "shcluster/apps")
                updated_deployer_bundle = True
    return updated_deployer_bundle, updated_cluster_master_bundle


def is_app_installed_locally(splunk, kubernetes, stack_id, instance_role, app):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    service = instances.create_client(
        core_api, stack_id, stack_config, instance_role)
    try:
        installed_app = service.apps[app.name]
        # logging.warning("installed_app: %s" % (installed_app.content))
        installed_version = ""
        if "version" in installed_app.content:
            installed_version = installed_app.content["version"]
        logging.debug("installed_version: %s target_version: %s" %
                      (installed_version, app.version))
        if installed_version != app.version:
            logging.warning("app '%s' is installed on '%s' but has different version '%s' (looking for version '%s')" %
                            (app.name, instance_role, installed_version, app.version))
            return False
        logging.debug("app '%s' is installed on '%s'" %
                      (app.name, instance_role))
        return True
    except KeyError:
        logging.debug("app '%s' is not installed on '%s'" %
                      (app.name, instance_role))
        return False


def is_app_installed_in_folder(splunk, kubernetes, stack_id, instance_role, app):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    service = instances.create_client(
        core_api, stack_id, stack_config, instance_role)
    if instance_role == services.deployer_role:
        bundle_type = "deployer"
    elif instance_role == services.cluster_master_role:
        bundle_type = "cluster-master"
    else:
        raise Exception("invalid instance_role '%s'" % instance_role)
    response = service.get(
        "saas_support/app/%s" % (app.name),
        bundle_type=bundle_type
    )
    app_info = json.loads(response.body.read())
    if not app_info["installed"]:
        logging.debug("app '%s' is not installed on '%s'" %
                      (app.name, instance_role))
        return False
    installed_version = ""
    if "version" in app_info:
        installed_version = app_info["version"]
    logging.debug("installed_version: %s target_version: %s" %
                  (installed_version, app.version))
    if installed_version != app.version:
        logging.info("app '%s' is installed on '%s' but has different version '%s' (looking for version '%s')" %
                     (app.name, instance_role, installed_version, app.version))
        return False
    logging.debug("app '%s' is installed on '%s'" %
                  (app.name, instance_role))
    return True


def get_pod(splunk, kubernetes, stack_id, type_label):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    pods = core_api.list_namespaced_pod(
        namespace=stack_config["namespace"],
        label_selector="app=splunk,for=%s,type=%s" % (stack_id, type_label),
    ).items
    if len(pods) != 1:
        raise Exception("expected 1 %s pod (got %d)" % (type_label, len(pods)))
    return pods[0]


def is_sh_cluster_restart_in_progress(core_api, stack_id, stack_config):
    search_head_service = instances.create_client(
        core_api, stack_id, stack_config, services.search_head_role)
    logging.info("checking search head cluster status ...")
    response = search_head_service.get(
        "shcluster/status",
        output_mode="json"
    )
    data = json.loads(response.body.read())
    restart_in_progress = data["entry"][0]["content"]["captain"]["rolling_restart_flag"]
    if restart_in_progress:
        logging.info("search head cluster restart in progress")
    else:
        logging.info("search head cluster restart not in progress")
    return restart_in_progress


def push_deployer_bundle(core_api, stack_id, stack_config):
    search_head_hostnames = services.get_load_balancer_hosts(
        core_api, stack_id, services.search_head_role, stack_config["namespace"])
    if len(search_head_hostnames) == 0:
        raise errors.RetryOperation(
            "Waiting for hostname for search heads ...")
    search_head_hostname = search_head_hostnames[0]

    if is_sh_cluster_restart_in_progress(core_api, stack_id, stack_config):
        raise errors.RetryOperation(
            "wait for SH cluster restart process completed ...")

    service = instances.create_client(
        core_api, stack_id, stack_config, services.deployer_role)
    logging.info("pushing deployer bundle...")
    service.post(
        "apps/deploy",
        target="https://%s:8089" % (search_head_hostname),
        action="all",
        advertising="true",
        force="true",
    )

    if is_sh_cluster_restart_in_progress(core_api, stack_id, stack_config):
        raise errors.RetryOperation(
            "wait for SH cluster restart process completed ...")


def apply_cluster_bundle(core_api, stack_id, stack_config):
    service = instances.create_client(
        core_api, stack_id, stack_config, services.cluster_master_role)
    logging.info("applying cluster master bundle...")
    try:
        service.post("cluster/master/control/default/apply",
                     ignore_identical_bundle=False)
        logging.info("cluster bundle updated")
    except splunklib.binding.HTTPError as e:
        if e.status == 404:
            logging.info("cluster bundle did not change")
        else:
            raise


def install_app_into_pod(splunk, kubernetes, stack_id, pod, app):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_config = clusters.get_cluster_config(
        splunk, stack_config["cluster"])
    pod_local_path = "/tmp/%s.tar" % (app.name)
    temp_dir = tempfile.mkdtemp()
    try:
        app.render(cluster_config, stack_config, temp_dir)
        kubernetes_utils.tar_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace=stack_config["namespace"],
            local_path=temp_dir,
            remote_path=pod_local_path,
        )
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    service = instances.create_client(
        core_api, stack_id, stack_config, pod.metadata.labels["type"])
    try:
        service.post(
            "apps/local",
            filename=True,
            name=pod_local_path,
            update=True,
            explicit_appname=app.name,
        )
    except splunklib.binding.HTTPError:
        raise
    logging.info("installed app '%s' into '%s" % (app.name, pod.metadata.name))


def copy_app(service, core_api, cluster_config, stack_config, pod, app, target_parent_name):
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app.name, target_parent_name, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app.render(cluster_config, stack_config, temp_dir)
        kubernetes_utils.copy_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace=stack_config["namespace"],
            local_path=temp_dir,
            remote_path="/opt/splunk/etc/%s/%s/" % (
                target_parent_name, app.name),
        )
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
