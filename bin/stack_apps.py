import os
import sys
bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import fix_path
from base_handler import BaseRestHandler
from urllib.parse import parse_qs


def get_stack_apps(splunk):
    return splunk.kvstore["stack_apps"].data


def get_stack_app_overwrites(splunk):
    return splunk.kvstore["stack_app_overwrites"].data


class AppsInStack(BaseRestHandler):
    def handle_POST(self):
        pass

    def handle_GET(self):
        pass


class AppInStack(BaseRestHandler):
    def handle_GET(self):
        self.send_result({
            "test": "hallo",
        })

    def handle_DELETE(self):
        pass


class StacksHavingApp(BaseRestHandler):
    def handle_GET(self):
        self.send_result({
            "test": "hallo",
        })
