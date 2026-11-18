"""Approvals -> effective requirements.

Only structured `changes` of approvals that are `approved`, have an approver and apply to
the current requirements revision take effect. Free-text fields are never interpreted.

Order: by `sequence` (approvals without one sort last), then `decided_at`, then id.
Two applicable approvals that set the same attribute of the same requirement to different
values are a conflict, unless every approval involved carries a distinct `sequence`
(then the later one deliberately supersedes the earlier). A conflict leaves the
requirement unresolved and the effective decision list undefined: the reviewer must not
guess which approval wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ..contracts.artifacts import AddRequirement, Approval, ApprovalsFile, Change, Requirement
from ..contracts.common import CoverageItem, Issue, Location
from ..contracts.ir import (
    And, Compare, Cond, DecisionList, FieldDecl, IRRule, Not, Or, TRUE, and_, walk,
)
from ..ingest import units
from ..ingest.requirements_parser import ParseError, RequirementsDoc, _parse_rule


@dataclass
class ResolvedRequirements:
    requirements: list[Requirement]
    applied: list[str] = dc_field(default_factory=list)
    ignored: list[tuple[str, str]] = dc_field(default_factory=list)  # (approval id, reason)
    conflicts: list[str] = dc_field(default_factory=list)  # requirement ids
    unresolved: list[str] = dc_field(default_factory=list)
    issues: list[Issue] = dc_field(default_factory=list)
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    decision_list: DecisionList | None = None

    def by_id(self) -> dict[str, Requirement]:
        return {r.id: r for r in self.requirements}


def _order_key(a: Approval):
    return (a.sequence is None, a.sequence or 0, a.decided_at or "", a.id)


def _change_keys(c: Change) -> list[tuple[tuple[str, str], object]]:
    """(requirement, attribute) -> value set by this change."""
    out: list[tuple[tuple[str, str], object]] = []
    if c.set_threshold is not None:
        t = c.set_threshold
        out.append(((c.requirement, f"threshold:{t.field or '*'}"), (t.value, t.unit)))
    if c.set_route is not None:
        out.append(((c.requirement, "route"), c.set_route))
    if c.remove:
        out.append(((c.requirement, "remove"), True))
    if c.add is not None:
        out.append(((c.add.id, "add"), (c.add.text, c.add.after)))
    return out


def _map_compare(cond: Cond, fn) -> Cond:
    if isinstance(cond, Compare):
        return fn(cond)
    if isinstance(cond, And):
        return And(args=tuple(_map_compare(a, fn) for a in cond.args))
    if isinstance(cond, Or):
        return Or(args=tuple(_map_compare(a, fn) for a in cond.args))
    if isinstance(cond, Not):
        return Not(arg=_map_compare(cond.arg, fn))
    return cond


def _compare_fields(r: Requirement) -> set[str]:
    conds = [r.condition] if r.condition is not None else []
    conds += [e.condition for e in r.exceptions]
    return {n.field for c in conds for n in walk(c) if isinstance(n, Compare)}


def resolve(doc: RequirementsDoc, approvals_file: ApprovalsFile | None,
            revision: str | None, approvals_version: str = "?") -> ResolvedRequirements:
    out = ResolvedRequirements(requirements=list(doc.requirements))
    fields = doc.fields

    def loc(i: int, j: int | None = None) -> Location:
        ptr = f"/approvals/{i}" + (f"/changes/{j}" if j is not None else "")
        return Location(artifact="approvals", version=approvals_version, pointer=ptr)

    approvals = list(approvals_file.approvals) if approvals_file else []
    index = {id(a): i for i, a in enumerate(approvals)}

    applicable: list[Approval] = []
    for i, a in enumerate(approvals):
        reason = None
        if a.status != "approved":
            reason = f"status is {a.status}"
        elif not a.approver:
            reason = "no approver recorded"
        elif a.applies_to_revision != revision:
            reason = f"applies to revision {a.applies_to_revision}, requirements are at {revision}"
        if reason:
            out.ignored.append((a.id, reason))
            out.coverage.append(CoverageItem(location=loc(i), status="ignored",
                                             reason=f"approval {a.id}: {reason}"))
        else:
            applicable.append(a)
    applicable.sort(key=_order_key)

    ids = [a.id for a in approvals]
    for dup in sorted({x for x in ids if ids.count(x) > 1}):
        out.issues.append(Issue(code="duplicate_approval_id", blocking=True, location=loc(ids.index(dup)),
                                message=f"approval id {dup} appears more than once"))

    # ---- conflict detection over (requirement, attribute)
    touched: dict[tuple[str, str], list[tuple[Approval, object]]] = {}
    for a in applicable:
        for c in a.changes:
            for key, value in _change_keys(c):
                touched.setdefault(key, []).append((a, value))
    conflicted: set[str] = set()
    for (rid, attr), entries in sorted(touched.items()):
        if len({repr(v) for _, v in entries}) <= 1:
            continue
        seqs = [a.sequence for a, _ in entries]
        if all(s is not None for s in seqs) and len(set(seqs)) == len(seqs):
            continue  # explicitly sequenced: later supersedes earlier
        conflicted.add(rid)
        who = ", ".join(a.id for a, _ in entries)
        out.issues.append(Issue(
            code="approval_conflict", blocking=True, location=loc(index[id(entries[0][0])]),
            message=f"approvals {who} set {attr} of {rid} to different values with no "
                    f"explicit ordering; effective requirement is undefined"))
    out.conflicts = sorted(conflicted)

    # ---- apply in order
    reqs = out.requirements
    failed: set[str] = set(conflicted)
    for a in applicable:
        i = index[id(a)]
        for j, c in enumerate(a.changes):
            target = c.add.id if c.add is not None and c.requirement == c.add.id else c.requirement
            if target in conflicted:
                continue
            err = _apply(reqs, c, fields, loc(i, j), a.id)
            if err is not None:
                failed.add(target)
                out.issues.append(err)
        out.applied.append(a.id)
        out.coverage.append(CoverageItem(location=loc(i), status="supported",
                                         reason=f"approval {a.id} applied ({len(a.changes)} change(s))"))

    out.requirements = [r.model_copy(update={"order": k}) for k, r in enumerate(reqs)]
    out.unresolved = sorted(failed)
    if not out.unresolved and not any(i.blocking for i in out.issues):
        out.decision_list = requirements_to_decision_list(out.requirements, doc.version)
    return out


def _apply(reqs: list[Requirement], c: Change, fields: dict[str, FieldDecl],
           where: Location, aid: str) -> Issue | None:
    def fail(code: str, msg: str) -> Issue:
        return Issue(code=code, blocking=True, location=where, message=f"approval {aid}: {msg}")

    if c.add is not None:
        return _add(reqs, c.add, fields, where, aid, fail)

    pos = next((k for k, r in enumerate(reqs) if r.id == c.requirement), None)
    if pos is None:
        return fail("unknown_requirement", f"targets {c.requirement}, which does not exist")
    r = reqs[pos]
    if c.remove:
        del reqs[pos]
        return None
    if c.set_route is not None:
        r = r.model_copy(update={"route": c.set_route})
    if c.set_threshold is not None:
        t = c.set_threshold
        candidates = _compare_fields(r)
        if t.field is not None:
            if t.field not in candidates:
                return fail("threshold_target_missing",
                            f"{c.requirement} has no numeric comparison on {t.field!r}")
            fname = t.field
        elif len(candidates) == 1:
            fname = next(iter(candidates))
        elif not candidates:
            return fail("threshold_target_missing", f"{c.requirement} has no numeric threshold")
        else:
            return fail("ambiguous_threshold",
                        f"{c.requirement} compares {sorted(candidates)}; the approval names no field")
        try:
            value = units.convert(t.value, t.unit, fields[fname].unit if fname in fields else None)
        except units.UnitError as e:
            return fail("threshold_unit", str(e))

        def fn(node: Compare) -> Compare:
            return node.model_copy(update={"value": value}) if node.field == fname else node

        r = r.model_copy(update={
            "condition": _map_compare(r.condition, fn) if r.condition is not None else None,
            "exceptions": tuple(e.model_copy(update={"condition": _map_compare(e.condition, fn)})
                                for e in r.exceptions),
        })
    reqs[pos] = r
    return None


def _add(reqs: list[Requirement], add: AddRequirement, fields, where: Location, aid: str, fail):
    if any(r.id == add.id for r in reqs):
        return fail("duplicate_requirement_id", f"adds {add.id}, which already exists")
    try:
        cond, route, exceptions, is_default = _parse_rule(add.id, add.text, fields)
    except (ParseError, units.UnitError) as e:
        return fail("unparseable_added_requirement", f"added requirement {add.id}: {e}")
    if add.after is None:
        pos = 0
    else:
        k = next((k for k, r in enumerate(reqs) if r.id == add.after), None)
        if k is None:
            return fail("unknown_requirement", f"inserts after {add.after}, which does not exist")
        pos = k + 1
    reqs.insert(pos, Requirement(id=add.id, order=pos, text=add.text, condition=cond, route=route,
                                 is_default=is_default, exceptions=exceptions,
                                 location=where.model_copy(update={"excerpt": add.text[:200]})))
    return None


def requirements_to_decision_list(reqs: list[Requirement], version: str) -> DecisionList:
    rules: list[IRRule] = []
    default_route = None
    default_location = None
    for k, r in enumerate(reqs):
        if r.is_default:
            if k == len(reqs) - 1:
                default_route, default_location = r.route, r.location
            else:
                rules.append(IRRule(ref=r.id, condition=TRUE, route=r.route, location=r.location))
            continue
        assert r.condition is not None
        for e in r.exceptions:
            rules.append(IRRule(ref=r.id, condition=and_(r.condition, e.condition), route=e.route,
                                location=r.location))
        rules.append(IRRule(ref=r.id, condition=r.condition, route=r.route, location=r.location))
    return DecisionList(source="requirements", version=version, rules=tuple(rules),
                        default_route=default_route, default_location=default_location)
