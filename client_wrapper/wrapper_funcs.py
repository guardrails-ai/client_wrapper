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
from typing import Callable, Dict
from logging import getLogger

import time
import requests
from websockets.sync.client import connect as sync_connect
from concurrent.futures import ThreadPoolExecutor

from queue import Queue
import threading
from .protocols import Report

DEFAULT_CONTROL_PLANE_URL = "http://localhost:8080"
DEFAULT_GENERATION_URL = "ws://localhost:48001/ws"

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", DEFAULT_CONTROL_PLANE_URL)
GENERATION_URL = os.environ.get("GENERATION_URL", DEFAULT_GENERATION_URL)

LOGGER = getLogger(__name__)

last_successful_test = None


def _get_token() -> str:
    return os.environ.get("GUARDRAILS_WEBHOOK_TOKEN", "hunter2")


class TestProcessor:
    def __init__(
        self, control_plane_host: str, generator_host: str, max_workers: int = 5
    ):
        self.control_plane_host = control_plane_host
        self.generator_host = generator_host
        self.processing_queue = Queue()
        self.queued_tests: Dict[str, bool] = {}
        self.should_stop = False
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.processing_thread = None

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
            response = fn(test_data["prompt"])

            report = Report(
                id=test_data["id"],
                token=_get_token(),
                prompt=test_data["prompt"],
                response=response,
                persona=test_data["persona"],
            )

            requests.put(
                f"{self.control_plane_host}/api/tests/{test_data['id']}",
                json=asdict(report),
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
            except Exception as e:
                print(f"Error submitting test to thread pool: {e}")


def tt_webhook_polling_sync(
    enable: bool,
    control_plane_host: str = CONTROL_PLANE_URL,
    generator_host: str = GENERATION_URL,
    max_workers: int = 100,  # Controls max concurrency
) -> Callable:
    processor = TestProcessor(control_plane_host, generator_host, max_workers)
    def wrap(fn: Callable[[str, ...], str]) -> Callable:
        def wrapped(*args, **kwargs):
            if enable:
                processor.start_processing(fn)
                try:
                    last_successful_test = None
                    while True:
                        print("===> Starting...")
                        if not last_successful_test:
                            print("===> No successful connection tests yet, check for tests")
                            pending_connection_tests = requests.get(
                                f"{control_plane_host}/api/connection-tests?status=pending&token={_get_token()}"
                            ).json()
                            for test in pending_connection_tests:
                                try:
                                    response = fn(test["prompt"])
                                    requests.patch(
                                        f"{control_plane_host}/api/connection-tests/{test['id']}",
                                        json={
                                            "response": response,
                                            "status": "completed",
                                            "executed_by": _get_token(),
                                            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        },
                                    )
                                    last_successful_test = int(time.time())
                                except Exception as e:
                                    print("Error processing connection test", e)
                                    requests.patch(
                                        f"{control_plane_host}/api/connection-tests/{test['id']}",
                                        json={
                                            "status": "failed",
                                            "executed_by": _get_token(),
                                            "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            "error": str(e),
                                        },
                                    )
                                    last_successful_test = None

                        experiments = requests.get(
                            f"{control_plane_host}/api/experiments?token={_get_token()}"
                        ).json()
                        print(f"=== Found {len(experiments)} experiments")
                        sleep = True

                        for experiment in experiments:
                            print(
                                f"=== checking for tests for experiment {experiment['id']}"
                            )
                            tests = requests.get(
                                f"{control_plane_host}/api/experiments/{experiment['id']}/tests"
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
                                        }
                                    )

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
