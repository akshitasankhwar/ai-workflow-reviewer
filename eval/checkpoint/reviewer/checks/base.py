"""Check protocol and registry; wraps each check so an exception becomes status=error (never pass).

A check is a function `(ctx) -> (CheckResult, list[Finding])`. Finding ids are assigned later
by the pipeline, so checks leave `id` as a placeholder.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

from ..contracts.common import Location
from ..contracts.ir import ERROR_ROUTE, NO_ROUTE, DecisionList
from ..contracts.report import CheckResult, Counterexample, Finding
from ..semantics.diagnose import diagnose, label
from ..semantics.domain import Domain, build_domain
from ..semantics.equivalence import Comparison, MismatchGroup, compare

CheckFn = Callable[["ReviewContext"], "tuple[CheckResult, list[Finding]]"]
ARTIFACTS = ("spec", "workflow", "code")
WHAT = {"spec": "specification", "workflow": "workflow", "code": "code"}


@dataclass
class ReviewContext:
    analysis: Any                     # pipeline.Analysis (not imported: avoids a cycle)
    config: dict[str, Any]
    _domain: Domain | None = None
    _cmp: dict[str, Comparison] = dc_field(default_factory=dict)

    @property
    def bundle(self):
        return self.analysis.bundle

    @property
    def effective(self) -> DecisionList | None:
        return self.analysis.effective

    def dl(self, kind: str) -> DecisionList | None:
        part = getattr(self.bundle, kind, None)
        return part.decision_list if part is not None else None

    @property
    def domain(self) -> Domain:
        if self._domain is None:
            reqs = self.bundle.requirements
            dls = [d for d in [self.effective, *(self.dl(k) for k in ARTIFACTS)] if d is not None]
            self._domain = build_domain(reqs.fields if reqs else {}, dls, self.config)
        return self._domain

    # ---- mapping a deciding rule back to requirement ids ----
    def default_requirement(self) -> str | None:
        res = self.analysis.resolved
        if res is None or not res.requirements or not res.requirements[-1].is_default:
            return None
        return res.requirements[-1].id

    def expected_refs(self, dl: DecisionList, route: str, idx: int | None) -> list[str]:
        if route in (NO_ROUTE, ERROR_ROUTE):
            return []
        if idx is None:
            d = self.default_requirement()
            return [d] if d else []
        return [dl.rules[idx].ref] if dl.rules[idx].ref else []

    def refs_fn(self, kind: str) -> Callable[[DecisionList, str, int | None], list[str]]:
        b = self.bundle

        def spec(dl: DecisionList, route: str, idx: int | None) -> list[str]:
            if route in (NO_ROUTE, ERROR_ROUTE):
                return []
            key = "default" if idx is None else dl.rules[idx].ref
            return list(b.spec.source_refs.get(key, [])) if key else []

        def single(dl: DecisionList, route: str, idx: int | None) -> list[str]:
            if route in (NO_ROUTE, ERROR_ROUTE) or idx is None:
                return []
            ref = dl.rules[idx].ref
            return [x.strip() for x in ref.split(",") if x.strip()] if ref else []

        return spec if kind == "spec" else single

    def comparison(self, kind: str) -> Comparison:
        if kind not in self._cmp:
            self._cmp[kind] = compare(self.effective, self.dl(kind), self.domain,
                                      self.expected_refs, self.refs_fn(kind))
        return self._cmp[kind]


def placeholder(check: str, severity: str, rule_ref: str | None, loc: Location, evidence: list[Location],
                message: str, correction: str, cx: Counterexample | None = None) -> Finding:
    return Finding(id="F000", check=check, severity=severity, rule_ref=rule_ref, artifact=loc.artifact,
                   version=loc.version, location=loc.pointer, evidence=evidence, message=message,
                   correction=correction, counterexample=cx)


def requirement_location(ctx: ReviewContext, rid: str | None) -> Location | None:
    res = ctx.analysis.resolved
    if res is None or rid is None:
        return None
    for r in res.requirements:
        if r.id == rid:
            return r.location
    return None


def mismatch_findings(ctx: ReviewContext, kind: str, check: str) -> tuple[CheckResult, list[Finding]]:
    """Shared body of the spec / workflow / code equivalence checks."""
    exp, act = ctx.effective, ctx.dl(kind)
    if exp is None or act is None:
        missing = "effective requirements" if exp is None else f"compiled {WHAT[kind]}"
        return CheckResult(name=check, status="skipped", method="none",
                           detail=f"not run: no {missing} to compare"), []
    cmp = ctx.comparison(kind)
    findings = [_finding(ctx, kind, check, exp, act, g) for g in cmp.groups]
    scope = (f"{cmp.method}: {cmp.tickets} representative tickets over {len(ctx.domain.fields)} fields"
             + (" (partition of the supported condition language)" if cmp.method == "exhaustive"
                else " (seeded sample; equivalence NOT proven)"))
    if kind == "code":
        scope += "; code analysed from the AST only, never executed"
    if cmp.notes:
        scope += "; " + "; ".join(cmp.notes)
    detail = (f"{len(findings)} mismatch group(s); " if findings else "equivalent on all tickets; ") + scope
    return CheckResult(name=check, status="failed" if findings else "passed", method=cmp.method,
                       detail=detail, tickets_evaluated=cmp.tickets), findings


def _finding(ctx: ReviewContext, kind: str, check: str, exp: DecisionList, act: DecisionList,
             g: MismatchGroup) -> Finding:
    refs = ctx.refs_fn(kind)
    d = diagnose(g, exp, act,
                 lambda i: ctx.expected_refs(exp, "x", i),
                 lambda i: refs(act, "x", i), WHAT[kind])
    rid = g.expected_refs[0] if g.expected_refs else (g.actual_refs[0] if g.actual_refs else None)
    if g.actual_idx is not None:
        act_loc = act.rules[g.actual_idx].location
    else:
        act_loc = act.default_location or Location(artifact=kind, version=act.version, pointer="/")
    evidence = [x for x in (requirement_location(ctx, rid), act_loc) if x is not None]
    cx = Counterexample(ticket=g.ticket, expected_route=g.expected_route, actual_route=g.actual_route,
                        expected_rule=", ".join(g.expected_refs) or label(exp, g.expected_idx),
                        actual_rule=label(act, g.actual_idx)
                        + (f" ({', '.join(g.actual_refs)})" if g.actual_refs else ""))
    msg = f"[{d.kind}] {d.message}"
    if g.count > 1:
        msg += f" ({g.count} representative tickets in this group)"
    return placeholder(check, "major", rid, act_loc, evidence, msg, d.correction, cx)


def run_check(name: str, fn: CheckFn, ctx: ReviewContext) -> tuple[CheckResult, list[Finding]]:
    try:
        res, findings = fn(ctx)
    except Exception as e:  # noqa: BLE001 - a crashing check must surface, never pass
        return CheckResult(name=name, status="error", method="none",
                           detail=f"check crashed: {type(e).__name__}: {e}"), []
    return res, findings
