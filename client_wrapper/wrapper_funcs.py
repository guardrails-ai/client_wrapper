#!/usr/bin/env python

# Client-side socket python wrapper + code-level annotation
# Sample:
# #my_py.py
# from client_wrapper import tt_webhook_polling_sync
# @tt_webhook_polling_sync
# def some_func(prompt):
# 		# YOUR EXISTING LLM LOGIC
#
# 		# SOME STRING RESULT
# 		return res

import os
from dataclasses import asdict
from typing import Callable, Dict, Optional
from logging import getLogger

import time
import requests
from websockets.sync.client import connect as sync_connect
from concurrent.futures import ThreadPoolExecutor

from queue import Queue
import threading
from .protocols import Report

DEFAULT_CONTROL_PLANE_URL = "http://localhost:8080"

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", DEFAULT_CONTROL_PLANE_URL)

LOGGER = getLogger(__name__)

last_successful_test = None


def _get_app_id(application_id: Optional[str] = None) -> str:
    if application_id:
        return application_id
    application_id = os.environ.get("GUARDRAILS_APP_ID")
    if not application_id:
        raise ValueError("GUARDRAILS_APP_ID is not set!")

def _get_api_key() -> str:
    api_key = os.environ.get("GUARDRAILS_TOKEN")
    if not api_key:
        raise ValueError("GUARDRAILS_TOKEN is not set!")
    return api_key


class TestProcessor:
    def __init__(
        self,
        control_plane_host: str,
        max_workers: Optional[int] = None,
        application_id: Optional[str] = None,
        throttle_time: Optional[float] = None
    ):
        self.control_plane_host = control_plane_host
        self.processing_queue = Queue()
        self.queued_tests: Dict[str, bool] = {}
        self.should_stop = False
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.processing_thread = None
        self.application_id = application_id
        self.throttle_time = throttle_time

    def start_processing(self, fn: Callable[[str, ...], str]):
        """Start the background processing thread"""
        self.should_stop = False
        self.processing_thread = threading.Thread(
            target=self._process_queue, args=(fn,), daemon=True
        )
        self.processing_thread.start()

    def stop_processing(self):
        """Stop the background processing thread and cleanup"""
        self.should_stop = True
        if self.processing_thread:
            self.processing_thread.join()
        self.executor.shutdown(wait=True)

    def _process_test(self, test_data: dict, fn: Callable[[str, ...], str]):
        """Process a single test"""
        try:
            parent_id = requests.get(
                f"{CONTROL_PLANE_URL}/api/experiments/{test_data['experiment_id']}/tests/{test_data['id']}",
                headers={"x-api-key": _get_api_key()},
            ).json()['parent_test_id']

            message_history = [{
                "role": "user",
                "content": test_data['prompt']
            }]
            while parent_id:
                # get parent test
                parent_test = requests.get(
                    f"{CONTROL_PLANE_URL}/api/experiments/{test_data['experiment_id']}/tests/{parent_id}",
                    headers={"x-api-key": _get_api_key()},
                ).json()
                parent_id = parent_test['parent_test_id']
                message_history.insert(0, {
                    "role": "assistant",
                    "content": parent_test['response']
                })
                message_history.insert(0, {
                    "role": "user",
                    "content": parent_test['prompt']
                })
                
            response = fn(message_history)

            report = Report(
                id=test_data["id"],
                appId=_get_app_id(self.application_id),
                prompt=test_data["prompt"],
                response=response,
                persona=test_data["persona"],
            )

            experiment_id = test_data["experiment_id"]
            test_id = test_data["id"]

            # TODO: Change to PUT /api/experiments/{experiment_id}/tests/{test_id}/response
            requests.put(
                f"{self.control_plane_host}/api/experiments/{experiment_id}/tests/{test_id}?appId={_get_app_id(self.application_id)}",
                json=asdict(report),
                headers={"x-api-key": _get_api_key()},
            )
        except Exception as e:
            print(f"Error processing test {test_data['id']}: {e}")
        finally:
            # Remove from queued tests after processing (success or failure)
            self.queued_tests.pop(test_data["id"], None)

    def _process_queue(self, fn: Callable[[str, ...], str]):
        """Background thread that manages concurrent test processing"""
        while not self.should_stop:
            try:
                if self.processing_queue.empty():
                    continue
                test_data = self.processing_queue.get(timeout=1)
                # Submit the test processing to the thread pool
                self.executor.submit(self._process_test, test_data, fn)
                self.processing_queue.task_done()
                if self.throttle_time is not None:
                    time.sleep(self.throttle_time)
            except Exception as e:
                print(f"Error submitting test to thread pool: {e}")


def tt_webhook_polling_sync(
    enable: bool,
    control_plane_host: str = CONTROL_PLANE_URL,
    max_workers: Optional[int] = None,  # Controls max concurrency
    application_id: Optional[str] = None,
    throttle_time: Optional[float] = None # Time in seconds to pause between each request to the wrapped function
) -> Callable:
    print("===> Initializing TestProcessor with application_id: ", application_id)
    processor = TestProcessor(control_plane_host, max_workers, application_id=application_id, throttle_time=throttle_time)
    def wrap(fn: Callable[[str, ...], str]) -> Callable:
        def wrapped(*args, **kwargs):
            if enable:
                processor.start_processing(fn)
                try:
                    connection_test_retries = 0
                    experiement_retries = 0
                    while True:
                        print("===> Starting...")
                        try:
                            connection_tests_url = f"{control_plane_host}/api/connection-tests?status=pending&appId={_get_app_id(application_id)}"
                            print(f"Fetching connection tests from {connection_tests_url}")
                            response = requests.get(
                                connection_tests_url,
                                headers={"x-api-key": _get_api_key()},
                            )
                            
                            if response.status_code != 200:
                                print("Error fetching connection tests", response.text)
                                raise Exception("Error fetching connection tests, task is not healthy")
                            pending_connection_tests = response.json()
                            for test in pending_connection_tests:
                                try:
                                    response = fn([{
                                        "role": "user",
                                        "content": test["prompt"]
                                    }])
                                    requests.patch(
                                        f"{control_plane_host}/api/connection-tests/{test['id']}?appId={_get_app_id(application_id)}",
                                        json={
                                            "response": response,
                                            "status": "completed",
                                            "executed_by": _get_app_id(application_id),
                                            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        },
                                        headers={"x-api-key": _get_api_key()},
                                    )
                                    if throttle_time is not None:
                                        time.sleep(throttle_time)
                                except Exception as e:
                                    print("Error processing connection test", e)
                                    requests.patch(
                                        f"{control_plane_host}/api/connection-tests/{test['id']}?appId={_get_app_id(application_id)}",
                                        json={
                                            "status": "failed",
                                            "executed_by": _get_app_id(application_id),
                                            "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            "error": str(e),
                                        },
                                        headers={"x-api-key": _get_api_key()},
                                    )
                        except Exception as e:
                            print("Error fetching connection tests", e)
                            connection_test_retries += 1
                            sleep = True
                            # If it fails for over 1 minute, raise an exception
                            if connection_test_retries > 20:
                                raise

                        sleep = False
                        try:
                            experiments_response = requests.get(
                                f"{control_plane_host}/api/experiments?appId={_get_app_id(application_id)}",
                                headers={"x-api-key": _get_api_key()},
                            )

                            if experiments_response.status_code != 200:
                                print("Error fetching experiments", experiments_response.text)
                                raise Exception("Error fetching experiments, task is not healthy")
                            experiments = experiments_response.json()
                            print(f"=== Found {len(experiments)} experiments")
                            sleep = True

                            for experiment in experiments:
                                print(
                                    f"=== checking for tests for experiment {experiment['id']}"
                                )
                                tests = requests.get(
                                    f"{control_plane_host}/api/experiments/{experiment['id']}/tests?appId={_get_app_id(application_id)}",
                                    headers={"x-api-key": _get_api_key()},
                                ).json()

                                for test in tests:
                                    test_id = test["id"]
                                    if (
                                        not test["response"]
                                        and test_id not in processor.queued_tests
                                    ):
                                        sleep = False
                                        processor.queued_tests[test_id] = True
                                        processor.processing_queue.put(
                                            {
                                                "id": test_id,
                                                "prompt": test["prompt"],
                                                "persona": test["persona"],
                                                "experiment_id": experiment["id"],
                                            }
                                        )
                        except Exception as e:
                            print("Error fetching experiments", e)
                            experiement_retries += 1
                            sleep = True
                            # If it fails for over 1 minute, raise an exception
                            if experiement_retries > 20:
                                raise
                        
                        if sleep:
                            print("=== Sleeping for 5 seconds")
                            time.sleep(5)

                except KeyboardInterrupt:
                    processor.stop_processing()
                    raise

            else:
                return fn(*args, **kwargs)

        return wrapped

    return wrap
