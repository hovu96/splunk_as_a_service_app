import fix_path
import sys
import logging
import os
import splunklib.binding
from operator_up_command import UpCommand
from operator_down_command import DownCommand
app_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))


def main(service, stack_id, command):

    logging.debug("will run '%s' command" % command)

    # HTTPError: HTTP 503 Service Unavailable - - KV Store is initializing.
    # Please try again later.
    try:
        _ = service.kvstore["stacks"].data
    except splunklib.binding.HTTPError as e:
        if e.status == 503:
            logging.warning("%s" % e)
            return
        raise

    if command == "up":
        operator = UpCommand(service, stack_id, command)
    elif command == "down" or command == "kill":
        operator = DownCommand(service, stack_id, command)
    else:
        raise Exception("unknown command: %s" % command)

    operator.run()


def create_service(sessionKey):
    entity = __import__("splunk.entity", fromlist=[None])
    entity = entity.getEntity(
        '/server', 'settings', namespace=app_name, sessionKey=sessionKey, owner='-')
    import splunklib.client
    service = splunklib.client.Service(
        token=sessionKey,
        port=entity['mgmtHostPort'],
        scheme="https",
        host="127.0.0.1",
        owner="nobody",
        app=app_name,
    )
    service.login()
    return service


if __name__ == "__main__":
    sessionKey = sys.stdin.readline()
    stack_id = sys.argv[1]
    command = sys.argv[2]

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s level=\"%(levelname)s\" %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    service = create_service(sessionKey)

    try:
        main(service, stack_id, command)
    except:
        import traceback
        logging.error(traceback.format_exc())
