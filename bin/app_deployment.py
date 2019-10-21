import fix_path
import os
import logging
import tempfile
import kubernetes_utils
import services
import base64
import splunklib
import clusters


def install_base_apps(service, core_api, stack_id, config_config):
    install_indexer_apps(service, core_api, stack_id, config_config)
    install_search_head_apps(service, core_api, stack_id, config_config)
    install_deployment_server_apps(core_api, stack_id, config_config)


def install_indexer_apps(service, core_api, stack_id, stack_config):
    if stack_config["deployment_type"] == "standalone":
        standalone_pods = core_api.list_namespaced_pod(
            namespace="default",
            label_selector="app=splunk,for=%s,type=standalone" % stack_id,
        ).items
        if len(standalone_pods) != 1:
            logging.warning("expected 1 standalone pod (got %d)" %
                            (len(standalone_pods)))
        else:
            pod = standalone_pods[0]
            path = tar_app(service, core_api, stack_config,
                           pod, "indexer_base")
            install_local_app(core_api, stack_id, pod, path, "indexer_base")
    elif stack_config["deployment_type"] == "distributed":
        cluster_master_pods = core_api.list_namespaced_pod(
            namespace="default",
            label_selector="app=splunk,for=%s,type=cluster-master" % stack_id,
        ).items
        if len(cluster_master_pods) != 1:
            logging.warning("expected 1 cluster master (got %d)" %
                            (len(cluster_master_pods)))
        else:
            pod = cluster_master_pods[0]
            copy_app(service, core_api, stack_config, pod,
                     "indexer_base", "master-apps")
            apply_cluster_bundle(core_api, stack_id)


def install_local_app(core_api, stack_id, pod, pod_local_path, name):
    service = create_client(core_api, stack_id, services.standalone_role)
    try:
        service.post(
            "apps/local",
            filename=True,
            name=pod_local_path,
            update=True,
            explicit_appname=name,
        )
        logging.info("cluster bundle updated")
        # https://docs.splunk.com/Documentation/Splunk/7.3.1/RESTREF/RESTapps#apps.2Flocal
        # state_change_requires_restart
    except splunklib.binding.HTTPError:
        raise


def apply_cluster_bundle(core_api, stack_id):
    service = create_client(core_api, stack_id, services.cluster_master_role)
    try:
        service.post("cluster/master/control/default/apply",
                     ignore_identical_bundle=False)
        logging.info("cluster bundle updated")
    except splunklib.binding.HTTPError as e:
        if e.status == 404:
            logging.info("cluster bundle did not change")
        else:
            raise


def install_search_head_apps(service, core_api, stack_id, stack_config):
    deployer_pods = core_api.list_namespaced_pod(
        namespace="default",
        label_selector="app=splunk,for=%s,type=deployer" % stack_id,
    ).items
    if len(deployer_pods) > 1:
        logging.warning("expected max. 1 deployer (got %d)" %
                        (len(deployer_pods)))
    elif len(deployer_pods) == 1:
        pod = deployer_pods[0]
        copy_app(service, core_api, stack_config, pod,
                 "search_head_base", "shcluster/apps")


def install_deployment_server_apps(core_api, stack_id, stack_config):
    pass


def create_client(core_api, stack_id, role):
    hosts = services.get_load_balancer_hosts(
        core_api, stack_id, role)
    if len(hosts) == 0:
        raise Exception(
            "could not get hostname for load balancer for role %s " % (role))
    secrets = core_api.read_namespaced_secret(
        "splunk-%s-secrets" % stack_id,
        namespace="default",
    )
    password = base64.b64decode(secrets.data["password"])
    service = splunklib.client.Service(
        port=8089,
        scheme="https",
        host=hosts[0],
        username="admin",
        password=password
    )
    service.login()
    return service


def render_app(service, stack_config, source_dir, target_dir):
    import shutil

    cluster_config = clusters.get_cluster_config(service, stack_config["cluster"])

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


def tar_app(service, core_api, stack_config, pod, app_name):
    target_path = "/tmp/splunk-app.tar"
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_path, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(service, stack_config, app_path, temp_dir)
        kubernetes_utils.tar_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace="default",
            local_path=temp_dir,
            remote_path=target_path,
        )
        return target_path
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def copy_app(service, core_api, stack_config, pod, app_name, target_parent_name):
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_parent_name, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(service, stack_config, app_path, temp_dir)
        kubernetes_utils.copy_directory_to_pod(
            core_api=core_api,
            pod=pod.metadata.name,
            namespace="default",
            local_path=temp_dir,
            remote_path="/opt/splunk/etc/%s/%s/" % (
                target_parent_name, app_name),
        )
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
