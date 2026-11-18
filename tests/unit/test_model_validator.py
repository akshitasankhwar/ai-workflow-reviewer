"""Model failures: timeout, malformed, truncated, invented refs, bad evidence, conflicts,
injection. None of them may produce PASS; a clean answer must."""
import pytest

from reviewer.pipeline import review


def _mr(rep):
    return next(c for c in rep.checks if c.name == "model_review")


@pytest.fixture
def nocache(config):
    config["cache"]["enabled"] = False
    return config


@pytest.mark.parametrize("script,check_status", [
    ("timeout", "error"), ("malformed", "error"), ("truncated", "error"),
    ("invented_ref", "failed"), ("bad_evidence", "failed"), ("conflict", "failed"),
    ("partial", "failed"),
])
def test_model_failures_are_incomplete(bundle_copy, nocache, script, check_status):
    rep = review(bundle_copy, nocache, model="fake", fake_script=script)
    assert rep.status == "INCOMPLETE"
    assert _mr(rep).status == check_status


def test_retries_are_bounded(bundle_copy, nocache):
    rep = review(bundle_copy, nocache, model="fake", fake_script="timeout")
    mc = nocache["model"]
    assert rep.model_usage.calls == min(mc["max_retries"] + 1, mc["max_calls_per_review"])
    assert rep.model_usage.retries == rep.model_usage.calls - 1


def test_retry_recovers(bundle_copy, nocache):
    rep = review(bundle_copy, nocache, model="fake", fake_script="malformed,valid")
    assert rep.status == "PASS" and rep.model_usage.retries == 1
    assert [a["outcome"] for a in rep.model_usage.attempts] == ["malformed", "ok"]


def test_injection_cannot_set_status_or_approval(bundle_copy, nocache):
    rep = review(bundle_copy, nocache, model="fake", fake_script="injected")
    assert rep.status == "PASS"           # same as the deterministic result
    assert "ignored top-level key 'status'" in _mr(rep).detail


def test_model_concern_is_advisory_and_provenanced(bundle_copy, nocache):
    rep = review(bundle_copy, nocache, model="fake", fake_script="concern")
    f = next(f for f in rep.findings if f.origin == "model")
    assert f.severity == "minor" and f.evidence and f.version
    assert rep.status == "PASS"
    u = rep.model_usage
    assert u.prompt_sha256 and u.request["temperature"] == 0.0 and u.response_source == "fake"


def test_model_cannot_rescue_a_defect(bundle_copy, nocache):
    from tests.conftest import read_json, write_json
    p = bundle_copy / "spec.json"
    spec = read_json(p)
    spec["rules"][2]["when"]["value"] = 40
    write_json(p, spec)
    assert review(bundle_copy, nocache, model="fake").status == "CHANGES_REQUIRED"
