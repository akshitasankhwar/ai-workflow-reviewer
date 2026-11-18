"""Regression: a check that raised an exception was once dropped from the report, so the
remaining checks could still produce PASS. A crashed check must be reported as an error
and the overall status must be INCOMPLETE.
"""
from reviewer.checks import REQUIRED
from reviewer.pipeline import review


def test_crashing_required_check_never_passes(bundle_copy, config, monkeypatch):
    def boom(ctx):
        raise RuntimeError("simulated crash")

    monkeypatch.setitem(REQUIRED, "interaction", boom)
    rep = review(bundle_copy, config)
    assert rep.status == "INCOMPLETE"
    assert next(c for c in rep.checks if c.name == "interaction").status == "error"
