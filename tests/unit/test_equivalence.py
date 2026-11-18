""">= vs not(<), 30 min vs 0.5 h are equivalent; > vs >= yields counterexample at 30.
"""
from reviewer.contracts.common import Location
from reviewer.contracts.ir import DecisionList, FieldDecl, IRRule
from reviewer.ingest.spec_compiler import compile_condition_json
from reviewer.semantics.domain import build_domain
from reviewer.semantics.equivalence import compare

FIELDS = {"wait_time": FieldDecl(name="wait_time", type="number", unit="minutes")}


def dl(source, cond):
    loc = Location(artifact=source, version="v", pointer="/")
    rule = IRRule(ref="R3", condition=compile_condition_json(cond, FIELDS), route="escalation",
                  location=loc)
    return DecisionList(source=source, version="v", rules=(rule,), default_route="normal_queue")


def refs(d, route, idx):
    return [d.rules[idx].ref] if idx is not None else []


def run(a, b, config):
    exp, act = dl("requirements", a), dl("spec", b)
    return compare(exp, act, build_domain(FIELDS, [exp, act], config), refs, refs)


def test_present_and_not_less_than_equals_at_least(config):
    c = run({"field": "wait_time", "op": ">=", "value": 30},
            {"all": [{"present": "wait_time"},
                     {"not": {"field": "wait_time", "op": "<", "value": 30}}]}, config)
    assert c.equivalent and c.method == "exhaustive"


def test_bare_not_less_than_differs_when_field_missing(config):
    # a missing value makes every comparison false, so not(<) is true for it
    c = run({"field": "wait_time", "op": ">=", "value": 30},
            {"not": {"field": "wait_time", "op": "<", "value": 30}}, config)
    assert [g.ticket for g in c.groups] == [{}]


def test_half_hour_equals_thirty_minutes(config):
    c = run({"field": "wait_time", "op": ">=", "value": 30},
            {"field": "wait_time", "op": ">=", "value": 0.5, "unit": "hours"}, config)
    assert c.equivalent


def test_strict_vs_non_strict_gives_counterexample_at_boundary(config):
    c = run({"field": "wait_time", "op": ">=", "value": 30},
            {"field": "wait_time", "op": ">", "value": 30}, config)
    assert not c.equivalent
    g = c.groups[0]
    assert g.ticket == {"wait_time": 30}
    assert (g.expected_route, g.actual_route) == ("escalation", "normal_queue")
