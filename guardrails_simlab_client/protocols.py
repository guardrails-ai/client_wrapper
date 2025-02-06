from dataclasses import dataclass
from typing import Dict, Optional


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


@dataclass
class JudgeResult:
    triggered: bool
    justification: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
