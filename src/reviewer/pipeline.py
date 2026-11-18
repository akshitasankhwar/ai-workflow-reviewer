"""Orchestrates one review, in order:
  load -> parse/compile each artifact to IR -> resolve approvals -> effective requirements
  -> deterministic checks -> (optional) model review + validation -> decision -> report.
No stage may silently drop input: anything not handled becomes a coverage gap.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

from .approvals.resolver import ResolvedRequirements, resolve
from .contracts.common import CoverageItem, Issue
from .contracts.ir import DecisionList, render
from .contracts.report import CheckResult, Finding, ModelUsage, Report
from .ingest.loader import LoadedBundle, load_bundle
from .ingest.reference_map import ReferenceMap, build_reference_map


@dataclass
class Analysis:
    """Everything known about a bundle before any check or model runs."""

    bundle: LoadedBundle
    resolved: ResolvedRequirements | None = None
    refmap: ReferenceMap | None = None
    issues: list[Issue] = dc_field(default_factory=list)
    coverage: list[CoverageItem] = dc_field(default_factory=list)

    @property
    def effective(self) -> DecisionList | None:
        return self.resolved.decision_list if self.resolved else None


def analyze(path: str | Path, config: dict[str, Any]) -> Analysis:
    b = load_bundle(path, config)
    a = Analysis(bundle=b, issues=b.all_issues(), coverage=b.all_coverage())
    if b.requirements is None:
        return a
    raw_appr = b.raw.get("approvals")
    # ablation switch (Stage 4 only): pretend there are no approvals at all
    approvals = None if config.get("ablation", {}).get("ignore_approvals") else b.approvals
    a.resolved = resolve(b.requirements, approvals, b.requirements.revision,
                         raw_appr.version if raw_appr else "?")
    a.issues += a.resolved.issues
    a.coverage += a.resolved.coverage
    a.refmap = build_reference_map(a.resolved.requirements, b.spec, b.workflow, b.code)
    a.issues += a.refmap.issues
    return a


def _dl(dl: DecisionList | None) -> dict[str, Any] | None:
    if dl is None:
        return None
    return {"source": dl.source, "version": dl.version,
            "rules": [{"ref": r.ref, "when": render(r.condition), "route": r.route}
                      for r in dl.rules],
            "default_route": dl.default_route}


def analysis_to_json(a: Analysis) -> dict[str, Any]:
    b = a.bundle
    r = a.resolved
    return {
        "bundle_id": b.bundle_id,
        "versions": b.versions(),
        "input_hash": b.input_hash(),
        "incomplete_reasons": b.incomplete_reasons,
        "approvals": None if r is None else {
            "applied": r.applied, "ignored": [{"id": i, "reason": why} for i, why in r.ignored],
            "conflicts": r.conflicts, "unresolved": r.unresolved},
        "effective_requirements": None if r is None else [
            {"id": q.id, "text": q.text, "route": q.route, "default": q.is_default,
             "when": render(q.condition) if q.condition is not None else None}
            for q in r.requirements],
        "decision_lists": {
            "requirements": _dl(a.effective),
            "spec": _dl(b.spec.decision_list if b.spec else None),
            "workflow": _dl(b.workflow.decision_list if b.workflow else None),
            "code": _dl(b.code.decision_list if b.code else None),
        },
        "trace": None if a.refmap is None else {
            k: {"spec": e.spec, "workflow": e.workflow, "code": e.code}
            for k, e in a.refmap.entries.items()},
        "issues": [i.model_dump(mode="json") for i in a.issues],
        "coverage": [c.model_dump(mode="json") for c in a.coverage],
    }


def review(path: str | Path, config: dict[str, Any], model: str = "none",
           disable: tuple[str, ...] = (), fake_script: str | None = None) -> Report:
    """Deterministic checks, then (if requested) the advisory model review.
    When a model is requested, model_review becomes a required check: if it cannot give a
    validated answer the review is INCOMPLETE. Model findings never block on their own."""
    from .checks import OPTIONAL, REQUIRED, ReviewContext, run_check
    from .decision import decide_status

    a = analyze(path, config)
    b = a.bundle
    ctx = ReviewContext(analysis=a, config=config)
    checks: list[CheckResult] = []
    findings: list[Finding] = []
    for name, fn in [*REQUIRED.items(), *OPTIONAL.items()]:
        if name in disable:
            checks.append(CheckResult(name=name, status="skipped", method="none",
                                      detail="disabled by --disable"))
            continue
        res, fs = run_check(name, fn, ctx)
        checks.append(res)
        findings += fs
    usage = ModelUsage(client=model, model="-", calls=0, retries=0, response_source="none")
    required = list(REQUIRED)
    if model != "none":
        required.append("model_review")
        if "model_review" in disable:
            checks.append(CheckResult(name="model_review", status="skipped", method="none",
                                      detail="disabled by --disable"))
        else:
            res, fs, usage = _model_stage(a, checks, config, model, fake_script)
            checks.append(res)
            findings += fs
    order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
    findings.sort(key=lambda f: (order[f.severity], f.check, f.rule_ref or "", f.location))
    findings = [f.model_copy(update={"id": f"F{i:03d}"}) for i, f in enumerate(findings, 1)]
    status, why = decide_status(checks, findings, a.coverage, b.incomplete_reasons, a.issues,
                                a.effective is not None, required)
    unreviewed = [f"{c.location.artifact} {c.location.pointer}: {c.status} ({c.reason})"
                  for c in a.coverage if c.status in ("unsupported", "ambiguous")]
    unreviewed += [f"check {c.name} {c.status}: {c.detail}" for c in checks
                   if c.status in ("skipped", "error")]
    return Report(bundle_id=b.bundle_id, status=status, summary="; ".join(why), findings=findings,
                  coverage=a.coverage, checks=checks, incomplete_reasons=b.incomplete_reasons,
                  unreviewed_scope=unreviewed, artifact_versions=b.versions(),
                  input_hash=b.input_hash(),
                  model_usage=usage)


def _model_stage(a: Analysis, checks: list[CheckResult], config: dict[str, Any], model: str,
                 fake_script: str | None) -> tuple[CheckResult, list[Finding], ModelUsage]:
    """Prompt -> (cache | client with bounded retries) -> validation -> one check result."""
    from .cache import ModelCache, cache_key
    from .model.client import ModelRequest
    from .model.fake_client import FakeClient
    from .model.ollama_client import OllamaClient
    from .model.prompt_builder import PromptTooLarge, build_prompt
    from .model.runner import run_model
    from .model.validator import shape_error, validate

    mc = config["model"]
    model_name = "fake-reviewer" if model == "fake" else mc.get("ollama_model", "qwen2.5:3b")
    usage = ModelUsage(client=model, model=model_name, calls=0, retries=0,
                       prompt_version=mc["prompt_version"])

    def err(detail: str) -> tuple[CheckResult, list[Finding], ModelUsage]:
        return CheckResult(name="model_review", status="error", method="model", detail=detail), [], usage

    try:
        prompt, ctx = build_prompt(a, checks, mc["prompt_version"],
                                   int(config["limits"].get("max_prompt_chars", 60000)))
    except PromptTooLarge as e:
        return err(str(e))
    req = ModelRequest(model=model_name, prompt=prompt, prompt_version=mc["prompt_version"],
                       temperature=float(mc["temperature"]), max_tokens=int(mc["max_tokens"]),
                       timeout_seconds=float(mc["timeout_seconds"]), context=ctx)
    if model == "fake":
        script = fake_script or "valid"
        client, client_id = FakeClient(script), f"fake:{script}"
    else:
        client = OllamaClient()
        client_id = f"real:{client.host}"
    usage = usage.model_copy(update={"prompt_sha256": req.prompt_sha256, "request": req.config()})
    if a.effective is None:
        return err("no effective requirements to review")

    cache_cfg = config.get("cache", {})
    cache = ModelCache(cache_cfg.get("dir", ".cache")) if cache_cfg.get("enabled") else None
    key = cache_key(prompt, req.config(), client_id)
    usage = usage.model_copy(update={"cache_key": key})
    data = cache.get(key) if cache else None
    if data is not None:
        usage = usage.model_copy(update={"response_source": "cache"})
    else:
        if model == "ollama" and not client.available():
            return err("ollama server not reachable at " + client.host)
        run = run_model(client, req, int(mc["max_retries"]), int(mc["max_calls_per_review"]),
                        shape=shape_error)
        usage = usage.model_copy(update={
            "calls": run.calls, "retries": run.retries, "prompt_tokens": run.prompt_tokens,
            "completion_tokens": run.completion_tokens, "response_source": client.name,
            "attempts": [vars(x) for x in run.attempts]})
        if run.data is None:
            return err(run.error)
        data = run.data

    v = validate(data, ctx["rule_refs"], a.bundle.raw)
    if cache is not None and v.clean and usage.response_source != "cache":
        cache.put(key, data)
    problems = ([f"not covered: {', '.join(v.missing)}"] if v.missing else []) + v.rejected + v.conflicts
    blocking = [f for f in v.findings if f.severity in ("critical", "major")]
    if blocking:
        problems.append(f"{len(blocking)} major model concern(s) need human review")
    detail = "; ".join(problems + v.notes) or f"validated; {len(v.findings)} advisory finding(s)"
    status = "failed" if problems else "passed"
    return CheckResult(name="model_review", status=status, method="model", detail=detail), v.findings, usage
