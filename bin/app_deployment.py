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
from configparser import ConfigParser
import apps
import stack_apps
import shutil
import tarfile
import io
import pathlib


def update_apps(splunk, kubernetes, stack_id):
    # collect apps to deploy
    apps_to_deploy = [
        SupportApp(
            "saas_support_app_inventory",
            deployer=True,
            cluster_master=True,
            standalone=True
        ),
        SupportApp(
            "saas_support_outputs",
            indexers=True,
            standalone=True,
        ),
    ]
    for stack_app in stack_apps.get_apps_in_stack(splunk, stack_id):
        apps_to_deploy.append(UserApp(splunk, stack_app))
    apps_to_deploy = {a.name: a for a in apps_to_deploy}
    # deploy apps
    roles_requiring_update = set()
    for app in apps_to_deploy.values():
        if app.any_flag_set:
            _updates = deploy_app(splunk, kubernetes, stack_id, app)
            roles_requiring_update.update(_updates)
    # undeploy apps
    for deployed_app in collect_deployed_apps(splunk, kubernetes, stack_id):
        if deployed_app.name in apps_to_deploy:
            app_to_deploy = apps_to_deploy[deployed_app.name]
            if app_to_deploy.search_heads:
                deployed_app.search_heads = False
            if app_to_deploy.indexers:
                deployed_app.indexers = False
            if app_to_deploy.deployer:
                deployed_app.deployer = False
            if app_to_deploy.cluster_master:
                deployed_app.cluster_master = False
            if app_to_deploy.standalone:
                deployed_app.standalone = False
        if deployed_app.any_flag_set:
            _updates = undeploy_app(splunk, kubernetes, stack_id, deployed_app)
            roles_requiring_update.update(_updates)
    # apply app bundles
    if services.indexer_role in roles_requiring_update:
        stack_config = stacks.get_stack_config(splunk, stack_id)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        apply_cluster_bundle(core_api, stack_id, stack_config)
    if services.search_head_role in roles_requiring_update:
        stack_config = stacks.get_stack_config(splunk, stack_id)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        push_deployer_bundle(core_api, stack_id, stack_config)
    if services.cluster_master_role in roles_requiring_update:
        restart_instance(splunk, kubernetes, stack_id, services.cluster_master_role)
    if services.deployer_role in roles_requiring_update:
        restart_instance(splunk, kubernetes, stack_id, services.deployer_role)
    if services.standalone_role in roles_requiring_update:
        restart_instance(splunk, kubernetes, stack_id, services.standalone_role)


class App(object):
    name = None
    version = None
    search_heads = False
    indexers = False
    deployer = False
    cluster_master = False
    standalone = False

    @property
    def any_flag_set(self):
        return self.search_heads or self.indexers or self.deployer or self.cluster_master or self.standalone


class DeployableApp(App):

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


class UserApp(DeployableApp):
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
        self.standalone = stack_app["deploy_to_standalone"]

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


class SupportApp(DeployableApp):
    def __init__(self, name,
                 search_heads=False,
                 indexers=False,
                 deployer=False,
                 cluster_master=False,
                 standalone=False,
                 ):
        self.name = name
        self.version = self.get_app_version(name)
        self.search_heads = search_heads
        self.indexers = indexers
        self.deployer = deployer
        self.cluster_master = cluster_master
        self.standalone = standalone

    def get_app_version(self, app_name):
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        app_version = ""
        default_app_conf_path = os.path.join(app_path, "default", "app.conf")
        local_app_conf_path = os.path.join(app_path, "local", "app.conf")
        if os.path.exists(default_app_conf_path):
            conf_parser = ConfigParser()
            conf_parser.read(default_app_conf_path)
            app_version = conf_parser.get(
                "launcher", "version", fallback="")
        if not app_version:
            if os.path.exists(local_app_conf_path):
                conf_parser = ConfigParser()
                conf_parser.read(local_app_conf_path)
                app_version = conf_parser.get(
                    "launcher", "version", fallback="")
        if not app_version and os.path.exists(default_app_conf_path):
            conf_parser = ConfigParser()
            conf_parser.read(default_app_conf_path)
            app_version = conf_parser.get(
                "id", "version", fallback="")
        if not app_version:
            if os.path.exists(local_app_conf_path):
                conf_parser = ConfigParser()
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


def collect_deployed_apps(splunk, kubernetes, stack_id):
    apps = {}

    def get_app(app_info):
        if app_info["name"] in apps:
            app = apps[app_info["name"]]
        else:
            app = App()
            app.name = app_info["name"]
            app.version = app_info["version"]
            apps[app_info["name"]] = app
        return app
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, services.standalone_role):
            get_app(app_info).standalone = True
    elif stack_config["deployment_type"] == "distributed":
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, services.search_head_role):
            get_app(app_info).search_heads = True
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, services.deployer_role):
            get_app(app_info).deployer = True
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, services.indexer_role):
            get_app(app_info).indexers = True
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, services.cluster_master_role):
            get_app(app_info).cluster_master = True

    return apps.values()


def undeploy_app(splunk, kubernetes, stack_id, app):
    roles_requiring_update = set()

    def delete(target_role):
        stack_config = stacks.get_stack_config(splunk, stack_id)
        instance_role, location = get_apps_role_and_location(splunk, stack_id, target_role)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        service = instances.create_client(core_api, stack_id, stack_config, instance_role)
        response = service.delete("saas_support/app/%s" % (app.name), location=location)
        delete_result = json.loads(response.body.read())
        if delete_result["requires_update"]:
            roles_requiring_update.add(target_role)
        logging.info("undeployed app \"%s\" from %s" % (app.name, instance_role))
    if app.search_heads:
        delete(services.search_head_role)
    if app.indexers:
        delete(services.indexer_role)
    if app.deployer:
        delete(services.deployer_role)
    if app.cluster_master:
        delete(services.cluster_master_role)
    if app.standalone:
        delete(services.standalone_role)
    return roles_requiring_update


def deploy_app(splunk, kubernetes, stack_id, app):
    roles_requiring_update = set()
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        if app.standalone:
            if not is_app_installed(splunk, kubernetes, stack_id, services.standalone_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "standalone")
                if install_as_local_app(splunk, kubernetes, stack_id, pod, app):
                    roles_requiring_update.add(services.standalone_role)
            else:
                pass
    elif stack_config["deployment_type"] == "distributed":
        if app.cluster_master:
            if not is_app_installed(splunk, kubernetes, stack_id, services.cluster_master_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                if install_as_local_app(splunk, kubernetes, stack_id, pod, app):
                    roles_requiring_update.add(services.cluster_master_role)
        if app.deployer:
            if not is_app_installed(splunk, kubernetes, stack_id, services.deployer_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                if install_as_local_app(splunk, kubernetes, stack_id, pod, app):
                    roles_requiring_update.add(services.deployer_role)
        if app.indexers:
            if not is_app_installed(splunk, kubernetes, stack_id, services.indexer_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                copy_app_into_folder(splunk, kubernetes, stack_id, pod, app, "master-apps")
                roles_requiring_update.add(services.indexer_role)
        if app.search_heads:
            if not is_app_installed(splunk, kubernetes, stack_id, services.search_head_role, app):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                copy_app_into_folder(splunk, kubernetes, stack_id, pod, app, "shcluster/apps")
                roles_requiring_update.add(services.search_head_role)
    return roles_requiring_update


def get_apps_role_and_location(splunk, stack_id, target_role):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        if target_role == services.standalone_role:
            service_role = services.standalone_role
            location = "local-apps"
        # elif target==services.forwarder_role:
        #    service_role = services.deployment_server
        #    location = "deploymentapps"
        else:
            raise Exception("target_role \"%s\" not supported" % target_role)
    elif stack_config["deployment_type"] == "distributed":
        if target_role == services.search_head_role:
            service_role = services.deployer_role
            location = "shcluster-apps"
        elif target_role == services.deployer_role:
            service_role = services.deployer_role
            location = "local-apps"
        elif target_role == services.cluster_master_role:
            service_role = services.cluster_master_role
            location = "local-apps"
        elif target_role == services.indexer_role:
            service_role = services.cluster_master_role
            location = "master-apps"
        # elif target_role==services.forwarder_role:
        #    service_role = services.deployment_server
        #    location = "deploymentapps"
        else:
            raise Exception("target_role \"%s\" not supported" % target_role)
    return service_role, location


def list_apps_installed(splunk, kubernetes, stack_id, target_role):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    service_role, location = get_apps_role_and_location(splunk, stack_id, target_role)
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    service = instances.create_client(core_api, stack_id, stack_config, service_role)
    response = service.get("saas_support/apps", location=location)
    app_infos = json.loads(response.body.read())
    return app_infos


def is_app_installed(splunk, kubernetes, stack_id, target_role, app):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    instance_role, location = get_apps_role_and_location(splunk, stack_id, target_role)
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    service = instances.create_client(core_api, stack_id, stack_config, instance_role)
    response = service.get("saas_support/app/%s" % (app.name), location=location)
    app_info = json.loads(response.body.read())
    if not app_info["installed"]:
        logging.debug("app '%s' is not installed on '%s'" % (app.name, instance_role))
        return False
    installed_version = ""
    if "version" in app_info:
        installed_version = app_info["version"]
    logging.debug("installed_version: %s target_version: %s" % (installed_version, app.version))
    if installed_version != app.version:
        logging.info("app '%s' is installed on '%s' but has different version '%s' (looking for version '%s')" % (app.name, instance_role, installed_version, app.version))
        return False
    logging.debug("app '%s' is installed on '%s'" % (app.name, instance_role))
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
    #logging.info("checking search head cluster status ...")
    response = search_head_service.get(
        "shcluster/status",
        output_mode="json"
    )
    data = json.loads(response.body.read())
    restart_in_progress = data["entry"][0]["content"]["captain"]["rolling_restart_flag"]
    if restart_in_progress:
        logging.debug("search head cluster restart in progress")
    else:
        logging.debug("search head cluster restart not in progress")
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
    service.post(
        "apps/deploy",
        target="https://%s:8089" % (search_head_hostname),
        action="all",
        advertising="true",
        force="true",
    )
    logging.info("pushed SH deployer bundle")

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
        #logging.info("cluster bundle updated")
    except splunklib.binding.HTTPError as e:
        if e.status == 404:
            logging.info("cluster bundle did not change")
        else:
            raise


def restart_instance(splunk, kubernetes, stack_id, role):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    service = instances.create_client(core_api, stack_id, stack_config, role)
    try:
        service.restart()
        logging.info("requested \"%s\" restart" % (role))
    except splunklib.binding.HTTPError as e:
        if e.status == 404:
            logging.info("cluster bundle did not change")
        else:
            raise


def render_saas_app_data(path, app):
    local_path = os.path.join(path, "local")
    if not os.path.isdir(local_path):
        os.makedirs(local_path)
    local_app_conf_path = os.path.join(local_path, "app.conf")
    conf = ConfigParser()  # comment_prefixes='/', allow_no_value=True
    if os.path.exists(local_app_conf_path):
        conf.read_file(local_app_conf_path)
    if not conf.has_section("install"):
        conf.add_section("install")
    conf.set("install", "saas_managed", "1")
    with open(local_app_conf_path, "w") as dest_file:
        conf.write(dest_file)

    readme_path = os.path.join(path, "README")
    if os.path.isfile(readme_path):
        os.remove(readme_path)
    if not os.path.isdir(readme_path):
        os.makedirs(readme_path)
    app_conf_spec_path = os.path.join(readme_path, "app.conf.spec")
    conf = ConfigParser()
    if os.path.exists(app_conf_spec_path):
        conf.read_file(app_conf_spec_path)
    if not conf.has_section("install"):
        conf.add_section("install")
    conf.set("install", "saas_managed", "<boolean>")
    with open(app_conf_spec_path, "w") as dest_file:
        conf.write(dest_file)


def install_as_local_app(splunk, kubernetes, stack_id, pod, app):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_config = clusters.get_cluster_config(
        splunk, stack_config["cluster"])
    pod_local_path = "/tmp/%s.tar" % (app.name)
    temp_dir = tempfile.mkdtemp()
    try:
        app.render(cluster_config, stack_config, temp_dir)
        render_saas_app_data(temp_dir, app)
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
    logging.info("installed app '%s' to '%s" % (app.name, pod.metadata.name))
    return False


def copy_app_into_folder(splunk, kubernetes, stack_id, pod, app, target_parent_name):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_config = clusters.get_cluster_config(
        splunk, stack_config["cluster"])
    temp_dir = tempfile.mkdtemp()
    try:
        app.render(cluster_config, stack_config, temp_dir)
        render_saas_app_data(temp_dir, app)
        kubernetes_utils.copy_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace=stack_config["namespace"],
            local_path=temp_dir,
            remote_path="/opt/splunk/etc/%s/%s/" % (
                target_parent_name, app.name),
        )
        logging.info("copied app '%s' at '%s' to '%s'" % (app.name, target_parent_name, pod.metadata.name))
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
