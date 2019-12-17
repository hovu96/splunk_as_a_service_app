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
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        apps_to_deploy = [
            SupportApp(
                "saas_support_app_inventory", [
                    services.standalone_role
                ]
            ),
            SupportApp(
                "saas_support_outputs", [
                    services.standalone_role
                ]
            ),
        ]
    elif stack_config["deployment_type"] == "distributed":
        apps_to_deploy = [
            SupportApp(
                "saas_support_app_inventory", [
                    services.deployer_role,
                    services.cluster_master_role]
            ),
            SupportApp(
                "saas_support_outputs", [
                    services.indexer_role
                ]
            ),
        ]
    for stack_app in stack_apps.get_apps_in_stack(splunk, stack_id):
        apps_to_deploy.append(UserApp(splunk, stack_app))
    apps_to_deploy = {a.name: a for a in apps_to_deploy}
    # deploy apps
    roles_requiring_update = set()
    for app in apps_to_deploy.values():
        if len(app.roles):
            _updates = deploy_app(splunk, kubernetes, stack_id, app)
            roles_requiring_update.update(_updates)
    # undeploy apps
    for deployed_app in collect_deployed_apps(splunk, kubernetes, stack_id):
        if deployed_app.name in apps_to_deploy:
            app_to_deploy = apps_to_deploy[deployed_app.name]
            deployed_app.roles -= app_to_deploy.roles
        if len(deployed_app.roles):
            _updates = undeploy_app(splunk, kubernetes, stack_id, deployed_app)
            roles_requiring_update.update(_updates)
    # restart/deploy config bundle
    for role in roles_requiring_update:
        if role == services.cluster_master_role or role == services.deployer_role or role == services.standalone_role:
            restart_instance(splunk, kubernetes, stack_id, role)
        elif role == services.indexer_role:
            stack_config = stacks.get_stack_config(splunk, stack_id)
            core_api = kuberneteslib.CoreV1Api(kubernetes)
            apply_cluster_bundle(core_api, stack_id, stack_config)
        elif role == services.search_head_role:
            stack_config = stacks.get_stack_config(splunk, stack_id)
            core_api = kuberneteslib.CoreV1Api(kubernetes)
            push_deployer_bundle(core_api, stack_id, stack_config)


class App(object):
    name = None
    version = None
    roles = None

    def __init__(self, name, version, roles):
        self.name = name
        self.version = version
        self.roles = set(roles)


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
        roles = []
        if stack_app["deploy_to_search_heads"]:
            roles.append(services.search_head_role)
        if stack_app["deploy_to_indexers"]:
            roles.append(services.indexer_role)
        if stack_app["deploy_to_deployer"]:
            roles.append(services.deployer_role)
        if stack_app["deploy_to_cluster_master"]:
            roles.append(services.cluster_master_role)
        if stack_app["deploy_to_standalone"]:
            roles.append(services.standalone_role)
        self.splunk = splunk
        DeployableApp.__init__(self,
                               name=stack_app["app_name"],
                               version=stack_app["app_version"],
                               roles=roles)

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
    def __init__(self, name, roles):
        version = self.get_app_version(name)
        DeployableApp.__init__(self, name, version, roles)

    def get_app_version(self, app_name):
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "support_apps", app_name)
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
            os.path.dirname(__file__)), "support_apps", self.name)

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
    stack_config = stacks.get_stack_config(splunk, stack_id)
    roles = set()
    if stack_config["deployment_type"] == "standalone":
        roles.add(services.standalone_role)
    elif stack_config["deployment_type"] == "distributed":
        roles.update([
            services.deployer_role,
            services.search_head_role,
            services.indexer_role,
            services.cluster_master_role,
        ])
    apps = {}
    for role in roles:
        for app_info in list_apps_installed(splunk, kubernetes, stack_id, role):
            if app_info["name"] in apps:
                app = apps[app_info["name"]]
            else:
                app = App(app_info["name"], app_info["version"], [])
                apps[app_info["name"]] = app
            app.roles.add(role)
    return apps.values()


def undeploy_app(splunk, kubernetes, stack_id, app):
    roles_requiring_update = set()
    for role in app.roles:
        stack_config = stacks.get_stack_config(splunk, stack_id)
        instance_role, location = get_apps_role_and_location(splunk, stack_id, role)
        core_api = kuberneteslib.CoreV1Api(kubernetes)
        service = instances.create_client(core_api, stack_id, stack_config, instance_role)
        response = service.delete("saas_support/app/%s" % (app.name), location=location)
        delete_result = json.loads(response.body.read())
        if delete_result["requires_update"]:
            roles_requiring_update.add(role)
        logging.info("undeployed app \"%s\" from %s" % (app.name, instance_role))
    return roles_requiring_update


def deploy_app(splunk, kubernetes, stack_id, app):
    roles_requiring_update = set()
    for role in app.roles:
        if not is_app_installed(splunk, kubernetes, stack_id, role, app):
            service_role, location = get_apps_role_and_location(splunk, stack_id, role)
            if role == service_role and location == "apps":
                pod = get_pod(splunk, kubernetes, stack_id, role)
                if install_as_local_app(splunk, kubernetes, stack_id, pod, app):
                    roles_requiring_update.add(role)
            else:
                pod = get_pod(splunk, kubernetes, stack_id, service_role)
                copy_app_into_folder(splunk, kubernetes, stack_id, pod, app, location)
                roles_requiring_update.add(role)
    return roles_requiring_update


def get_apps_role_and_location(splunk, stack_id, target_role):
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        if target_role == services.standalone_role:
            service_role = services.standalone_role
            location = "apps"
        # elif target==services.forwarder_role:
        #    service_role = services.deployment_server
        #    location = "deploymentapps"
        else:
            raise Exception("target_role \"%s\" not supported" % target_role)
    elif stack_config["deployment_type"] == "distributed":
        if target_role == services.search_head_role:
            service_role = services.deployer_role
            location = "shcluster/apps"
        elif target_role == services.deployer_role:
            service_role = services.deployer_role
            location = "apps"
        elif target_role == services.cluster_master_role:
            service_role = services.cluster_master_role
            location = "apps"
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
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if app.name == "saas_support_app_inventory":
        instance_role = target_role
        service = instances.create_client(core_api, stack_id, stack_config, target_role)
        try:
            installed_app = service.apps[app.name]
        except KeyError:
            logging.debug("app '%s' is not installed on '%s'" % (app.name, target_role))
            return False
        logging.debug("installed_app: %s" % (installed_app.content))
        installed_version = ""
        if "version" in installed_app.content:
            installed_version = installed_app.content["version"]
    else:
        instance_role, location = get_apps_role_and_location(splunk, stack_id, target_role)
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
    service = instances.create_client(core_api, stack_id, stack_config, pod.metadata.labels["type"])
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
    return service.restart_required


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
