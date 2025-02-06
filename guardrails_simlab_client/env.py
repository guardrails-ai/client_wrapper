import os
import re
from typing import Optional


DEFAULT_CONTROL_PLANE_URL = "http://localhost:8080"

CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", DEFAULT_CONTROL_PLANE_URL)


def _get_app_id(application_id: Optional[str] = None) -> str:
    if application_id:
        return application_id
    application_id = os.environ.get("GUARDRAILS_APP_ID")
    if not application_id:
        raise ValueError("GUARDRAILS_APP_ID is not set!")
    return application_id


def _get_api_key() -> str:
    home_filepath = os.path.expanduser("~")
    guardrails_rc_filepath = os.path.join(home_filepath, ".guardrailsrc")

    api_key = os.environ.get("GUARDRAILS_TOKEN")

    if not api_key and os.path.exists(guardrails_rc_filepath):
        with open(guardrails_rc_filepath, "r") as f:
            for line in f:
                match = re.match(r"token\s*=\s*(?P<api_key>.+)", line)
                if match:
                    api_key = match.group("api_key").strip()
                    break

    if not api_key:
        raise ValueError(
            "GUARDRAILS_TOKEN environment variable is not set or found in $HOME/.guardrailsrc"
        )

    return api_key
