import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

from kubernetes import client
from kubernetes.stream import stream
import base64
import re
import tempfile
import errors
import logging


def create_client_configuration(connection_stanza):
    config = client.Configuration()

    if connection_stanza.auth_mode == "aws-iam":
        # https://github.com/kubernetes-sigs/aws-iam-authenticator
        # https://aws.amazon.com/de/about-aws/whats-new/2019/05/amazon-eks-simplifies-kubernetes-cluster-authentication/
        # https://github.com/aws/aws-cli/blob/develop/awscli/customizations/eks/get_token.py

        # get cluster info
        import boto3
        eks_client = boto3.client('eks',
                                  region_name=connection_stanza.aws_region_name,
                                  aws_access_key_id=connection_stanza.aws_access_key_id,
                                  aws_secret_access_key=connection_stanza.aws_secret_access_key)
        cluster_info = eks_client.describe_cluster(
            name=connection_stanza.aws_cluster_name)
        aws_cluster_ca = cluster_info['cluster']['certificateAuthority']['data']
        aws_cluster_url = cluster_info['cluster']['endpoint']

        # get authentication token
        from botocore.signers import RequestSigner
        STS_TOKEN_EXPIRES_IN = 60
        session = boto3.Session(
            region_name=connection_stanza.aws_region_name,
            aws_access_key_id=connection_stanza.aws_access_key_id,
            aws_secret_access_key=connection_stanza.aws_secret_access_key
        )
        sts_client = session.client('sts')
        service_id = sts_client.meta.service_model.service_id
        token_signer = RequestSigner(
            service_id,
            connection_stanza.aws_region_name,
            'sts',
            'v4',
            session.get_credentials(),
            session.events
        )
        signed_url = token_signer.generate_presigned_url(
            {
                'method': 'GET',
                'url': 'https://sts.{}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15'.format(connection_stanza.aws_region_name),
                'body': {},
                'headers': {
                    'x-k8s-aws-id': connection_stanza.aws_cluster_name
                },
                'context': {}
            },
            region_name=connection_stanza.aws_region_name,
            expires_in=STS_TOKEN_EXPIRES_IN,
            operation_name=''
        )
        base64_url = base64.urlsafe_b64encode(
            signed_url.encode('utf-8')).decode('utf-8')
        auth_token = 'k8s-aws-v1.' + re.sub(r'=*', '', base64_url)

        config.host = aws_cluster_url
        ca_data = base64.standard_b64decode(aws_cluster_ca)
        fp = tempfile.NamedTemporaryFile(delete=False)   # TODO when to delete?
        fp.write(ca_data)
        fp.close()
        config.ssl_ca_cert = fp.name
        config.api_key["authorization"] = auth_token
        config.api_key_prefix["authorization"] = "Bearer"

    elif connection_stanza.auth_mode == "cert-key":
        config.host = connection_stanza.cluster_url

        if connection_stanza.client_cert:
            try:
                cert_data = base64.standard_b64decode(
                    connection_stanza.client_cert)
                fp = tempfile.NamedTemporaryFile(
                    delete=False)   # TODO when to delete?
                fp.write(cert_data)
                fp.close()
                config.cert_file = fp.name
            except Exception as e:
                raise errors.ApplicationError(
                    "Error applying cluster cert: %s" % (e))

        if connection_stanza.client_key:
            try:
                key_data = base64.standard_b64decode(
                    connection_stanza.client_key)
                fp = tempfile.NamedTemporaryFile(
                    delete=False)   # TODO when to delete?
                fp.write(key_data)
                fp.close()
                config.key_file = fp.name
            except Exception as e:
                raise errors.ApplicationError(
                    "Error applying cluster key: %s" % (e))

        if connection_stanza.cluster_ca:
            try:
                cluster_ca_data = base64.standard_b64decode(
                    connection_stanza.cluster_ca)
                fp = tempfile.NamedTemporaryFile(
                    delete=False)   # TODO when to delete?
                fp.write(cluster_ca_data)
                fp.close()
                config.ssl_ca_cert = fp.name
            except Exception as e:
                raise errors.ApplicationError(
                    "Error applying cluster ca: %s" % (e))

        config.verify_ssl = False

    elif connection_stanza.auth_mode == "user-token":
        config.host = connection_stanza.cluster_url
        config.api_key["authorization"] = connection_stanza.user_token
        config.api_key_prefix["authorization"] = "Bearer"
        config.verify_ssl = False

    else:
        raise Exception("invalid auth mode '%s'" % connection_stanza.auth_mode)

    return config


def tar_directory_to_pod(core_api, pod, namespace, local_path, remote_path):
    import tarfile
    from tempfile import TemporaryFile
    with TemporaryFile() as tar_buffer:
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            tar.add(
                name=local_path,
                arcname="/"
            )
        tar_buffer.seek(0)
        exec_in_pod(core_api, pod, namespace, tar_buffer,
                    ['sudo', '-u', 'splunk', 'tee', remote_path])


def copy_directory_to_pod(core_api, pod, namespace, local_path, remote_path):
    import tarfile
    from tempfile import TemporaryFile
    with TemporaryFile() as tar_buffer:
        with tarfile.open(fileobj=tar_buffer, mode='w') as tar:
            tar.add(
                name=local_path,
                arcname=remote_path
            )
        tar_buffer.seek(0)
        exec_in_pod(core_api, pod, namespace, tar_buffer,
                    ['sudo', '-u', 'splunk', 'tar', 'xvf', '-', '-C', '/'])


def exec_in_pod(core_api, pod, namespace, stdin, command):
    resp = stream(
        core_api.connect_get_namespaced_pod_exec,
        pod,
        namespace,
        command=command,
        stderr=True,
        stdin=True,
        stdout=True,
        tty=False,
        _preload_content=False
    )
    commands = []
    commands.append(stdin.read())
    while resp.is_open():
        resp.update(timeout=1)
        # if resp.peek_stdout():
        #    logging.info("STDOUT: %s" % resp.read_stdout())
        # if resp.peek_stderr():
        #    logging.error("STDERR: %s" % resp.read_stderr())
        if commands:
            c = commands.pop(0)
            # https://stackoverflow.com/questions/54108278/kubectl-cp-in-kubernetes-python-client
            # resp.write_stdin(c.decode())
            resp.write_stdin(c)
        else:
            break
    resp.close()
