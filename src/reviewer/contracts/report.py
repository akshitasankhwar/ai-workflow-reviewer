"""Output contract: the review report written for every bundle."""
from __future__ import annotations

from typing import Any, Literal

from .common import CoverageItem, Location, Strict

Status = Literal["PASS", "CHANGES_REQUIRED", "INCOMPLETE"]
Severity = Literal["critical", "major", "minor", "info"]


class Counterexample(Strict):
    ticket: dict[str, Any]
    expected_route: str
    actual_route: str
    expected_rule: str | None = None
    actual_rule: str | None = None


class Finding(Strict):
    id: str
    check: str
    severity: Severity
    rule_ref: str | None
    artifact: str
    version: str
    location: str
    evidence: list[Location]
    message: str
    correction: str
    counterexample: Counterexample | None = None
    origin: Literal["deterministic", "model"] = "deterministic"


class CheckResult(Strict):
    name: str
    status: Literal["passed", "failed", "skipped", "error"]
    method: Literal["exhaustive", "sampled", "structural", "model", "none"]
    detail: str
    tickets_evaluated: int = 0


class ModelUsage(Strict):
    client: str
    model: str
    calls: int
    retries: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response_source: Literal["fake", "real", "cache", "none"] = "none"
    prompt_version: str | None = None
    prompt_sha256: str | None = None
    request: dict[str, Any] | None = None   # exact request config (prompt text omitted)
    cache_key: str | None = None
    attempts: list[dict[str, Any]] = []     # n, outcome, detail, response_sha256, latency_ms


class Report(Strict):
    bundle_id: str
    status: Status
    summary: str
    findings: list[Finding]
    coverage: list[CoverageItem]
    checks: list[CheckResult]
    incomplete_reasons: list[str] = []
    unreviewed_scope: list[str] = []
    artifact_versions: dict[str, str] = {}
    input_hash: str = ""
    model_usage: ModelUsage | None = None
