"""Regression (Stage 4 eval, real): a defect in R3 was reported against R9.

Failing output on bundles/dev/b10_def_unit before the fix (code uses seconds(25)):
    code_equivalence  major  rule_ref=R9  "expected normal_queue, got escalation"
The ticket (wait 25 s..25 min) should fall through to the default R9, but the code's R3 branch
fires too early. The finding blamed the default requirement instead of the faulty rule.
"""
from reviewer.pipeline import review

from tests.conftest import read_json, write_json


def _code(bundle, old, new):
    p = bundle / "code" / "router.py"
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_too_early_escalation_is_blamed_on_r3(bundle_copy, config):
    _code(bundle_copy, "minutes(25)", "seconds(25)")
    rep = review(bundle_copy, config)
    assert rep.status == "CHANGES_REQUIRED"
    blocking = [f for f in rep.findings if f.severity in ("major", "critical")]
    assert blocking and {f.rule_ref for f in blocking} == {"R3"}
    cx = blocking[0].counterexample
    assert (cx.expected_route, cx.actual_route) == ("normal_queue", "escalation")


def test_missed_escalation_still_blamed_on_r3(bundle_copy, config):
    # opposite direction: the expected rule is specific, so it stays the blamed one
    p = bundle_copy / "spec.json"
    spec = read_json(p)
    spec["rules"][2]["when"]["value"] = 30
    write_json(p, spec)
    rep = review(bundle_copy, config)
    assert {f.rule_ref for f in rep.findings if f.severity == "major"} == {"R3"}
