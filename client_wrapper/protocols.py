
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class WebhookCommandEnum(Enum):
    REGISTER_FUNCTION = "register_function"
    TRIGGER_FUNCTION = "trigger_function"
    SHUTDOWN = "shutdown"

    @classmethod
    def from_string(cls, string: str) -> "WebhookCommandEnum":
        if string.startswith("WebhookCommandEnum."):
            return cls[string[len("WebhookCommandEnum."):]]
        else:
            return cls[string]

    def to_string_type(self, full: bool = False) -> str:
        if full:
            return str(self)
        return str(self)[len("WebhookCommandEnum."):]


@dataclass
class Report:
    id: str
    appId: str
    prompt: str
    response: str
    persona: Optional[str] = ""


@dataclass
class GeneratorHandshake:
    token: str


@dataclass
class GeneratorPrompt:
    id: str
    prompt: str
    persona: Optional[str] = ""
