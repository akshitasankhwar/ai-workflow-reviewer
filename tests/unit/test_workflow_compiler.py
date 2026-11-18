"""Workflow graphs compile to decision lists; malformed graphs are reported."""
import copy

from reviewer.ingest.workflow_compiler import compile_workflow
from reviewer.semantics.evaluator import decide

from tests.conftest import BASE_BUNDLE, read_json

BASE_WF = read_json(BASE_BUNDLE / "workflow.json")


def _node(wf, nid):
    return next(n for n in wf["nodes"] if n["id"] == nid)


def test_base_workflow(fields):
    cw = compile_workflow(copy.deepcopy(BASE_WF), "w1", fields)
    assert cw.decision_list is not None and not [i for i in cw.issues if i.blocking]
    t = {"category": "billing", "priority": "low", "wait_time": 25}
    assert decide(cw.decision_list, t)[0] == "escalation"
    assert decide(cw.decision_list, {"priority": "urgent"})[0] == "manual_review"
    assert set(cw.rule_refs.values()) == {"R1", "R2", "R3", "R9"}


def test_dangling_edge_is_blocking(fields):
    wf = copy.deepcopy(BASE_WF)
    _node(wf, "is_urgent")["on_true"] = "nowhere"
    assert any(i.blocking for i in compile_workflow(wf, "w1", fields).issues)


def test_cycle_is_blocking(fields):
    wf = copy.deepcopy(BASE_WF)
    _node(wf, "waited_long")["on_false"] = "has_category"
    assert any(i.blocking for i in compile_workflow(wf, "w1", fields).issues)


def test_unreachable_node_is_reported(fields):
    wf = copy.deepcopy(BASE_WF)
    wf["nodes"].append({"id": "orphan", "type": "route", "route": "manual_review", "rule_ref": "R1"})
    cw = compile_workflow(wf, "w1", fields)
    assert any("orphan" in (i.location.pointer or "") or "orphan" in i.message for i in cw.issues)
