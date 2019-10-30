import logging

from splunk.appserver.mrsparkle.lib.util import make_splunkhome_path


def setup(name, level=logging.DEBUG):
    """
    Setup a logger for the REST handler.
    """
    name = "saas_"+name

    logger = logging.getLogger(name)
    # Prevent the log messages from being duplicated in the python.log file
    logger.propagate = False
    logger.setLevel(level)

    file_handler = logging.handlers.RotatingFileHandler(make_splunkhome_path(
        ['var', 'log', 'splunk', name+'.log']), maxBytes=25000000, backupCount=5)

    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
