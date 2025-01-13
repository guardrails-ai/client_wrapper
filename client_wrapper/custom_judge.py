from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
import os
from queue import Queue
import threading
import time
from typing import Callable, Dict, Optional
from urllib.parse import quote_plus

import requests
from .env import CONTROL_PLANE_URL, _get_api_key, _get_app_id
from .protocols import JudgeResult

LOGGER = getLogger(__name__)

class RiskEvalutationProcessor:
    def __init__(self, control_plane_host: str, max_workers: Optional[int] = None, application_id: Optional[str] = None, throttle_time: Optional[float] = None):
        self.control_plane_host = control_plane_host
        self.processing_queue = Queue()
        self.queued_tests: Dict[str, bool] = {}
        self.should_stop = False
        self.max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.processing_thread = None
        self.application_id = _get_app_id(application_id)
        self.api_key = _get_api_key()
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

    def _process_queue(self, fn: Callable[[str, ...], str]):
        """Background thread that manages concurrent test processing"""
        while not self.should_stop:
            try:
                if self.processing_queue.empty():
                    continue
                test_data = self.processing_queue.get(timeout=1)
                # Submit the test processing to the thread pool
                self.executor.submit(self._evaluate_risk, test_data, fn)
                self.processing_queue.task_done()
                if self.throttle_time is not None:
                    time.sleep(self.throttle_time)
            except Exception as e:
                LOGGER.debug(f"Error submitting test to thread pool: {e}")



    def _evaluate_risk(self, risk_name: str, app_id: Optional[str] = None, enable: Optional[bool] = True) -> str:
        # TODO: Call the Judge function
        # TODO: Post a Risk Evaluation
        pass

def custom_judge (
    *,
	risk_name: str,
    enable: Optional[bool] = True,
    control_plane_host: str = CONTROL_PLANE_URL,
    max_workers: Optional[int] = None,  # Controls max concurrency
    application_id: Optional[str] = None,
    throttle_time: Optional[float] = None # Time in seconds to pause between each request to the wrapped function
) ->  Callable:
    LOGGER.debug("===> Initializing TestProcessor with application_id: ", application_id)
    processor = RiskEvalutationProcessor(
        control_plane_host, 
        max_workers, 
        application_id=application_id, 
        throttle_time=throttle_time
    )
    def wrap(fn: Callable[[str, str], JudgeResult]) -> Callable[[str, str], JudgeResult]:
        def wrapped(*args, **kwargs):
            if enable:
                processor.start_processing(fn)
                try:
                    experiement_retries = 0
                    test_retries = 0
                    while True:
                        LOGGER.debug("===> Starting...")
                        try:
                            experiments_response = requests.get(
                                f"{control_plane_host}/api/experiments?appId={_get_app_id(application_id)}&validationStatus=in%20progress",
                                headers={"x-api-key": _get_api_key()},
                            )

                            if experiments_response.status_code != 200:
                                LOGGER.debug("Error fetching experiments", experiments_response.text)
                                raise Exception("Error fetching experiments, task is not healthy")
                            experiments = experiments_response.json()
                            LOGGER.debug(f"=== Found {len(experiments)} experiments with validation in progress")

                            for experiment in experiments:
                                try:
                                    LOGGER.debug(
                                        f"=== checking for tests for experiment {experiment['id']}"
                                    )
                                    tests_response = requests.get(
                                        f"{control_plane_host}/api/experiments/{experiment['id']}/tests?appId={_get_app_id(application_id)}&unevaluated-risk={quote_plus(risk_name)}&include-risk-evaluations=false",
                                        headers={"x-api-key": _get_api_key()},
                                    )

                                    if tests_response.status_code != 200:
                                        LOGGER.debug("Error fetching tests", tests_response.text)
                                        raise Exception("Error fetching tests, task is not healthy")
                                    tests = tests_response.json()

                                    for test in tests:
                                        test_id = test["id"]
                                        if (
                                            test_id not in processor.queued_tests
                                        ):
                                            processor.queued_tests[test_id] = True
                                            processor.processing_queue.put(
                                                {
                                                    "experiment_id": experiment["id"],
                                                    "test_id": test_id,
                                                    "user_message": test["prompt"],
                                                    "bot_response": test["response"],
                                                }
                                            )
                                except Exception as e:
                                    LOGGER.debug("Error fetching tests", e)
                                    test_retries += 1
                                    # If it fails for over 1 minute, raise an exception
                                    if test_retries > 20:
                                        raise
                        except Exception as e:
                            LOGGER.debug("Error fetching experiments", e)
                            experiement_retries += 1
                            # If it fails for over 1 minute, raise an exception
                            if experiement_retries > 20:
                                raise
                        
                        LOGGER.debug("=== Sleeping for 5 seconds")
                        time.sleep(5)
                except KeyboardInterrupt:
                    processor.stop_processing()
                    raise
            else:
                return fn(*args, **kwargs)

        return wrapped

    return wrap
