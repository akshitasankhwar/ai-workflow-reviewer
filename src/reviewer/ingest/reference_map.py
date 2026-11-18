"""Traceability: which spec rules, workflow route nodes and code returns claim to
implement each effective requirement.

References are evidence only: they never decide equivalence. A requirement nobody
references is reported; so is a reference to a requirement that does not exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ..contracts.artifacts import Requirement
from ..contracts.common import Issue, Location
from ..contracts.ir import Const, NO_ROUTE
from .code_compiler import CompiledCode
from .spec_compiler import CompiledSpec
from .workflow_compiler import CompiledWorkflow


@dataclass
class TraceEntry:
    spec: list[str] = dc_field(default_factory=list)
    workflow: list[str] = dc_field(default_factory=list)
    code: list[int] = dc_field(default_factory=list)


@dataclass
class ReferenceMap:
    entries: dict[str, TraceEntry] = dc_field(default_factory=dict)
    issues: list[Issue] = dc_field(default_factory=list)


def build_reference_map(reqs: list[Requirement], spec: CompiledSpec | None,
                        workflow: CompiledWorkflow | None, code: CompiledCode | None) -> ReferenceMap:
    out = ReferenceMap(entries={r.id: TraceEntry() for r in reqs})
    known = set(out.entries)
    default_id = next((r.id for r in reqs if r.is_default), None)

    def unknown(ref: str, where: Location, what: str) -> None:
        out.issues.append(Issue(code="unknown_ref", blocking=False, location=where,
                                message=f"{what} references {ref}, which is not an effective requirement"))

    if spec is not None and spec.spec is not None:
        for idx, r in enumerate(spec.spec.rules):
            where = Location(artifact="spec", version=spec.decision_list.version if spec.decision_list
                             else "?", pointer=f"/rules/{idx}", excerpt=r.id)
            refs = spec.source_refs.get(r.id, list(r.source_refs))
            if not refs:
                out.issues.append(Issue(code="untraced_rule", blocking=False, location=where,
                                        message=f"spec rule {r.id} cites no requirement"))
            for ref in refs:
                if ref in known:
                    out.entries[ref].spec.append(r.id)
                else:
                    unknown(ref, where, f"spec rule {r.id}")
        for ref in spec.source_refs.get("default", []):
            if ref in known:
                out.entries[ref].spec.append("default")

    if workflow is not None:
        ver = workflow.workflow.workflow_version if workflow.workflow else "?"
        for nid, ref in workflow.rule_refs.items():
            where = Location(artifact="workflow", version=ver, pointer=f"node:{nid}")
            if ref is None:
                out.issues.append(Issue(code="untraced_rule", blocking=False, location=where,
                                        message=f"workflow route node {nid} cites no requirement"))
            elif ref in known:
                out.entries[ref].workflow.append(nid)
            else:
                unknown(ref, where, f"workflow node {nid}")

    if code is not None and code.decision_list is not None:
        for idx, rule in enumerate(code.decision_list.rules):
            for ref in [x.strip() for x in (rule.ref or "").split(",") if x.strip()]:
                if ref in known:
                    out.entries[ref].code.append(idx)
                else:
                    unknown(ref, rule.location, f"code return at line {rule.location.line}")
            if rule.ref is None and not (isinstance(rule.condition, Const) and rule.condition.value):
                out.issues.append(Issue(code="untraced_rule", blocking=False, location=rule.location,
                                        message=f"code return at line {rule.location.line} has no # ref"))

    # an implicit default counts as implemented when the artifact has a fallback route
    if default_id is not None:
        e = out.entries[default_id]
        if not e.spec and spec is not None and spec.decision_list and spec.decision_list.default_route:
            e.spec.append("default")
        if not e.code and code is not None and code.decision_list is not None:
            dl = code.decision_list
            if dl.default_route not in (None, NO_ROUTE):
                e.code.append(-1)
            else:
                e.code.extend(i for i, r in enumerate(dl.rules)
                              if r.ref is None and isinstance(r.condition, Const) and r.condition.value)

    for r in reqs:
        e = out.entries[r.id]
        for kind, hits, present in (("spec", e.spec, spec is not None),
                                    ("workflow", e.workflow, workflow is not None),
                                    ("code", e.code, code is not None)):
            if present and not hits:
                out.issues.append(Issue(code="unmapped_requirement", blocking=False, location=r.location,
                                        message=f"requirement {r.id} is not referenced by the {kind}"))
    return out
