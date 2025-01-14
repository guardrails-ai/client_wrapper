import os
from dataclasses import asdict
from typing import Callable, Dict, Optional
from logging import getLogger

import time
import requests
from concurrent.futures import ThreadPoolExecutor

from queue import Queue
import threading
from client_wrapper.protocols import Report
from client_wrapper.env import CONTROL_PLANE_URL, _get_api_key, _get_app_id

LOGGER = getLogger(__name__)

last_successful_test = None

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
