
from dataclasses import dataclass
from enum import Enum
from typing import Optional

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