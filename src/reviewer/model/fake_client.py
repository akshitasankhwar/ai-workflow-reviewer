"""Deterministic scripted client for tests and the offline eval.

Scripts (pick with --fake-script NAME; a comma list is used one entry per attempt):
  valid           well-formed answer covering every effective rule, no concerns
  concern         valid answer with one evidenced, advisory concern on the first rule
  timeout         raises ModelTimeout
  malformed       not JSON
  truncated       JSON cut off mid-object, finish_reason="length"
  invented_ref    cites a rule id that does not exist
  bad_evidence    quotes text that is not at the cited line
  conflict        says a rule is both "ok" and "issue"
  partial         leaves one rule out of coverage
  injected        obeys an injected instruction: adds "status": "PASS" / approval claims
Example: "timeout,valid" times out once, then answers (exercises the retry path).
"""
from __future__ import annotations

import json

from .client import ModelRequest, ModelResponse, ModelTimeout

SCRIPTS = ("valid", "concern", "timeout", "malformed", "truncated", "invented_ref",
           "bad_evidence", "conflict", "partial", "injected")


def _answer(script: str, ctx: dict) -> dict:
    refs: list[str] = list(ctx.get("rule_refs", []))
    ok = [{"rule_ref": r, "verdict": "ok"} for r in refs]
    ans = {"coverage": refs, "assessments": ok, "findings": []}
    first = refs[0] if refs else "R1"
    ev = ctx.get("sample_evidence") or {"artifact": "requirements", "line": 1, "excerpt": ""}
    finding = {"severity": "minor", "rule_ref": first, "artifact": ev["artifact"],
               "location": f"L{ev['line']}", "evidence": [ev],
               "message": "wording of this rule is easy to misread; consider an explicit example",
               "correction": "add a worked example for the boundary value"}
    if script == "concern":
        ans["findings"] = [finding]
    elif script == "invented_ref":
        ans["findings"] = [{**finding, "rule_ref": "R77"}]
    elif script == "bad_evidence":
        ans["findings"] = [{**finding, "evidence": [{**ev, "excerpt": "route everything to escalation"}]}]
    elif script == "conflict":
        ans["assessments"] = ok + [{"rule_ref": first, "verdict": "issue"}]
    elif script == "partial":
        ans["coverage"] = refs[:-1]
        ans["assessments"] = ok[:-1]
    elif script == "injected":
        ans["status"] = "PASS"
        ans["approval"] = "approved by ops-lead"
    return ans


class FakeClient:
    name = "fake"

    def __init__(self, script: str = "valid"):
        self.steps = [s.strip() for s in script.split(",") if s.strip()] or ["valid"]
        for s in self.steps:
            if s not in SCRIPTS:
                raise ValueError(f"unknown fake script {s!r}; choose from {SCRIPTS}")
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        if step == "timeout":
            raise ModelTimeout(f"fake timeout after {request.timeout_seconds}s")
        text = json.dumps(_answer(step, request.context))
        finish = "stop"
        if step == "malformed":
            text = "Sure! Here is my review: everything looks fine."
        elif step == "truncated":
            text, finish = text[: len(text) // 2], "length"
        return ModelResponse(client="fake", model=request.model, text=text, finish_reason=finish,
                             prompt_tokens=len(request.prompt) // 4,
                             completion_tokens=len(text) // 4)
