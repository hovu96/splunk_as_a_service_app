import os
import sys
bin_path = os.path.join(os.path.dirname(__file__))
if bin_path not in sys.path:
    sys.path.insert(0, bin_path)

import json
import fix_path
from base_handler import BaseRestHandler
from urllib.parse import parse_qs
from splunklib.searchcommands import \
    dispatch, GeneratingCommand, Configuration, Option, validators
import splunklib.results as results
import logging
import errors
import datetime

TEST_PREPARING = "Preparing"
TEST_RUNNING = "Running"
TEST_STOPPING = "Stopping"
TEST_FINISHED = "Finished"

ITEM_WAITING = "Waiting"
ITEM_CREATING = "Creating"
ITEM_RUNNING = "Running"
ITEM_DELETING = "Deleting"
ITEM_FINISHED = "Finished"


def get_performance_tests_collection(splunk):
    return splunk.kvstore["performance_tests"].data


def get_performance_test_items_collection(splunk):
    return splunk.kvstore["performance_test_items"].data


class PerformanceTestsHandler(BaseRestHandler):
    def handle_GET(self):
        tests = get_performance_tests_collection(self.splunk)
        query = tests.query(query=json.dumps({
            "status": {"$ne": TEST_FINISHED}
        }))

        def map(d):
            return {
                "id": d["_key"],
                "status": d["status"],
                "testsuite": d["testsuite"] if "testsuite" in d else "????",
                "cluster": d["cluster"] if "cluster" in d else "????",
                "created": d["created"] if "created" in d else "????",
            }
        self.send_entries([map(d) for d in query])

    def handle_POST(self):
        tests = get_performance_tests_collection(self.splunk)
        test_record = {
            "status": TEST_PREPARING,
            "created": datetime.datetime.utcnow().timestamp(),
        }
        fields_names = set([
            "testsuite",
            "cluster",
        ])
        request_params = parse_qs(self.request['payload'])
        test_record.update({
            k: request_params[k][0]
            for k in fields_names
        })
        test_id = tests.insert(json.dumps(test_record))["_key"]
        schedule_search(self.service, test_id)
        self.send_result({
            "test_id": test_id,
        })


class PerformanceTestHandler(BaseRestHandler):
    def handle_DELETE(self):
        path = self.request['path']
        _, test_id = os.path.split(path)
        tests = get_performance_tests_collection(self.splunk)
        test = tests.query_by_id(test_id)
        if test["status"] == TEST_FINISHED:
            return
        test.update({
            "status": TEST_STOPPING,
        })
        tests.update(test_id, json.dumps(test))
        schedule_search(self.service, test_id)


class PerformanceTestItemsHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, test_id = os.path.split(path)
        items_collection = get_performance_test_items_collection(self.splunk)
        items = items_collection.query(query=json.dumps({
            "test_id": test_id
        }))

        def map(item):
            return {
                "id": item["_key"],
                "status": item["status"],
                "data": item["data"],
            }
        self.send_entries([map(item) for item in items])


def get_search_name(test_id):
    return "performance_test_%s" % (test_id)


def schedule_search(splunk, test_id):
    try:
        unschedule_search(splunk, test_id)
    except KeyError:
        pass
    search = splunk.saved_searches.create(
        name=get_search_name(test_id),
        search="| performancetest test_id=\"%s\"" % (test_id),
        **{
            "cron_schedule": "* * * * *",
            "is_scheduled": 1,
            "schedule_window": "auto",
            "dispatch.auto_cancel": 0,
            "dispatch.auto_pause": 0,
            "dispatch.max_time": 0,
        }
    )
    search.dispatch(
        **{
            "dispatch.now": True,
            "force_dispatch": False,
        }
    )


def unschedule_search(splunk, test_id):
    search_name = get_search_name(test_id)
    splunk.saved_searches.delete(search_name)


@Configuration(type='reporting')
class PerformanceTest(GeneratingCommand):
    test_id = Option(require=True)

    def generate(self):
        log_file_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "..", "..", "..", "var", "log", "splunk", "saas_performance_test_" + self.test_id + ".log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=25000000, backupCount=5)
        formatter = logging.Formatter(
            '%(asctime)s test_id=\"' + self.test_id +
            '\" level=\"%(levelname)s\" %(message)s')
        formatter.datefmt = "%m/%d/%Y %H:%M:%S %Z"
        file_handler.setFormatter(formatter)
        root_logger = logging.getLogger()
        root_logger.setLevel("DEBUG")
        root_logger.addHandler(file_handler)

        logging.debug("running ...")

        if False:
            yield

        try:
            perform_test(self.service, self.test_id)
            logging.info("done")
        except errors.RetryOperation as e:
            msg = "%s" % e
            if msg:
                logging.info("%s\n\n(will check in 1m)" % msg)
            else:
                logging.info("will check in 1m")
            return
        except:
            import traceback
            logging.error("%s\n\n(will try again in 1m)" %
                          traceback.format_exc())
            return
        finally:
            logging.shutdown()

        unschedule_search(self.service, self.test_id)


def perform_test(splunk, test_id):
    tests = get_performance_tests_collection(splunk)
    test = tests.query_by_id(test_id)

    if test["status"] == TEST_PREPARING:
        prepare_test_items(splunk, test_id, test)
        test.update({
            "status": TEST_RUNNING,
        })
        tests.update(test_id, json.dumps(test))
        logging.info("new test status: %s" % test["status"])

    if test["status"] == TEST_RUNNING:
        run_test_items(splunk, test_id, test)
        test.update({
            "status": TEST_STOPPING,
        })
        tests.update(test_id, json.dumps(test))
        logging.info("new test status: %s" % test["status"])

    if test["status"] == TEST_STOPPING:
        stop_test_items(splunk, test_id, test)
        test.update({
            "status": TEST_FINISHED,
            "finished": datetime.datetime.utcnow().timestamp(),
        })
        tests.update(test_id, json.dumps(test))
        logging.info("new test status: %s" % test["status"])

    if test["status"] != TEST_FINISHED:
        logging.error("unexpected state: %s" % test["status"])


def prepare_test_items(splunk, test_id, test):
    testsuite_results = splunk.jobs.oneshot(
        "| inputlookup %s" % test["testsuite"])
    testsuite_reader = results.ResultsReader(testsuite_results)
    items_collection = get_performance_test_items_collection(splunk)
    cnt = 0
    for testsuite_item in testsuite_reader:
        logging.debug("creating item %s" % json.dumps(testsuite_item))
        item_record = {
            "status": ITEM_WAITING,
            "test_id": test_id,
            "data": json.dumps(testsuite_item)
        }
        items_collection.insert(json.dumps(item_record))["_key"]
        cnt += 1
    logging.info("created %s items" % cnt)


def run_test_items(splunk, test_id, test):
    items_collection = get_performance_test_items_collection(splunk)
    items = items_collection.query(query=json.dumps({
        "test_id": test_id,
    }))
    for item in items:
        item_id = item["_key"]
        status = item["status"]
        if status == ITEM_FINISHED:
            continue
        if status == ITEM_WAITING:
            item.update({
                "status": ITEM_CREATING,
            })
            items_collection.update(item_id, json.dumps(item))
            raise errors.RetryOperation(
                "creating test item %s" % item_id)
        elif status == ITEM_CREATING:
            logging.warning("run_test_items: %s not implemented" %
                            (ITEM_CREATING))
            item.update({
                "status": ITEM_RUNNING,
            })
            items_collection.update(item_id, json.dumps(item))
            raise errors.RetryOperation(
                "running test item %s" % item_id)
        elif status == ITEM_RUNNING:
            logging.warning("run_test_items: %s not implemented" %
                            (ITEM_RUNNING))
            item.update({
                "status": ITEM_DELETING,
            })
            items_collection.update(item_id, json.dumps(item))
            raise errors.RetryOperation(
                "deleting test item %s" % item_id)
        elif status == ITEM_DELETING:
            stop_test_item(splunk, test_id, item_id)
            item.update({
                "status": ITEM_FINISHED,
            })
            items_collection.update(item_id, json.dumps(item))
            logging.info("finished test item %s" % item_id)
        else:
            logging.error(
                "run_test_items: unexpected status for item %s: %s" % (item_id, status))
            raise errors.RetryOperation()


def stop_test_items(splunk, test_id, test):
    items_collection = get_performance_test_items_collection(splunk)
    items = items_collection.query(query=json.dumps({
        "test_id": test_id,
    }))
    for item in items:
        item_id = item["_key"]
        status = item["status"]
        if "stopped" in item and item["stopped"] == True:
            continue
        if status == ITEM_WAITING:
            pass
        elif status == ITEM_CREATING:
            stop_test_item(splunk, test_id, item_id)
        elif status == ITEM_RUNNING:
            stop_test_item(splunk, test_id, item_id)
        elif status == ITEM_FINISHED:
            pass
        else:
            logging.error(
                "stop_test_items: unexpected status for item %s: %s" % (item_id, status))
            raise errors.RetryOperation()
        item.update({"stopped": True})
        items_collection.update(item_id, json.dumps(item))
        logging.info("stopped item %s" % item)


def stop_test_item(splunk, test_id, item_id):
    pass


dispatch(PerformanceTest, sys.argv, sys.stdin, sys.stdout, __name__)
