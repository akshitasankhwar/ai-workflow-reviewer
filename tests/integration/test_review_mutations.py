"""One artifact of the base bundle is changed at a time. Real behaviour changes must give
CHANGES_REQUIRED with a concrete counterexample; equivalent rewrites must still PASS.
The effective R3 threshold is 25 minutes (approval A1 changes it from 30).
"""
import pytest

from reviewer.decision import BLOCKING_SEVERITIES
from reviewer.pipeline import review

from tests.conftest import read_json, write_json


def mutate(bundle, name, fn):
    path = bundle / name
    data = read_json(path)
    fn(data)
    write_json(path, data)


def node(wf, nid):
    return next(n for n in wf["nodes"] if n["id"] == nid)


def blockers(rep):
    return [f for f in rep.findings if f.severity in BLOCKING_SEVERITIES]


def test_base_bundle_passes(bundle_copy, config):
    rep = review(bundle_copy, config)
    assert rep.status == "PASS", rep.summary
    assert all(c.status == "passed" for c in rep.checks)
    assert {c.method for c in rep.checks if c.name.endswith("_equivalence")} == {"exhaustive"}


def _spec_threshold_30(s):
    s["rules"][2]["when"]["value"] = 30


def _spec_strict(s):
    s["rules"][2]["when"]["op"] = ">"


def _spec_swap_s2_s3(s):
    s["rules"][1]["priority"], s["rules"][2]["priority"] = 3, 2


def _spec_drop_s2(s):
    del s["rules"][1]


def _wf_redirect(w):
    node(w, "is_urgent")["on_true"] = "to_escalation"


@pytest.mark.parametrize("artifact,fn,kind,ticket_check", [
    ("spec.json", _spec_threshold_30, "changed_threshold",
     lambda t: 25 <= t["wait_time"] < 30),
    ("spec.json", _spec_strict, "boundary", lambda t: t["wait_time"] == 25),
    ("spec.json", _spec_swap_s2_s3, "wrong_precedence",
     lambda t: t["priority"] == "urgent" and t["wait_time"] >= 25),
    ("spec.json", _spec_drop_s2, "omitted_rule", lambda t: t["priority"] == "urgent"),
    ("workflow.json", _wf_redirect, None, lambda t: t["priority"] == "urgent"),
])
def test_behaviour_change_is_caught_with_counterexample(bundle_copy, config, artifact, fn, kind,
                                                        ticket_check):
    mutate(bundle_copy, artifact, fn)
    rep = review(bundle_copy, config)
    assert rep.status == "CHANGES_REQUIRED", rep.summary
    bad = [f for f in blockers(rep) if f.counterexample is not None]
    assert bad, [f.message for f in rep.findings]
    cx = bad[0].counterexample
    assert cx.expected_route != cx.actual_route
    assert ticket_check(cx.ticket), cx.ticket
    if kind:
        assert any(kind.replace("_", " ") in f.message or kind in f.message for f in bad), \
            [f.message for f in bad]


def test_code_with_correct_ref_but_wrong_route(bundle_copy, config):
    p = bundle_copy / "code" / "router.py"
    src = p.read_text(encoding="utf-8")
    p.write_text(src.replace('return "priority_queue"', 'return "escalation"'), encoding="utf-8")
    rep = review(bundle_copy, config)
    assert rep.status == "CHANGES_REQUIRED"
    f = next(f for f in blockers(rep) if f.check == "code_equivalence")
    assert f.rule_ref == "R2" and f.counterexample.ticket["priority"] == "urgent"
    assert f.counterexample.actual_route == "escalation"


def _spec_reordered(s):
    s["rules"].reverse()            # list order changes, priorities still decide


def _spec_seconds(s):
    s["rules"][2]["when"].update(value=1500, unit="seconds")


def _wf_renamed(w):
    ren = {n["id"]: f"n_{i}" for i, n in enumerate(w["nodes"])}
    w["start"] = ren[w["start"]]
    for n in w["nodes"]:
        n["id"] = ren[n["id"]]
        for k in ("on_true", "on_false"):
            if k in n:
                n[k] = ren[n[k]]


def _wf_present(w):
    n = node(w, "has_category")
    n["condition"] = {"present": "category"}
    n["on_true"], n["on_false"] = n["on_false"], n["on_true"]


@pytest.mark.parametrize("artifact,fn", [
    ("spec.json", _spec_reordered), ("spec.json", _spec_seconds),
    ("workflow.json", _wf_renamed), ("workflow.json", _wf_present),
])
def test_equivalent_rewrite_still_passes(bundle_copy, config, artifact, fn):
    mutate(bundle_copy, artifact, fn)
    rep = review(bundle_copy, config)
    assert rep.status == "PASS", (rep.summary, [f.message for f in rep.findings])


def test_disabled_required_check_is_incomplete(bundle_copy, config):
    rep = review(bundle_copy, config, disable=("code_equivalence",))
    assert rep.status == "INCOMPLETE"
    assert any("code_equivalence" in u for u in rep.unreviewed_scope)


def test_report_is_deterministic(bundle_copy, config):
    mutate(bundle_copy, "spec.json", _spec_threshold_30)
    a, b = review(bundle_copy, config), review(bundle_copy, config)
    assert a.model_dump() == b.model_dump()
