"""Turns structural ingest issues of one artifact into findings (shared by workflow and code checks)."""
from __future__ import annotations

from ..contracts.common import Location
from ..contracts.report import CheckResult, Finding
from .base import ReviewContext, mismatch_findings, placeholder

FIX = {
    "version_mismatch": "make the artifact version match the version the bundle declares",
    "duplicate_node_id": "give every workflow node a unique id",
    "dangling_edge": "point the edge at an existing node",
    "dangling_start": "set start to an existing node id",
    "route_without_target": "give the route node a destination",
    "incomplete_decision": "give the decision node a condition, on_true and on_false",
    "cycle": "remove the cycle so every path ends at a route node",
    "path_explosion": "simplify the workflow; too many paths to enumerate",
    "workflow_schema": "fix the workflow so it matches the workflow schema",
    "unreachable_node": "remove the node or connect it to a reachable path",
    "no_entrypoint": "define the routing function the bundle names",
    "code_syntax": "fix the syntax error so the code can be analysed",
    "unreachable_code": "remove the dead code or make its branch reachable",
}


def with_structure(ctx: ReviewContext, kind: str, name: str) -> tuple[CheckResult, list[Finding]]:
    part = getattr(ctx.bundle, kind, None)
    issues = list(part.issues) if part is not None else []
    version = ctx.bundle.versions().get(kind, "?")
    structural: list[Finding] = []
    for i in issues:
        if not i.blocking and i.code not in FIX:
            continue
        loc = i.location or Location(artifact=kind, version=version, pointer="/")
        structural.append(placeholder(
            name, "major" if i.blocking else "minor", None, loc, [loc],
            f"[{i.code}] {i.message}", FIX.get(i.code, "fix the reported structural problem")))
    res, findings = mismatch_findings(ctx, kind, name)
    blocking = sum(f.severity == "major" for f in structural)
    if res.status == "skipped" and structural:
        res = CheckResult(name=name, status="failed" if blocking else "skipped", method="structural",
                          detail=f"{len(structural)} structural issue(s); routing not compared: "
                                 + res.detail.removeprefix("not run: "))
    elif structural:
        res = res.model_copy(update={
            "status": "failed" if blocking else res.status,
            "detail": f"{len(structural)} structural issue(s); " + res.detail})
    return res, structural + findings
