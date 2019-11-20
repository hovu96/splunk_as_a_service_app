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
from datetime import datetime, timezone, timedelta
import splunklib
import stacks
import time
import clusters
from kubernetes import client as kubernetes
import services

TEST_PREPARING = "Preparing"
TEST_RUNNING = "Running"
TEST_STOPPING = "Stopping"
TEST_FINISHED = "Finished"

CASE_WAITING = "Waiting"
CASE_STARTING = "Starting"
CASE_RUNNING = "Running"
CASE_STOPPING = "Stopping"
CASE_FINISHED = "Finished"


def get_performance_tests_collection(splunk):
    return splunk.kvstore["performance_tests"].data


def get_performance_test_cases_collection(splunk):
    return splunk.kvstore["performance_test_cases"].data


def get_test_info(test):
    info = {
        "id": test["_key"],
        "status": test["status"],
        "testsuite": test["testsuite"],
        "cluster": test["cluster"],
        "time_created": test["time_created"],
        "run_duration": test["run_duration"] if "run_duration" in test else None,
    }
    if "time_finished" in test:
        info["time_finished"] = test["time_finished"]
    return info


class TestsHandler(BaseRestHandler):
    def handle_GET(self):
        request_query = self.request["query"]
        if "filter" in request_query:
            query_filter = request_query["filter"]
        else:
            query_filter = "non_finished"
        if query_filter == "non_finished":
            query = {
                "status": {"$ne": TEST_FINISHED}
            }
        elif query_filter == "recently_finished":
            query = {
                "$and": [
                    {"status": TEST_FINISHED},
                    {"time_finished": {
                        "$gt": (datetime.utcnow() - timedelta(hours=24)).timestamp()}},
                ],
            }
        else:
            raise Exception("unsupported filter")
        tests = get_performance_tests_collection(self.splunk)
        tests_query = tests.query(
            query=json.dumps(query),
            sort="time_created:-1",
        )
        self.send_entries([get_test_info(test) for test in tests_query])

    def handle_POST(self):
        tests = get_performance_tests_collection(self.splunk)
        test_record = {
            "status": TEST_PREPARING,
            "time_created": time.time(),
        }
        fields_names = set([
            "testsuite",
            "cluster",
            "run_duration",
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


class TestHandler(BaseRestHandler):
    def handle_DELETE(self):
        path = self.request['path']
        _, test_id = os.path.split(path)
        tests = get_performance_tests_collection(self.splunk)
        test = tests.query_by_id(test_id)
        if test["status"] == TEST_FINISHED:
            return
        unschedule_search(self.splunk, test_id, raise_error=False)
        test.update({
            "status": TEST_STOPPING,
        })
        tests.update(test_id, json.dumps(test))
        schedule_search(self.splunk, test_id)

    def handle_GET(self):
        path = self.request['path']
        _, test_id = os.path.split(path)
        tests = get_performance_tests_collection(self.splunk)
        test = tests.query_by_id(test_id)
        self.send_result(get_test_info(test))


class PerformanceTestCasesHandler(BaseRestHandler):
    def handle_GET(self):
        path = self.request['path']
        _, test_id = os.path.split(path)
        cases_collection = get_performance_test_cases_collection(self.splunk)
        cases = cases_collection.query(
            query=json.dumps({
                "test_id": test_id
            }),
            sort="index:1",
        )

        def map(case):
            result = {
                "id": case["_key"],
                "index": case["index"],
                "status": case["status"],
                "deployment_type": case["deployment_type"],
                "indexer_count": case["indexer_count"],
                "search_head_count": case["search_head_count"],
                "cpu_per_instance": case["cpu_per_instance"],
                "etc_storage_in_gb": case["etc_storage_in_gb"],
                "other_var_storage_in_gb": case["other_var_storage_in_gb"],
                "indexer_var_storage_in_gb": case["indexer_var_storage_in_gb"],
                "memory_per_instance": case["memory_per_instance"],
                "data_volume_in_gb_per_day": case["data_volume_in_gb_per_day"],
                "searches_per_minute": case["searches_per_minute"],
                "user_count": case["user_count"],
            }
            if "stack_id" in case:
                result["stack_id"] = case["stack_id"]
            return result
        self.send_entries([map(case) for case in cases])


def get_search_name(test_id):
    return "performance_test_%s" % (test_id)


def schedule_search(splunk, test_id):
    unschedule_search(splunk, test_id, raise_error=False)
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


def unschedule_search(splunk, test_id, raise_error=True):
    search_name = get_search_name(test_id)
    try:
        splunk.saved_searches.delete(search_name)
    except KeyError:
        if raise_error:
            raise


@Configuration(type='reporting')
class PerformanceTest(GeneratingCommand):
    test_id = Option(require=True)

    def generate(self):
        log_file_path = os.path.join(os.path.dirname(
            os.path.dirname(__file__)), "..", "..", "..", "var", "log", "splunk", "saas_performance_test_" + self.test_id + ".log")
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path, maxBytes=25000000, backupCount=5)
        tz = time.strftime("%Z")
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d ' + tz + ' test_id=\"' + self.test_id +
            '\" level=\"%(levelname)s\" %(message)s')
        formatter.datefmt = "%m/%d/%Y %H:%M:%S"
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
                logging.info("%s" % msg)
            logging.debug("will check in 1m")
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
        prepare_cases(splunk, test_id, test)
        test.update({
            "status": TEST_RUNNING,
        })
        tests.update(test_id, json.dumps(test))
        logging.debug("new test status: %s" % test["status"])

    if test["status"] == TEST_RUNNING:
        run_cases(splunk, test_id, test)
        test.update({
            "status": TEST_STOPPING,
        })
        tests.update(test_id, json.dumps(test))
        logging.debug("new test status: %s" % test["status"])

    if test["status"] == TEST_STOPPING:
        stop_cases(splunk, test_id, test)
        test.update({
            "status": TEST_FINISHED,
            "time_finished": time.time(),
        })
        tests.update(test_id, json.dumps(test))
        logging.debug("new test status: %s" % test["status"])

    if test["status"] != TEST_FINISHED:
        logging.error("unexpected state: %s" % test["status"])


def prepare_cases(splunk, test_id, test):
    testsuite_results = splunk.jobs.oneshot(
        "| inputlookup %s" % test["testsuite"])
    testsuite_reader = results.ResultsReader(testsuite_results)
    cases_collection = get_performance_test_cases_collection(splunk)
    cnt = 0
    for case_data in testsuite_reader:
        logging.debug("creating test case %s" % json.dumps(case_data))
        case = {
            "status": CASE_WAITING,
            "test_id": test_id,
            "index": cnt,
            "deployment_type": case_data["deployment_type"],
            "indexer_count": case_data["indexer_count"],
            "search_head_count": case_data["search_head_count"],
            "cpu_per_instance": case_data["cpu_per_instance"],
            "etc_storage_in_gb": case_data["etc_storage_in_gb"],
            "other_var_storage_in_gb": case_data["other_var_storage_in_gb"],
            "indexer_var_storage_in_gb": case_data["indexer_var_storage_in_gb"],
            "memory_per_instance": case_data["memory_per_instance"],
            "data_volume_in_gb_per_day": case_data["data_volume_in_gb_per_day"],
            "searches_per_minute": case_data["searches_per_minute"],
            "user_count": case_data["user_count"],
        }
        cases_collection.insert(json.dumps(case))["_key"]
        cnt += 1
    logging.info("created %s test cases" % cnt)


def run_cases(splunk, test_id, test):
    cases_collection = get_performance_test_cases_collection(splunk)
    cases = cases_collection.query(
        query=json.dumps({
            "test_id": test_id,
        }),
        sort="index:1",
    )
    for case in cases:
        case_id = case["_key"]
        status = case["status"]
        if status == CASE_FINISHED:
            continue
        if status == CASE_WAITING:
            result = splunk.post("saas/stacks", **{
                "deployment_type": case["deployment_type"],
                "indexer_count": case["indexer_count"],
                "search_head_count": case["search_head_count"],
                "cpu_per_instance": case["cpu_per_instance"],
                "etc_storage_in_gb": case["etc_storage_in_gb"],
                "other_var_storage_in_gb": case["other_var_storage_in_gb"],
                "indexer_var_storage_in_gb": case["indexer_var_storage_in_gb"],
                "memory_per_instance": case["memory_per_instance"],
                "title": "Performance Test %s and Case %s" % (test_id, case_id),
                "cluster": test["cluster"],
            })
            response = json.loads(result.body.read())["entry"][0]["content"]
            stack_id = response["stack_id"]
            logging.info("created stack %s for test case %s" %
                         (stack_id, case_id))
            case.update({
                "status": CASE_STARTING,
                "stack_id": stack_id,
            })
            cases_collection.update(case_id, json.dumps(case))
            raise errors.RetryOperation(
                "waiting for stack %s in test case %s starting up ..." % (stack_id, case_id))
        elif status == CASE_STARTING:
            stack_id = case["stack_id"]
            stack = splunk.get("saas/stack/%s" % stack_id)
            stack_status = json.loads(stack.body.read())[
                "entry"][0]["content"]["status"]
            if stack_status == stacks.CREATING:
                raise errors.RetryOperation()
            if stack_status != stacks.CREATED:
                raise Exception("unexpected stack status: %s" % stack_status)
            logging.info("successfully created stack %s for case %s" %
                         (stack_id, case_id))
            stack_config = stacks.get_stack_config(splunk, stack_id)
            kube_client = clusters.create_client(
                splunk, stack_config["cluster"])
            core_api = kubernetes.CoreV1Api(kube_client)
            if stack_config["deployment_type"] == "standalone":
                hosts = services.get_load_balancer_hosts(
                    core_api, stack_id, services.standalone_role, stack_config["namespace"])
            elif stack_config["deployment_type"] == "distributed":
                hosts = services.get_load_balancer_hosts(
                    core_api, stack_id, services.indexer_role, stack_config["namespace"])
            else:
                raise Exception("unexpected deployment type: %s" %
                                stack_config["deployment_type"])
            logging.info(
                "successfully created data gen for case %s" % (case_id))
            data_volume_in_gb_per_day = int(case["data_volume_in_gb_per_day"])
            logging.debug("data_volume_in_gb_per_day=%s" %
                          (data_volume_in_gb_per_day))
            data_volume_in_gb_per_second = data_volume_in_gb_per_day / 24 / 60 / 60
            logging.debug("data_volume_in_gb_per_second=%s" %
                          (data_volume_in_gb_per_second))
            data_volume_in_kb_per_second = data_volume_in_gb_per_second * 1024 * 1024
            logging.debug("data_volume_in_kb_per_second=%s" %
                          (data_volume_in_kb_per_second))
            max_kb_per_second_per_data_generator = 100
            logging.debug("max_kb_per_second_per_data_generator=%s" %
                          (max_kb_per_second_per_data_generator))
            number_of_data_generators = max(
                int(data_volume_in_kb_per_second / max_kb_per_second_per_data_generator) + 1, 1)
            logging.debug("number_of_data_generators=%s" %
                          (number_of_data_generators))
            data_volume_in_kb_per_second_per_data_generator = data_volume_in_kb_per_second / \
                number_of_data_generators
            logging.debug("data_volume_in_kb_per_second_per_data_generator=%s" %
                          (data_volume_in_kb_per_second_per_data_generator))
            cluster_config = clusters.get_cluster_config(
                splunk, test["cluster"])
            node_selector_labels = cluster_config["node_selector"].split(",")
            node_selector_for_data_generators = {}
            for label in node_selector_labels:
                if label:
                    kv = label.split("=")
                    if len(kv) != 2:
                        raise errors.ApplicationError(
                            "invalid node selector format (%s)" % cluster_config.node_selector)
                    node_selector_for_data_generators[kv[0]] = kv[1]
            apps_api = kubernetes.AppsV1Api(kube_client)
            apps_api.create_namespaced_deployment(
                namespace=stack_config["namespace"],
                body=kubernetes.V1Deployment(
                    metadata=kubernetes.V1ObjectMeta(
                        name="datagen-%s" % (stack_id),
                        namespace=stack_config["namespace"],
                        labels={
                            "for": stack_id,
                            "app": "datagen",
                            "test": test_id,
                            "case": case_id,
                        },
                    ),
                    spec=kubernetes.V1DeploymentSpec(
                        replicas=number_of_data_generators,
                        selector=kubernetes.V1LabelSelector(
                            match_labels={
                                "name": "datagen-%s" % (stack_id),
                            }
                        ),
                        template=kubernetes.V1PodTemplateSpec(
                            metadata=kubernetes.V1ObjectMeta(
                                labels={
                                    "name": "datagen-%s" % (stack_id),
                                    "app": "datagen",
                                    "test": test_id,
                                    "case": case_id,
                                    "stack": stack_id,
                                },
                            ),
                            spec=kubernetes.V1PodSpec(
                                containers=[
                                    kubernetes.V1Container(
                                        name="datagen",
                                        image="blackhypothesis/splunkeventgenerator:latest",
                                        resources=kubernetes.V1ResourceRequirements(
                                            requests={
                                                "memory": "10Mi",
                                                "cpu": "500m",
                                            },
                                            limits={
                                                "memory": "50Mi",
                                                "cpu": "1",
                                            },
                                        ),
                                        env=[
                                            kubernetes.V1EnvVar(
                                                name="DSTHOST",
                                                value=";".join(
                                                    map(lambda host: host + ":9996", hosts)),
                                            ),
                                            kubernetes.V1EnvVar(
                                                name="KB_S",
                                                value="%s" % data_volume_in_kb_per_second_per_data_generator,
                                            ),
                                        ],
                                    ),
                                ],
                                node_selector=node_selector_for_data_generators,
                            ),
                        ),
                    ),
                ),
            )
            logging.info(
                "created %s data generators for case %s" % (number_of_data_generators, case_id))
            case.update({
                "status": CASE_RUNNING,
                "time_started_running": time.time(),
            })
            cases_collection.update(case_id, json.dumps(case))
            raise errors.RetryOperation(
                "running test case %s ..." % case_id)
        elif status == CASE_RUNNING:
            time_started_running = case["time_started_running"]
            time_now = time.time()
            seconds_running_to_far = time_now - time_started_running
            target_run_duration = test["run_duration"]
            logging.debug("time_started_running=%s time_now=%s seconds_running_to_far=%s" % (
                time_started_running, time_now, seconds_running_to_far))
            if seconds_running_to_far < (target_run_duration * 60):
                logging.debug("still waiting")
                raise errors.RetryOperation()
            logging.info("time elapsed for case %s" % (case_id))
            case.update({
                "status": CASE_STOPPING,
                "time_finished_running": time.time(),
            })
            cases_collection.update(case_id, json.dumps(case))
            raise errors.RetryOperation(
                "stopping test case %s" % case_id)
        elif status == CASE_STOPPING:
            stop_case(splunk, test_id, case_id, case)
            case.update({
                "status": CASE_FINISHED,
            })
            cases_collection.update(case_id, json.dumps(case))
            logging.info("finished test case %s" % case_id)
        else:
            logging.error(
                "run_cases: unexpected status for test case %s: %s" % (case_id, status))
            raise errors.RetryOperation()


def stop_cases(splunk, test_id, test):
    cases_collection = get_performance_test_cases_collection(splunk)
    cases = cases_collection.query(
        query=json.dumps({
            "test_id": test_id,
        }),
        sort="index:1",
    )
    for case in cases:
        case_id = case["_key"]
        status = case["status"]
        if "stopped" in case and case["stopped"] == True:
            continue
        if status == CASE_WAITING:
            pass
        elif status == CASE_STARTING:
            stop_case(splunk, test_id, case_id, case)
            logging.info("stopped test case %s" % case_id)
        elif status == CASE_RUNNING:
            stop_case(splunk, test_id, case_id, case)
            logging.info("stopped test case %s" % case_id)
        elif status == CASE_STOPPING:
            stop_case(splunk, test_id, case_id, case)
            logging.info("stopped test case %s" % case_id)
        elif status == CASE_FINISHED:
            pass
        else:
            logging.error(
                "stop_cases: unexpected status for test case %s: %s" % (case_id, status))
            raise errors.RetryOperation()
        case.update({"stopped": True})
        cases_collection.update(case_id, json.dumps(case))


def stop_case(splunk, test_id, case_id, case):
    if "stack_id" not in case:
        return
    stack_id = case["stack_id"]
    result = splunk.get("saas/stack/%s" % stack_id)
    logging.debug("get stack result: %s" % result)
    response = json.loads(result.body.read())["entry"][0]["content"]
    logging.debug("get stack response: %s" % response)
    stack_status = response["status"]
    if stack_status == stacks.DELETING:
        raise errors.RetryOperation("still in status %s" % stacks.DELETING)
    elif stack_status == stacks.DELETED:
        pass
    elif stack_status != stacks.DELETED:
        result = splunk.delete("saas/stack/%s" % stack_id)
        response = json.loads(result.body.read())["entry"][0]["content"]
        logging.debug("delete stack result: %s" % response)
        raise errors.RetryOperation("issued deletion of stack %s" % (stack_id))
    stack_config = stacks.get_stack_config(splunk, stack_id)
    kube_client = clusters.create_client(
        splunk, stack_config["cluster"])
    apps_api = kubernetes.AppsV1Api(kube_client)
    datagen_deployments = apps_api.list_namespaced_deployment(
        namespace=stack_config["namespace"],
        label_selector="app=datagen,test=%s" % test_id,
    ).items
    for deployment in datagen_deployments:
        apps_api.delete_namespaced_deployment(
            name=deployment.metadata.name,
            namespace=stack_config["namespace"],
        )
        logging.debug("deleted deployment %s" % deployment.metadata.name)


dispatch(PerformanceTest, sys.argv, sys.stdin, sys.stdout, __name__)
