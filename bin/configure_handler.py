import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
from urllib.parse import parse_qs
import splunklib
import traceback
import errors


class ConfigureHandler(BaseRestHandler):

    default_fields = set([
        "cluster",
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

        self.service.confs["defaults"]["general"].submit(defaults)

    def handle_GET(self):

        defaults = self.service.confs["defaults"]["general"]
        defaults_data = {
            self.defaults_prefix+k: defaults[k] if k in defaults else ""
            for k in self.default_fields}

        data = {}
        data.update(defaults_data)
        self.send_json_response(data)
