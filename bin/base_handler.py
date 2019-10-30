import fix_path
import splunk.rest
import json
from logger import getLogger
import splunklib.client as client
import os
from urlparse import parse_qs

logger = getLogger()

app_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))


class BaseRestHandler(splunk.rest.BaseRestHandler):
    _splunk = None
    _payload = None

    @property
    def payload(self):
        if self._payload != None:
            return self._payload
        _payload = parse_qs(self.request['payload'])
        return _payload

    @property
    def splunk(self):
        if self._splunk != None:
            return self._splunk
        self._splunk = client.Service(
            token=self.request["systemAuth"],  # self.sessionKey,
            sharing="app",
            app=app_name,
        )
        return self._splunk

    @property
    def service(self):
        return self.splunk

    def send_entries(self, entries):
        self.send_json_response({
            "entry": [{
                "content": e
            } for e in entries]
        })

    def send_result(self, entry):
        self.send_entries([entry])

    def send_json_response(self, object):
        self.response.setStatus(200)
        self.response.setHeader('content-type', 'application/json')
        self.response.write(json.dumps(object))

    @property
    def logger(self):
        return logger

    @property
    def app(self):
        return __file__.split(os.sep)[-3]

    @property
    def stacks(self):
        return self.service.kvstore["stacks"].data
