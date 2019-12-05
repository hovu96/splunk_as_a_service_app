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


def update_apps(splunk, kubernetes, stack_id):
    deploy_support_apps(splunk, kubernetes, stack_id)
    get_currently_deployed_apps(splunk, kubernetes, stack_id)


def get_currently_deployed_apps(
    splunk,
    kubernetes,
    stack_id,
):
    pass


def deploy_support_apps(
    splunk,
    kubernetes,
    stack_id,
):
    updated_deployer_bundle = False
    updated_master_bundle = False
    updated_deployer_bundle_, updated_master_bundle_ = deploy_support_app(
        splunk,
        kubernetes,
        stack_id,
        "saas_support_app_inventory",
        deployer=True,
        cluster_master=True,
    )
    updated_deployer_bundle = updated_deployer_bundle or updated_deployer_bundle_
    updated_master_bundle = updated_master_bundle or updated_master_bundle_
    updated_deployer_bundle_, updated_master_bundle_ = deploy_support_app(
        splunk,
        kubernetes,
        stack_id,
        "saas_support_outputs",
        indexers=True,
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


def deploy_support_app(
    splunk,
    kubernetes,
    stack_id,
    app_name,
    search_heads=False,
    indexers=False,
    deployer=False,
    cluster_master=False
):
    updated_deployer_bundle = False
    updated_cluster_master_bundle = False
    app_version = get_support_app_version(app_name)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    if stack_config["deployment_type"] == "standalone":
        if not is_app_installed_locally(
                splunk, kubernetes, stack_id, services.standalone_role, app_name, app_version):
            pod = get_pod(splunk, kubernetes, stack_id, "standalone")
            install_support_app_into_pod(
                splunk, kubernetes, stack_id, pod, app_name)
    elif stack_config["deployment_type"] == "distributed":
        if cluster_master:
            if not is_app_installed_locally(splunk, kubernetes, stack_id, services.cluster_master_role, app_name, app_version):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                install_support_app_into_pod(
                    splunk, kubernetes, stack_id, pod, app_name)
        if deployer:
            if not is_app_installed_locally(splunk, kubernetes, stack_id, services.deployer_role, app_name, app_version):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                install_support_app_into_pod(
                    splunk, kubernetes, stack_id, pod, app_name)
        if indexers:
            if not is_app_installed_in_folder(splunk, kubernetes, stack_id, services.cluster_master_role, app_name, app_version):
                pod = get_pod(splunk, kubernetes, stack_id, "cluster-master")
                core_api = kuberneteslib.CoreV1Api(kubernetes)
                cluster_config = clusters.get_cluster_config(
                    splunk, stack_config["cluster"])
                copy_app(splunk, core_api, cluster_config, stack_config,
                         pod, app_name, "master-apps")
                updated_cluster_master_bundle = True
        if search_heads:
            if not is_app_installed_in_folder(splunk, kubernetes, stack_id, services.deployer_role, app_name, app_version):
                pod = get_pod(splunk, kubernetes, stack_id, "deployer")
                core_api = kuberneteslib.CoreV1Api(kubernetes)
                cluster_config = clusters.get_cluster_config(
                    splunk, stack_config["cluster"])
                copy_app(splunk, core_api, cluster_config, stack_config, pod,
                         app_name, "shcluster/apps")
                updated_deployer_bundle = True
    return updated_deployer_bundle, updated_cluster_master_bundle


def get_support_app_version(app_name):
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


def is_app_installed_locally(splunk, kubernetes, stack_id, instance_role, app_name, app_version):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    service = instances.create_client(
        core_api, stack_id, stack_config, instance_role)
    try:
        app = service.apps[app_name]
        installed_version = ""
        if "version" in app.content:
            installed_version = app.content["version"]
        logging.debug("installed_version: %s target_version: %s" %
                      (installed_version, app_version))
        if installed_version != app_version:
            logging.info("app '%s' is installed on '%s' but has different version '%s' (looking for version '%s')" %
                         (app_name, instance_role, installed_version, app_version))
            return False
        logging.debug("app '%s' is installed on '%s'" %
                      (app_name, instance_role))
        return True
    except KeyError:
        logging.debug("app '%s' is not installed on '%s'" %
                      (app_name, instance_role))
        return False


def is_app_installed_in_folder(splunk, kubernetes, stack_id, instance_role, app_name, app_version):
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
        "saas_support/app/%s" % (app_name),
        bundle_type=bundle_type
    )
    app_info = json.loads(response.body.read())
    if not app_info["installed"]:
        logging.debug("app '%s' is not installed on '%s'" %
                      (app_name, instance_role))
        return False
    installed_version = ""
    if "version" in app_info:
        installed_version = app_info["version"]
    logging.debug("installed_version: %s target_version: %s" %
                  (installed_version, app_version))
    if installed_version != app_version:
        logging.info("app '%s' is installed on '%s' but has different version '%s' (looking for version '%s')" %
                     (app_name, instance_role, installed_version, app_version))
        return False
    logging.debug("app '%s' is installed on '%s'" %
                  (app_name, instance_role))
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


def render_app(service, cluster_config, stack_config, source_dir, target_dir):
    import shutil

    def recursive_overwrite(src, dest, ignore=None):
        if os.path.isdir(src):
            if not os.path.isdir(dest):
                os.makedirs(dest)
            files = os.listdir(src)
            if ignore is not None:
                ignored = ignore(src, files)
            else:
                ignored = set()
            for f in files:
                if f not in ignored:
                    recursive_overwrite(os.path.join(src, f),
                                        os.path.join(dest, f),
                                        ignore)
        else:
            if src.endswith(".conf"):
                with open(src, "r") as src_file:
                    with open(dest, "w") as dest_file:
                        for line in src_file:
                            line = line.replace(
                                "$saas.cluster.indexer_server$",
                                cluster_config["indexer_server"]
                            )
                            dest_file.write(line)  # +"\n")
            else:
                shutil.copyfile(src, dest)
    recursive_overwrite(source_dir, target_dir)


def install_support_app_into_pod(splunk, kubernetes, stack_id, pod, app_name):
    core_api = kuberneteslib.CoreV1Api(kubernetes)
    stack_config = stacks.get_stack_config(splunk, stack_id)
    cluster_config = clusters.get_cluster_config(
        splunk, stack_config["cluster"])
    path = tar_app(splunk, core_api, cluster_config, stack_config,
                   pod, app_name)
    install_local_app(core_api, stack_id,
                      stack_config, pod, path, app_name)


def tar_app(service, core_api, cluster_config, stack_config, pod, app_name):
    target_path = "/tmp/splunk-app.tar"
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_path, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(service, cluster_config, stack_config, app_path, temp_dir)
        kubernetes_utils.tar_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace=stack_config["namespace"],
            local_path=temp_dir,
            remote_path=target_path,
        )
        return target_path
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def install_local_app(core_api, stack_id, stack_config, pod, pod_local_path, name):
    service = instances.create_client(
        core_api, stack_id, stack_config, pod.metadata.labels["type"])
    try:
        service.post(
            "apps/local",
            filename=True,
            name=pod_local_path,
            update=True,
            explicit_appname=name,
        )
    except splunklib.binding.HTTPError:
        raise


def copy_app(service, core_api, cluster_config, stack_config, pod, app_name, target_parent_name):
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_parent_name, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(service, cluster_config, stack_config, app_path, temp_dir)
        kubernetes_utils.copy_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace=stack_config["namespace"],
            local_path=temp_dir,
            remote_path="/opt/splunk/etc/%s/%s/" % (
                target_parent_name, app_name),
        )
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
