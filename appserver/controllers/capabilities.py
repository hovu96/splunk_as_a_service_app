import cherrypy
import splunk
import splunk.rest as rest
import logger
import json
import splunk.entity as entity

logger = logger.setup("caps")


def has(capabilities, user=None, session_key=None):
    """
    Determine if the user has the given capabilities.
    """

    # Assign defaults if the user or session key is None
    if user is None:
        user = cherrypy.session['user']['name']

    if session_key is None:
        session_key = cherrypy.session.get('sessionKey')

    # Convert the capability to a list if it was a scalar
    if not isinstance(capabilities, list) or isinstance(capabilities, basestring):
        capabilities = [capabilities]

    # Get the capabilities that the user has
    try:
        users_capabilities = get4User(user, session_key)
    except splunk.LicenseRestriction:
        # This can happen when the Splunk install is using the free license

        # Check to see if the Splunk install is using the free license and allow access if so
        # We are only going to check for this if it is the admin user since that is the user
        # that the non-authenticated user is logged in as when the free license is used.
        if user == 'admin':

            # See the free license is active
            response, content = rest.simpleRequest('/services/licenser/groups/Free?output_mode=json',
                                                   sessionKey=session_key)

            # If the response didn't return a 200 code, then the entry likely didn't exist and
            # the host is not using the free license
            if response.status == 200:

                # Parse the JSON content
                logger.warn(content)
                license_info = json.loads(content)

                if license_info['entry'][0]['content']['is_active'] == 1:
                    # This host is using the free license, allow this through
                    return True

    # Check the capabilities
    for capability in capabilities:
        if capability not in users_capabilities:
            return False

    return True


def get4User(user=None, session_key=None):
    """
    Get the capabilities for the given user.
    """

    roles = []
    capabilities = []

    # Get user info
    if user is not None:
        logger.info('Retrieving role(s) for current user: %s', user)
        userDict = entity.getEntities(
            'authentication/users/%s' % (user), count=-1, sessionKey=session_key)

        for stanza, settings in userDict.items():
            if stanza == user:
                for key, val in settings.items():
                    if key == 'roles':
                        logger.info(
                            'Successfully retrieved role(s) for user: %s', user)
                        roles = val

    # Get capabilities
    for role in roles:
        logger.info('Retrieving capabilities for current user: %s', user)
        roleDict = entity.getEntities(
            'authorization/roles/%s' % (role), count=-1, sessionKey=session_key)

        for stanza, settings in roleDict.items():
            if stanza == role:
                for key, val in settings.items():
                    if key == 'capabilities' or key == 'imported_capabilities':
                        logger.info(
                            'Successfully retrieved %s for user: %s', key, user)
                        capabilities.extend(val)

    return capabilities
