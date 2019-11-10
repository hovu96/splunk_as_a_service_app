import os
import sys

bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
import traceback
import sys
import json
from splunklib.searchcommands import \
    dispatch, GeneratingCommand, Configuration, Option, validators


@Configuration(type='reporting')
class EndpointCommand(GeneratingCommand):
    path = Option(require=True)

    def generate(self):
        result = self.service.post("saas/%s" % self.path)
        response = json.loads(result.body.read())
        for e in response["entry"]:
            yield e["content"]


dispatch(EndpointCommand, sys.argv, sys.stdin, sys.stdout, __name__)
