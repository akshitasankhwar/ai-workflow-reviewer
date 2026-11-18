"""Regression: `not (wait_time < 25)` was once treated as `wait_time >= 25`.

A comparison on a missing field is false, so the negation is true for a ticket without
wait_time. A spec written that way escalates such tickets; the reviewer must report it
with a counterexample that has no wait_time, and accept the form once `present` is added.
"""
from reviewer.pipeline import review

from tests.conftest import read_json, write_json


def _set_s3(bundle, cond):
    p = bundle / "spec.json"
    spec = read_json(p)
    spec["rules"][2]["when"] = cond
    write_json(p, spec)


NEG = {"not": {"field": "wait_time", "op": "<", "value": 25}}


def test_bare_negation_is_a_mismatch_on_missing_wait_time(bundle_copy, config):
    _set_s3(bundle_copy, NEG)
    rep = review(bundle_copy, config)
    assert rep.status == "CHANGES_REQUIRED"
    cx = next(f.counterexample for f in rep.findings
              if f.check == "spec_equivalence" and f.counterexample is not None)
    assert "wait_time" not in cx.ticket
    assert (cx.expected_route, cx.actual_route) == ("normal_queue", "escalation")


def test_negation_with_present_is_equivalent(bundle_copy, config):
    _set_s3(bundle_copy, {"all": [{"present": "wait_time"}, NEG]})
    assert review(bundle_copy, config).status == "PASS"
