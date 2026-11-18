"""ModelClient protocol: complete(request) -> ModelResponse.

ModelRequest keeps the full request config (model, prompt version + hash, temperature,
max_tokens, timeout) so every report can say exactly what was asked.
ModelResponse keeps provenance (client, model, raw text, finish reason, latency, tokens).
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class ModelTimeout(Exception):
    """The client did not answer within timeout_seconds."""


@dataclass(frozen=True)
class ModelRequest:
    model: str
    prompt: str
    prompt_version: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    # Not sent to a real model; lets the scripted fake build bundle-aware answers.
    context: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode()).hexdigest()

    def config(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("prompt"), d.pop("context")
        d["prompt_sha256"] = self.prompt_sha256
        return d


@dataclass(frozen=True)
class ModelResponse:
    client: str
    model: str
    text: str
    finish_reason: str = "stop"          # "length" means the output was cut off
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


class ModelClient(Protocol):
    name: str          # "fake" or "real" (used for response_source)

    def complete(self, request: ModelRequest) -> ModelResponse: ...
