"""workflow.json graph -> IR.

Enumerates every path from `start` to a route node, conjoining the branch conditions
(true edge: C, false edge: not C). Paths of a tree are mutually exclusive, so the
resulting decision list is order-independent. Reports dangling edges, cycles,
unreachable nodes, malformed nodes, and path explosion (never silently truncated).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from pydantic import ValidationError

from ..contracts.artifacts import Workflow, WorkflowNode
from ..contracts.common import CoverageItem, Issue, Location
from ..contracts.ir import Cond, DecisionList, FieldDecl, IRRule, TRUE, and_, not_
from .spec_compiler import ConditionError, compile_condition_json

MAX_PATHS = 4096


@dataclass
class CompiledWorkflow:
    decision_list: DecisionList | None
    workflow: Workflow | None
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    issues: list[Issue] = dc_field(default_factory=list)
    rule_refs: dict[str, str | None] = dc_field(default_factory=dict)  # route node id -> rule_ref


def compile_workflow(data: Any, version: str, fields: dict[str, FieldDecl],
                     max_paths: int = MAX_PATHS) -> CompiledWorkflow:
    def loc(node_id: str | None, excerpt: str | None = None) -> Location:
        return Location(artifact="workflow", version=version,
                        pointer=f"node:{node_id}" if node_id else "/", excerpt=excerpt)

    try:
        wf = Workflow.model_validate(data)
    except ValidationError as e:
        err = e.errors()[0]
        return CompiledWorkflow(None, None, issues=[Issue(
            code="workflow_schema", blocking=True, location=loc(None),
            message=f"workflow.json does not match the schema: {err['msg']} at "
                    f"{'/'.join(map(str, err['loc']))}")])

    out = CompiledWorkflow(None, wf)
    if wf.workflow_version != version:
        out.issues.append(Issue(code="version_mismatch", blocking=True, location=loc(None),
                                message=f"workflow_version {wf.workflow_version} != manifest {version}"))

    nodes: dict[str, WorkflowNode] = {}
    for n in wf.nodes:
        if n.id in nodes:
            out.issues.append(Issue(code="duplicate_node_id", blocking=True, location=loc(n.id),
                                    message=f"workflow node id {n.id} appears more than once"))
        nodes[n.id] = n

    conds: dict[str, Cond] = {}
    broken = False
    for n in wf.nodes:
        if n.type == "decision":
            if n.condition is None or n.on_true is None or n.on_false is None:
                broken = True
                out.issues.append(Issue(
                    code="incomplete_decision", blocking=True, location=loc(n.id),
                    message=f"decision node {n.id} needs condition, on_true and on_false"))
                continue
            try:
                conds[n.id] = compile_condition_json(n.condition, fields)
                out.coverage.append(CoverageItem(location=loc(n.id), status="supported",
                                                 reason=f"decision {n.id} compiled"))
            except ConditionError as e:
                broken = True
                out.coverage.append(CoverageItem(location=loc(n.id), status="unsupported",
                                                 reason=f"decision {n.id}: {e}"))
            for edge in (n.on_true, n.on_false):
                if edge not in nodes:
                    broken = True
                    out.issues.append(Issue(code="dangling_edge", blocking=True, location=loc(n.id),
                                            message=f"node {n.id} points to unknown node {edge!r}"))
        else:
            if not n.route:
                broken = True
                out.issues.append(Issue(code="route_without_target", blocking=True,
                                        location=loc(n.id),
                                        message=f"route node {n.id} has no route"))
            else:
                out.coverage.append(CoverageItem(location=loc(n.id), status="supported",
                                                 reason=f"route node {n.id}"))
            out.rule_refs[n.id] = n.rule_ref
        for extra in sorted((n.model_extra or {}).keys()):
            out.coverage.append(CoverageItem(location=loc(n.id), status="ignored",
                                             reason=f"node {n.id}: unknown key {extra!r} not interpreted"))

    if wf.start not in nodes:
        out.issues.append(Issue(code="dangling_start", blocking=True, location=loc(None),
                                message=f"start node {wf.start!r} does not exist"))
        return out

    rules: list[IRRule] = []
    visited: set[str] = set()
    exploded = False

    def dfs(node_id: str, path_cond: Cond, stack: tuple[str, ...]) -> None:
        nonlocal broken, exploded
        if exploded or node_id not in nodes:
            return
        if node_id in stack:
            broken = True
            out.issues.append(Issue(code="cycle", blocking=True, location=loc(node_id),
                                    message="cycle: " + " -> ".join(stack + (node_id,))))
            return
        visited.add(node_id)
        n = nodes[node_id]
        if n.type == "route":
            if len(rules) >= max_paths:
                exploded = True
                return
            if n.route:
                rules.append(IRRule(ref=n.rule_ref, condition=path_cond, route=n.route,
                                    location=loc(n.id, " -> ".join(stack + (node_id,)))))
            return
        c = conds.get(node_id)
        if c is None:
            return
        dfs(n.on_true, and_(path_cond, c), stack + (node_id,))
        dfs(n.on_false, and_(path_cond, not_(c)), stack + (node_id,))

    dfs(wf.start, TRUE, ())
    if exploded:
        broken = True
        out.issues.append(Issue(code="path_explosion", blocking=True, location=loc(None),
                                message=f"more than {max_paths} paths; workflow not fully enumerated"))
    for nid in nodes:
        if nid not in visited:
            out.issues.append(Issue(code="unreachable_node", blocking=False, location=loc(nid),
                                    message=f"node {nid} is not reachable from {wf.start}"))
    if not broken:
        out.decision_list = DecisionList(source="workflow", version=version, rules=tuple(rules),
                                         default_route=None)
    return out
