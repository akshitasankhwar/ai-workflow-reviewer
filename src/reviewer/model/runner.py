"""Calls a client with bounded retries and a per-review call budget; records every attempt.

Retried: timeout, malformed JSON, truncated JSON, schema errors (transport/format problems).
Not retried: semantic problems (invented refs, bad evidence, conflicts) - the validator reports
those and asking again would only spend budget.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from typing import Callable

from .client import ModelClient, ModelRequest, ModelTimeout


@dataclass
class Attempt:
    n: int
    outcome: str                # ok | timeout | malformed | truncated | schema | error
    detail: str = ""
    response_sha256: str = ""
    latency_ms: int = 0


@dataclass
class RunResult:
    data: dict[str, Any] | None
    attempts: list[Attempt] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str = ""

    @property
    def calls(self) -> int:
        return len(self.attempts)

    @property
    def retries(self) -> int:
        return max(0, self.calls - 1)


def run_model(client: ModelClient, req: ModelRequest, max_retries: int, max_calls: int,
              shape: Callable[[dict], str | None] = lambda d: None) -> RunResult:
    out = RunResult(data=None)
    budget = min(max_retries + 1, max_calls)
    for n in range(1, budget + 1):
        try:
            resp = client.complete(req)
        except ModelTimeout as e:
            out.attempts.append(Attempt(n, "timeout", str(e)))
            continue
        except Exception as e:  # noqa: BLE001 - any client failure is recorded, never hidden
            out.attempts.append(Attempt(n, "error", f"{type(e).__name__}: {e}"))
            continue
        out.prompt_tokens += resp.prompt_tokens
        out.completion_tokens += resp.completion_tokens
        a = Attempt(n, "ok", response_sha256=resp.sha256, latency_ms=resp.latency_ms)
        out.attempts.append(a)
        if resp.finish_reason == "length":
            a.outcome, a.detail = "truncated", "finish_reason=length"
            continue
        try:
            data = json.loads(resp.text)
        except json.JSONDecodeError as e:
            a.outcome, a.detail = "malformed", f"invalid JSON: {e.msg} at char {e.pos}"
            continue
        if not isinstance(data, dict):
            a.outcome, a.detail = "malformed", "top-level JSON is not an object"
            continue
        err = shape(data)
        if err:
            a.outcome, a.detail = "schema", err
            continue
        out.data = data
        return out
    last = out.attempts[-1] if out.attempts else None
    out.error = (f"no usable model answer after {out.calls} call(s)"
                 + (f"; last: {last.outcome} {last.detail}".rstrip() if last else ""))
    return out
