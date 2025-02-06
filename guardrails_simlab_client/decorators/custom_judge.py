from logging import getLogger
import time
from typing import Callable, Optional
from urllib.parse import quote_plus

import requests
from guardrails_simlab_client.env import CONTROL_PLANE_URL, _get_api_key, _get_app_id
from guardrails_simlab_client.protocols import JudgeResult
from guardrails_simlab_client.processors.risk_evaluation_processor import (
    RiskEvaluationProcessor,
)

LOGGER = getLogger(__name__)


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
    LOGGER.info(
        f"===> Initializing RiskEvaluationProcessor with application_id: {application_id}"
    )
    processor = RiskEvaluationProcessor(
        control_plane_host,
        max_workers,
        application_id=application_id,
        throttle_time=throttle_time,
    )

    def wrap(
        fn: Callable[[str, str], JudgeResult],
    ) -> Callable[[str, str], JudgeResult]:
        LOGGER.info(f"===> Wrapping function {fn.__name__}")

        def wrapped(*args, **kwargs):
            LOGGER.info(
                f"===> Wrapped function called with args: {args}, kwargs: {kwargs}"
            )
            if enable:
                LOGGER.info("===> Starting processing")
                processor.start_processing(fn)
                try:
                    experiment_retries = 0
                    test_retries = 0
                    while True:
                        LOGGER.info("===> Starting...")
                        try:
                            experiments_response = requests.get(
                                f"{control_plane_host}/api/experiments?appId={_get_app_id(application_id)}&validationStatus=in%20progress",
                                headers={"x-api-key": _get_api_key()},
                            )

                            if not experiments_response.ok:
                                LOGGER.info(
                                    f"Error fetching experiments: {experiments_response.text}"
                                )
                                raise Exception(
                                    "Error fetching experiments, task is not healthy"
                                )
                            experiments = experiments_response.json()
                            LOGGER.info(
                                f"=== Found {len(experiments)} experiments with validation in progress"
                            )
                            # experiments = [{"id": "123"}]
                            for experiment in experiments:
                                try:
                                    if (
                                        risk_name
                                        not in experiment.get("source_data", {})
                                        .get("evaluation_configuration", {})
                                        .keys()
                                    ):
                                        LOGGER.info(
                                            f"=== Skipping experiment {experiment['id']} as it does not have risk {risk_name}"
                                        )
                                        continue
                                    LOGGER.info(
                                        f"=== checking for tests for experiment {experiment['id']}"
                                    )
                                    tests_response = requests.get(
                                        f"{control_plane_host}/api/experiments/{experiment['id']}/tests?appId={_get_app_id(application_id)}&unevaluated-risk={quote_plus(risk_name)}&include-risk-evaluations=false",
                                        headers={"x-api-key": _get_api_key()},
                                    )

                                    if not tests_response.ok:
                                        LOGGER.info(
                                            f"Error fetching tests: {tests_response.text}"
                                        )
                                        raise Exception(
                                            "Error fetching tests, task is not healthy"
                                        )
                                    tests = tests_response.json()

                                    for test in tests:
                                        test_id = test["id"]
                                        if (
                                            test_id not in processor.queued_tests
                                            and test.get("response") is not None
                                        ):
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
                                    LOGGER.info(f"Error fetching tests: {e}")
                                    test_retries += 1
                                    # If it fails for over 1 minute, raise an exception
                                    if test_retries > 20:
                                        raise
                        except Exception as e:
                            LOGGER.info(f"Error fetching experiments: {e}")
                            experiment_retries += 1
                            # If it fails for over 1 minute, raise an exception
                            if experiment_retries > 20:
                                raise

                        LOGGER.info("=== Sleeping for 5 seconds")
                        time.sleep(5)
                except KeyboardInterrupt:
                    processor.stop_processing()
                    raise
            else:
                return fn(*args, **kwargs)

        return wrapped

    return wrap
