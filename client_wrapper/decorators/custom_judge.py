from logging import getLogger
import time
from typing import Callable, Optional
from urllib.parse import quote_plus

import requests
from client_wrapper.env import CONTROL_PLANE_URL, _get_api_key, _get_app_id
from client_wrapper.protocols import JudgeResult

LOGGER = getLogger(__name__)

from client_wrapper.classes.judge_result import JudgeResult
from client_wrapper.processors.risk_evaluation_processor import RiskEvaluationProcessor

def custom_judge(
    *,
    risk_name: str,
    enable: Optional[bool] = True,
    control_plane_host: str = CONTROL_PLANE_URL,
    max_workers: Optional[int] = None,  # Controls max concurrency
    application_id: Optional[str] = None,
    throttle_time: Optional[
        float
    ] = None,  # Time in seconds to pause between each request to the wrapped function
) -> Callable:
    LOGGER.debug(
        f"===> Initializing TestProcessor with application_id: {application_id}"
    )
    processor = RiskEvaluationProcessor(
        control_plane_host,
        max_workers,
        application_id=application_id,
        throttle_time=throttle_time,
    )

    def wrap(
        fn: Callable[[str, str], JudgeResult]
    ) -> Callable[[str, str], JudgeResult]:
        def wrapped(*args, **kwargs):
            LOGGER.debug(f"===> Wrapped function called with args: f{args}")
            if enable:
                LOGGER.debug("===> Starting processing")
                processor.start_processing(fn)
                try:
                    experiment_retries = 0
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
                            # experiments = [{"id": "123"}]
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
                                        if test_id not in processor.queued_tests:
                                            processor.queued_tests[test_id] = True
                                            processor.processing_queue.put(
                                                {
                                                    "experiment_id": experiment["id"],
                                                    "test_id": test_id,
                                                    "user_message": test["prompt"],
                                                    "bot_response": test["response"],
                                                    "risk_name": risk_name,
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
                            experiment_retries += 1
                            # If it fails for over 1 minute, raise an exception
                            if experiment_retries > 20:
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
