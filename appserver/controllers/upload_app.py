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
import capabilities
from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path


class UploadAppController(controllers.BaseController):

    @route('/')
    @expose_page(must_login=True, methods=['POST'])
    def post(self, **kwargs):
        app_name = "%s" % cherrypy.request.path_info.split("/")[-2]

        lib_path = sys.path.append(make_splunkhome_path(
            ["etc", "apps", "splunk_as_a_service", "lib"]))
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        bin_path = sys.path.append(make_splunkhome_path(
            ["etc", "apps", "splunk_as_a_service", "bin"]))
        if bin_path not in sys.path:
            sys.path.insert(0, bin_path)

        try:
            if not capabilities.has("saas_manage_apps") and not capabilities.has("admin_all_objects"):
                cherrypy.response.status = 403
                return "missing capability"

            app_field = kwargs.get('app')
            if not isinstance(app_field, cgi.FieldStorage):
                cherrypy.response.status = 400
                return "Missing app field"

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

                import apps
                # todo: make python 3 compliant
                reload(apps)
                return apps.add_app(splunk, app_path)
            finally:
                if app_path:
                    os.remove(app_path)

        except:
            cherrypy.response.status = 500
            return traceback.format_exc()