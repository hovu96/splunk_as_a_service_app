import os
import sys

#bin_path = os.path.join(os.path.dirname(__file__), "..", "..", "bin")
# if bin_path not in sys.path:
#    sys.path.insert(0, bin_path)

import os
import sys
import cgi
import cherrypy
import splunk
import splunk.appserver.mrsparkle.controllers as controllers
import splunk.appserver.mrsparkle.lib.util as util
import splunk.util
import splunk.clilib.cli_common
import shutil
from splunk.appserver.mrsparkle.lib.decorators import expose_page
from splunk.appserver.mrsparkle.lib.routes import route
from splunk.appserver.mrsparkle.lib import jsonresponse
import tempfile
import shutil
import traceback
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path


class UploadAppController(controllers.BaseController):

    # @route('/')
    @expose_page(must_login=True, methods=['POST'])
    def post(self, **kwargs):
        app_name = "%s" % cherrypy.request.path_info.split("/")[-3]

        try:
            lib_path = sys.path.append(make_splunkhome_path(
                ["etc", "apps", "splunk_as_a_service", "lib"]))
            if lib_path not in sys.path:
                sys.path.insert(0, lib_path)

            bin_path = sys.path.append(make_splunkhome_path(
                ["etc", "apps", "splunk_as_a_service", "bin"]))
            if bin_path not in sys.path:
                sys.path.insert(0, bin_path)

            import capabilities
            import apps
            import app_bundles

            import importlib
            importlib.reload(capabilities)
            importlib.reload(apps)
            importlib.reload(app_bundles)

            if not capabilities.has("saas_manage_apps") and not capabilities.has("admin_all_objects"):
                cherrypy.response.status = 403
                return "missing capability"

            app_field = kwargs.get('app')
            # if not isinstance(app_field, cgi.FieldStorage):
            #    cherrypy.response.status = 400
            #    return "Missing app field: %s" % dir(app_field)

            import splunklib.client as client
            splunk = client.Service(
                token=cherrypy.session.get('sessionKey'),
                sharing="app",
                app=app_name,
            )

            app_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    shutil.copyfileobj(app_field.file, temp_file)
                    app_path = temp_file.name

                if app_bundles.is_bundle(app_path):
                    bundle_name = app_bundles.add_bundle(splunk, app_path, app_field.filename)
                    return self.render_json(dict(
                        kind="bundle",
                        name=bundle_name,
                    ))
                else:
                    app_name, app_version = apps.add_app(splunk, app_path)
                    return self.render_json(dict(
                        kind="app",
                        name=app_name,
                        version=app_version
                    ))
            finally:
                if app_path:
                    os.remove(app_path)

        except:
            cherrypy.response.status = 500
            return traceback.format_exc()
