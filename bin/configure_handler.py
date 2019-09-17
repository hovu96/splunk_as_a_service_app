import fix_path
from base_handler import BaseRestHandler
from urlparse import parse_qs
import splunklib
import traceback
import errors


class ConfigureHandler(BaseRestHandler):

    default_fields = set([
        "license_master_url",
        "license_master_mode",
        "cluster",
        "deployment_type",
        "indexer_server",
    ])
    defaults_prefix = "default_"

    def handle_POST(self):
        self.response.setHeader(
            'X-SAAS-Is-Configured', self.service.confs["app"]["install"]["is_configured"])
        params = parse_qs(self.request['payload'])

        self.update_defaults(params)

        self.service.confs["app"]["install"].submit({
            "is_configured": 1,
        })
        self.service.apps[self.app].reload()

    def update_defaults(self, params):
        defaults = splunklib.data.record({
            k: params[self.defaults_prefix+k][0] if self.defaults_prefix+k in params else ""
            for k in self.default_fields})

        try:
            indexer_server_count = 0
            for server in defaults.indexer_server.split(","):
                components = server.split(":")
                if len(components) != 2:
                    raise errors.ApplicationError(
                        "Expect format \"<server>:<port>,...\" for indexer server. Got \"%s\"" % (server))
                hostname = components[0].strip()
                port = int(components[1].strip())
                import socket
                s = socket.socket()
                try:
                    s.connect((hostname, port))
                except Exception as e:
                    raise errors.ApplicationError(
                        "Could not connect to indexer server \"%s\": %s" % (server, e))
                finally:
                    s.close()
                indexer_server_count += 1
            if indexer_server_count == 0:
                raise errors.ApplicationError(
                    "Invalid or misssing indexer server")
        except errors.ApplicationError:
            raise
        except Exception:
            self.logger.info(traceback.format_exc())
            raise Exception(traceback.format_exc())

        self.service.confs["defaults"]["general"].submit(defaults)

    def handle_GET(self):

        defaults = self.service.confs["defaults"]["general"]
        defaults_data = {
            self.defaults_prefix+k: defaults[k] if k in defaults else ""
            for k in self.default_fields}

        data = {}
        data.update(defaults_data)
        self.send_json_response(data)
