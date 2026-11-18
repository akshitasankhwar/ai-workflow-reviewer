"""Every effective requirement mapped in spec, workflow and code? Omissions reported
even if the id never appears in the spec.

A missing reference alone is minor (behaviour may still be right through another rule);
it becomes major when the equivalence check also found a mismatch for that requirement.
"""
from __future__ import annotations

from ..contracts.common import Location
from ..contracts.report import CheckResult, Finding
from .base import ARTIFACTS, WHAT, ReviewContext, placeholder, requirement_location

NAME = "coverage"


def run(ctx: ReviewContext) -> tuple[CheckResult, list[Finding]]:
    res, refmap = ctx.analysis.resolved, ctx.analysis.refmap
    if res is None or refmap is None or ctx.effective is None:
        return CheckResult(name=NAME, status="skipped", method="none",
                           detail="not run: no effective requirements"), []
    present = [k for k in ARTIFACTS if ctx.dl(k) is not None]
    findings: list[Finding] = []
    checked = 0
    for r in res.requirements:
        entry = refmap.entries.get(r.id)
        for kind in present:
            checked += 1
            if entry is not None and getattr(entry, kind):
                continue
            wrong = any(r.id in g.expected_refs for g in ctx.comparison(kind).groups)
            loc = Location(artifact=kind, version=ctx.dl(kind).version, pointer="/")
            findings.append(placeholder(
                NAME, "major" if wrong else "minor", r.id, loc,
                [x for x in (requirement_location(ctx, r.id), loc) if x is not None],
                f"{r.id} is not referenced anywhere in the {WHAT[kind]}"
                + ("; its tickets are also routed wrongly (see the equivalence findings)" if wrong
                   else "; routing still matches, so only traceability is missing"),
                f"add a rule in the {WHAT[kind]} that implements and cites {r.id}"))
    missing = [k for k in ARTIFACTS if k not in present]
    detail = (f"{checked} requirement/artifact links checked, {len(findings)} missing"
              + (f"; not checked because the artifact did not compile: {', '.join(missing)}"
                 if missing else ""))
    if any(f.severity == "major" for f in findings):
        status = "failed"
    elif missing:
        status = "skipped"
    else:
        status = "passed"
    return CheckResult(name=NAME, status=status, method="structural", detail=detail), findings
