"""Status rules; a crashed required check never yields PASS.
"""
from reviewer.checks.base import run_check
from reviewer.contracts.common import Location
from reviewer.contracts.report import CheckResult, Finding
from reviewer.decision import decide_status

REQ = ["a", "b"]
LOC = Location(artifact="spec", version="s1", pointer="/rules/0")


def ok(name):
    return CheckResult(name=name, status="passed", method="exhaustive", detail="")


def finding(severity="major", origin="deterministic", evidence=True):
    return Finding(id="F001", check="a", severity=severity, rule_ref="R1", artifact="spec",
                   version="s1", location="/rules/0", evidence=[LOC] if evidence else [],
                   message="m", correction="c", origin=origin)


def status(checks, findings=(), **kw):
    args = dict(coverage=[], incomplete_reasons=[], issues=[], has_effective=True, required=REQ)
    args.update(kw)
    return decide_status(checks, list(findings), **args)[0]


def test_all_passed_is_pass():
    assert status([ok("a"), ok("b")]) == "PASS"


def test_evidenced_major_is_changes_required():
    assert status([ok("a"), ok("b")], [finding()]) == "CHANGES_REQUIRED"


def test_minor_or_unevidenced_or_model_findings_do_not_block():
    fs = [finding("minor"), finding(evidence=False), finding(origin="model")]
    assert status([ok("a"), ok("b")], fs) == "PASS"


def test_crashed_required_check_is_never_pass():
    def boom(ctx):
        raise RuntimeError("bug")
    res, fs = run_check("b", boom, ctx=None)
    assert res.status == "error"
    assert status([ok("a"), res], fs) == "INCOMPLETE"


def test_disabled_or_missing_required_check_is_incomplete():
    skipped = CheckResult(name="b", status="skipped", method="none", detail="disabled")
    assert status([ok("a"), skipped]) == "INCOMPLETE"
    assert status([ok("a")]) == "INCOMPLETE"


def test_no_effective_requirements_is_incomplete():
    assert status([ok("a"), ok("b")], has_effective=False) == "INCOMPLETE"
