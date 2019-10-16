import fix_path
import os
import logging
import tempfile
import kubernetes_utils


def render_app(stack_config, source_dir, target_dir):
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
                                "$saas.stack.indexer_server$",
                                stack_config["indexer_server"]
                            )
                            dest_file.write(line)  # +"\n")
            else:
                shutil.copyfile(src, dest)
    recursive_overwrite(source_dir, target_dir)


def tar_app(core_api, stack_config, pod, app_name):
    target_path = "/tmp/splunk-app.tar"
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_path, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(stack_config, app_path, temp_dir)
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


def copy_app(core_api, stack_config, pod, app_name, target_parent_name):
    logging.info("installing app '%s' into '%s' of '%s' ..." %
                 (app_name, target_parent_name, pod.metadata.name))
    temp_dir = tempfile.mkdtemp()
    try:
        app_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "apps", app_name)
        render_app(stack_config, app_path, temp_dir)
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
