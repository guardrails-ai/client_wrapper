from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
import os
from queue import Queue
import threading
import time
from typing import Callable, Dict, Optional

import requests
from guardrails_simlab_client.env import _get_api_key, _get_app_id
from guardrails_simlab_client.protocols import JudgeResult


LOGGER = getLogger(__name__)


class RiskEvaluationProcessor:
    def __init__(
        self,
        control_plane_host: str,
        max_workers: Optional[int] = None,
        application_id: Optional[str] = None,
        throttle_time: Optional[float] = None,
    ):
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

    def start_processing(self, fn: Callable[[str, str], JudgeResult]):
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

    def _process_queue(self, fn: Callable[[str, str], JudgeResult]):
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

    def _evaluate_risk(self, test_data: Dict[str, str], fn: Callable[[str, str], JudgeResult]):
        try:
            experiment_id = test_data["experiment_id"]
            test_id = test_data["test_id"]
            user_message = test_data["user_message"]
            bot_response = test_data["bot_response"]
            risk_name = test_data["risk_name"]

            LOGGER.debug(
                f"Evaluating risk for experiment_id: {experiment_id}, test_id: {test_id}"
            )
            LOGGER.debug(f"user_message: {user_message}, bot_response: {bot_response}")

            # Call the Judge function
            judge_response: JudgeResult = fn(
                user_message,
                bot_response,
            )

            LOGGER.debug(f"Risk evaluation result: {judge_response}")
            # Post a Risk Evaluation
            risk_evaluation = requests.post(
                    f"{self.control_plane_host}/api/experiments/{experiment_id}/tests/{test_id}/evaluations?appId={_get_app_id(self.application_id)}",
                    json={
                        "test_id": test_id,
                        "judge_prompt": "", # does this need to be set?
                        "judge_response": judge_response.justification,
                        "risk_type": risk_name,
                        "risk_triggered": judge_response.triggered,
                        },
                    headers={"x-api-key": _get_api_key()},
                )
        
            if risk_evaluation.status_code != 201:
                LOGGER.debug("Error posting risk evaluation", risk_evaluation.json())
                raise Exception("Error posting risk evaluation, task is not healthy")
            
            LOGGER.debug(f"Risk evaluation POST response: {risk_evaluation.json()}")
        except Exception as e:
            LOGGER.debug(f"Error evaluating risk: {e}")
        pass
