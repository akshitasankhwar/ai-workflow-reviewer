"""Supported patterns parse; unsupported lines stay visible."""
from reviewer.contracts.ir import render
from reviewer.ingest.requirements_parser import parse_requirements

from tests.conftest import BASE_REQUIREMENTS


def test_base_document_parses(base_doc):
    assert base_doc.revision == "r1"
    assert [r.id for r in base_doc.requirements] == ["R1", "R2", "R3", "R9"]
    assert not [i for i in base_doc.issues if i.blocking]
    by = base_doc.by_id()
    assert "category" in render(by["R1"].condition)
    assert "urgent" in render(by["R2"].condition)
    assert "30" in render(by["R3"].condition)
    assert by["R9"].is_default and by["R9"].route == "normal_queue"


def test_field_declarations(fields):
    assert set(fields) == {"category", "priority", "wait_time"}
    assert fields["wait_time"].unit == "minutes"


def test_threshold_in_other_unit_is_converted():
    text = BASE_REQUIREMENTS.replace("at least 30 minutes", "at least 1 hours")
    doc = parse_requirements(text, "r1")
    assert "60" in render(doc.by_id()["R3"].condition)


def test_hedged_rule_is_not_silently_parsed():
    text = BASE_REQUIREMENTS.replace("at least 30 minutes", "roughly 30 minutes")
    doc = parse_requirements(text, "r1")
    assert "R3" not in doc.by_id()
    assert any(c.status != "supported" and "R3" in (c.location.excerpt or "") for c in doc.coverage)


def test_unrecognised_sentence_stays_visible():
    text = BASE_REQUIREMENTS + "- [R4] Tickets from VIP customers deserve love.\n"
    doc = parse_requirements(text, "r1")
    assert "R4" not in doc.by_id()
    assert any(c.status != "supported" and "R4" in (c.location.excerpt or "") for c in doc.coverage)


def test_missing_revision_is_reported():
    doc = parse_requirements(BASE_REQUIREMENTS.replace("revision: r1\n", ""), "r1")
    assert doc.revision is None


R3_LINE = "- [R3] Otherwise, if `wait_time` is at least 30 minutes, route to `escalation`."


def _r3(sentence: str):
    doc = parse_requirements(BASE_REQUIREMENTS.replace(R3_LINE, f"- [R3] {sentence}"), "r1")
    assert "R3" in doc.by_id(), [c.reason for c in doc.coverage if c.status != "supported"]
    return doc.by_id()["R3"]


def test_strict_and_inclusive_boundaries_differ():
    assert render(_r3("If `wait_time` is more than 30 minutes, route to `escalation`.").condition) \
        == "wait_time > 30"
    assert render(_r3("If `wait_time` is less than 30 minutes, route to `escalation`.").condition) \
        == "wait_time < 30"
    assert render(_r3("If `wait_time` is at most 30 minutes, route to `escalation`.").condition) \
        == "wait_time <= 30"
    assert render(_r3("If `wait_time` is 30 minutes or more, route to `escalation`.").condition) \
        == "wait_time >= 30"


def test_exactly_is_equality_on_number():
    c = render(_r3("If `wait_time` is exactly 30 minutes, route to `escalation`.").condition)
    assert "wait_time >= 30" in c and "wait_time <= 30" in c


def test_nested_and_or_with_parentheses():
    r = _r3("If (`priority` is `high` or `priority` is `low`) and `wait_time` is at least "
            "30 minutes, route to `escalation`.")
    c = render(r.condition)
    assert "or" in c and "and" in c and c.index("or") < c.index("and")


def test_and_binds_tighter_than_or():
    from reviewer.semantics.evaluator import holds
    r = _r3("If `priority` is `high` or `priority` is `low` and `wait_time` is at least "
            "30 minutes, route to `escalation`.")
    assert holds(r.condition, {"priority": "high", "wait_time": 0})
    assert not holds(r.condition, {"priority": "low", "wait_time": 0})


def test_one_of_and_not():
    r = _r3("If `priority` is one of `high`, `normal` or `low`, route to `escalation`.")
    assert "high" in render(r.condition) and "low" in render(r.condition)
    r = _r3("If `priority` is not `low`, route to `escalation`.")
    assert render(r.condition).startswith("not")


def test_present_is_negated_missing():
    r = _r3("If `category` is present, route to `escalation`.")
    assert render(r.condition) == "not (category is missing)" or "not" in render(r.condition)


def test_unless_excludes_condition():
    from reviewer.semantics.evaluator import holds
    r = _r3("If `wait_time` is at least 30 minutes, route to `escalation`, unless "
            "`priority` is `low`.")
    assert holds(r.condition, {"priority": "high", "wait_time": 40, "category": "billing"})
    assert not holds(r.condition, {"priority": "low", "wait_time": 40, "category": "billing"})


def test_ordered_exceptions_come_before_main_rule():
    from reviewer.approvals.resolver import requirements_to_decision_list
    r = _r3("If `wait_time` is at least 30 minutes, route to `escalation`; except if "
            "`priority` is `low`, route to `normal_queue`.")
    assert [e.route for e in r.exceptions] == ["normal_queue"]
    doc = parse_requirements(BASE_REQUIREMENTS.replace(R3_LINE, f"- [R3] {r.text}"), "r1")
    dl = requirements_to_decision_list(doc.requirements, "r1")
    routes = [x.route for x in dl.rules if x.ref == "R3"]
    assert routes == ["normal_queue", "escalation"]


def test_undeclared_field_and_wrong_unit_are_unsupported():
    for s in ("If `vip` is `true`, route to `escalation`.",
              "If `wait_time` is at least 30 kilograms, route to `escalation`."):
        doc = parse_requirements(BASE_REQUIREMENTS.replace(R3_LINE, f"- [R3] {s}"), "r1")
        assert "R3" not in doc.by_id()
        assert any(c.status == "unsupported" and "R3" in c.reason for c in doc.coverage)
