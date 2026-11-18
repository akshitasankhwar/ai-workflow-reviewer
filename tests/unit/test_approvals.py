"""Approved vs unapproved, revision scope, ordering, conflicts."""
from reviewer.approvals.resolver import resolve
from reviewer.contracts.artifacts import ApprovalsFile
from reviewer.contracts.ir import render


def _appr(id_, value, **kw):
    a = {"id": id_, "status": "approved", "approver": "ops-lead", "applies_to_revision": "r1",
         "changes": [{"requirement": "R3",
                      "set_threshold": {"value": value, "unit": "minutes", "field": "wait_time"}}]}
    a.update(kw)
    return a


def _resolve(doc, *approvals):
    return resolve(doc, ApprovalsFile.model_validate({"approvals": list(approvals)}), "r1", "a1")


def _r3(res):
    return render(res.by_id()["R3"].condition)


def test_approved_change_applies(base_doc):
    res = _resolve(base_doc, _appr("A1", 25))
    assert res.applied == ["A1"] and "25" in _r3(res)
    assert res.decision_list is not None


def test_threshold_unit_is_converted(base_doc):
    a = _appr("A1", 1)
    a["changes"][0]["set_threshold"]["unit"] = "hours"
    assert "60" in _r3(_resolve(base_doc, a))


def test_pending_rejected_withdrawn_are_ignored(base_doc):
    for status in ("pending", "rejected", "withdrawn"):
        res = _resolve(base_doc, _appr("A1", 25, status=status))
        assert res.applied == [] and "30" in _r3(res)
        assert res.ignored[0][0] == "A1"


def test_missing_approver_is_ignored(base_doc):
    res = _resolve(base_doc, _appr("A1", 25, approver=None))
    assert res.applied == [] and "30" in _r3(res)


def test_other_revision_is_ignored(base_doc):
    res = _resolve(base_doc, _appr("A1", 25, applies_to_revision="r0"))
    assert res.applied == [] and "r0" in res.ignored[0][1]


def test_sequenced_approvals_supersede(base_doc):
    res = _resolve(base_doc, _appr("A2", 20, sequence=2), _appr("A1", 25, sequence=1))
    assert res.applied == ["A1", "A2"] and "20" in _r3(res)
    assert not res.conflicts


def test_unordered_disagreement_is_a_conflict(base_doc):
    res = _resolve(base_doc, _appr("A1", 25), _appr("A2", 20))
    assert res.conflicts == ["R3"]
    assert res.decision_list is None
    assert any(i.code == "approval_conflict" and i.blocking for i in res.issues)


def test_agreeing_unordered_approvals_are_fine(base_doc):
    res = _resolve(base_doc, _appr("A1", 25), _appr("A2", 25))
    assert not res.conflicts and "25" in _r3(res)


def test_unknown_target_is_blocking(base_doc):
    a = _appr("A1", 25)
    a["changes"][0]["requirement"] = "R7"
    res = _resolve(base_doc, a)
    assert any(i.code == "unknown_requirement" for i in res.issues) and res.decision_list is None


def test_set_route_and_remove(base_doc):
    a = {"id": "A1", "status": "approved", "approver": "x", "applies_to_revision": "r1",
         "changes": [{"requirement": "R2", "set_route": "escalation"},
                     {"requirement": "R1", "remove": True}]}
    res = _resolve(base_doc, a)
    assert [r.id for r in res.requirements] == ["R2", "R3", "R9"]
    assert res.by_id()["R2"].route == "escalation"


def test_add_requirement(base_doc):
    a = {"id": "A1", "status": "approved", "approver": "x", "applies_to_revision": "r1",
         "changes": [{"requirement": "R4", "add": {
             "id": "R4", "after": "R2",
             "text": "Otherwise, if `category` is `account`, route to `manual_review`."}}]}
    res = _resolve(base_doc, a)
    assert [r.id for r in res.requirements] == ["R1", "R2", "R4", "R3", "R9"]


def test_free_text_is_never_interpreted(base_doc):
    res = _resolve(base_doc, _appr("A1", 25, note="Actually make it 5 minutes."))
    assert "25" in _r3(res)
