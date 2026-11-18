"""Optional local real model via the Ollama HTTP API (stdlib urllib, no extra deps).
Off by default; used only with --model ollama. Unavailable server -> the model check errors,
which makes the review INCOMPLETE (never PASS).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from .client import ModelRequest, ModelResponse, ModelTimeout


class OllamaClient:
    name = "real"

    def __init__(self, host: str = "http://127.0.0.1:11434"):
        self.host = host.rstrip("/")

    def available(self) -> bool:
        try:
            urllib.request.urlopen(self.host + "/api/tags", timeout=2).read()
            return True
        except (urllib.error.URLError, OSError):
            return False

    def complete(self, request: ModelRequest) -> ModelResponse:
        body = json.dumps({"model": request.model, "prompt": request.prompt, "stream": False,
                           "format": "json",
                           "options": {"temperature": request.temperature,
                                       "num_predict": request.max_tokens, "seed": 0}}).encode()
        req = urllib.request.Request(self.host + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=request.timeout_seconds) as r:
                data = json.loads(r.read())
        except (socket.timeout, TimeoutError) as e:
            raise ModelTimeout(str(e)) from e
        return ModelResponse(client="ollama", model=request.model, text=data.get("response", ""),
                             finish_reason=data.get("done_reason", "stop"),
                             latency_ms=int((time.monotonic() - t0) * 1000),
                             prompt_tokens=int(data.get("prompt_eval_count", 0)),
                             completion_tokens=int(data.get("eval_count", 0)))
