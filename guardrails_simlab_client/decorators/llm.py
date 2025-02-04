from typing import Callable,Optional
from logging import getLogger

import time
import requests

from guardrails_simlab_client.env import CONTROL_PLANE_URL, _get_api_key, _get_app_id
from guardrails_simlab_client.processors.test_processor import TestProcessor

LOGGER = getLogger(__name__)

def tt_webhook_polling_sync(
    enable: bool,
    control_plane_host: str = CONTROL_PLANE_URL,
    max_workers: Optional[int] = None,  # Controls max concurrency
    application_id: Optional[str] = None,
    throttle_time: Optional[float] = None # Time in seconds to pause between each request to the wrapped function
) -> Callable:
    LOGGER.info(f"===> Initializing TestProcessor with application_id: {application_id}")
    processor = TestProcessor(control_plane_host, max_workers, application_id=application_id, throttle_time=throttle_time)
    def wrap(fn: Callable[[str, ...], str]) -> Callable:
        def wrapped(*args, **kwargs):
            if enable:
                processor.start_processing(fn)
                try:
                    connection_test_retries = 0
                    experiement_retries = 0
                    while True:
                        LOGGER.info("===> Starting...")
                        try:
                            connection_tests_url = f"{control_plane_host}/api/connection-tests?status=pending&appId={_get_app_id(application_id)}"
                            LOGGER.info(f"Fetching connection tests from {connection_tests_url}")
                            response = requests.get(
                                connection_tests_url,
                                headers={"x-api-key": _get_api_key()},
                            )
                            
                            if not response.ok:
                                LOGGER.info(f"Error fetching connection tests: {response.text}", )
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
                                    LOGGER.info(f"Error processing connection test: {e}")
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
                            LOGGER.info(f"Error fetching connection tests: {e}")
                            connection_test_retries += 1
                            sleep = True
                            # If it fails for over 1 minute, raise an exception
                            if connection_test_retries > 20:
                                raise

                        sleep = False
                        try:
                            experiments_response = requests.get(
                                f"{control_plane_host}/api/experiments?appId={_get_app_id(application_id)}&evaluated=false",
                                headers={"x-api-key": _get_api_key()},
                            )

                            if not experiments_response.ok:
                                LOGGER.info(f"Error fetching experiments: {experiments_response.text}")
                                raise Exception("Error fetching experiments, task is not healthy")
                            experiments = experiments_response.json()
                            LOGGER.info(f"=== Found {len(experiments)} unevaluated experiments")
                            sleep = True

                            for experiment in experiments:
                                experiment_id = experiment["id"]
                                limit = processor.max_workers * 2
                                app_id = _get_app_id(application_id)
                                LOGGER.info(
                                    f"=== checking for tests for experiment {experiment_id}"
                                )
                                tests_response = requests.get(
                                    f"{control_plane_host}/api/experiments/{experiment_id}/tests?appId={app_id}&include-risk-evaluations=false&limit={limit}&unprocessed-only=true",
                                    headers={"x-api-key": _get_api_key()},
                                )

                                if not tests_response.ok:
                                    sleep = True
                                    LOGGER.info(f"Error fetching tests: {tests_response.text}")
                                    continue

                                tests = tests_response.json()

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
                            LOGGER.info(f"Error fetching experiments: {e}")
                            experiement_retries += 1
                            sleep = True
                            # If it fails for over 1 minute, raise an exception
                            if experiement_retries > 20:
                                raise
                        
                        if sleep:
                            LOGGER.info("=== Sleeping for 5 seconds")
                            time.sleep(5)

                except KeyboardInterrupt:
                    processor.stop_processing()
                    raise

            else:
                return fn(*args, **kwargs)

        return wrapped

    return wrap
