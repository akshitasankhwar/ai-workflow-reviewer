"""Compile spec.json into the shared IR.

Rules are ordered by `priority` (lower first); ties keep array order but are reported,
because a tie makes precedence depend on file layout. Numeric thresholds are converted
to the unit the requirements declare for that field.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from pydantic import ValidationError

from ..contracts.artifacts import Spec
from ..contracts.common import CoverageItem, Issue, Location
from ..contracts.ir import (
    Compare, Cond, DecisionList, Eq, FieldDecl, In, IRRule, Missing, and_, not_, or_,
)
from . import units

_OPS = {"<", "<=", ">", ">=", "==", "!=", "in", "not_in"}


class ConditionError(ValueError):
    pass


def compile_condition_json(c: Any, fields: dict[str, FieldDecl]) -> Cond:
    """ConditionJSON (see contracts.artifacts) -> IR. Raises ConditionError."""
    if not isinstance(c, dict) or not c:
        raise ConditionError(f"condition must be a non-empty object, got {c!r}")
    keys = set(c)
    if keys == {"all"} or keys == {"any"}:
        parts = c.get("all", c.get("any"))
        if not isinstance(parts, list) or not parts:
            raise ConditionError("'all'/'any' needs a non-empty list")
        sub = [compile_condition_json(p, fields) for p in parts]
        return and_(*sub) if "all" in c else or_(*sub)
    if keys == {"not"}:
        return not_(compile_condition_json(c["not"], fields))
    if keys == {"missing"}:
        _field(c["missing"], fields)
        return Missing(field=c["missing"])
    if keys == {"present"}:
        _field(c["present"], fields)
        return not_(Missing(field=c["present"]))
    if "field" in c and "op" in c:
        extra = keys - {"field", "op", "value", "values", "unit"}
        if extra:
            raise ConditionError(f"unknown keys {sorted(extra)}")
        f = _field(c["field"], fields)
        op = c["op"]
        if op not in _OPS:
            raise ConditionError(f"unsupported operator {op!r}")
        if op in ("in", "not_in"):
            vals = c.get("values")
            if not isinstance(vals, list) or not vals:
                raise ConditionError("'in' needs a non-empty 'values' list")
            node = In(field=f.name, values=tuple(_scalar(v, f) for v in vals))
            return not_(node) if op == "not_in" else node
        if "value" not in c:
            raise ConditionError(f"operator {op!r} needs 'value'")
        if op in ("==", "!="):
            node = Eq(field=f.name, value=_scalar(c["value"], f))
            return not_(node) if op == "!=" else node
        if f.type != "number":
            raise ConditionError(f"numeric operator on non-numeric field {f.name!r}")
        v = c["value"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ConditionError(f"threshold for {f.name!r} must be a number")
        try:
            v = units.convert(v, c.get("unit"), f.unit)
        except units.UnitError as e:
            raise ConditionError(str(e)) from e
        return Compare(field=f.name, op=op, value=v)
    raise ConditionError(f"unrecognised condition shape {sorted(keys)}")


def _field(name: Any, fields: dict[str, FieldDecl]) -> FieldDecl:
    if not isinstance(name, str):
        raise ConditionError(f"field name must be a string, got {name!r}")
    if name not in fields:
        raise ConditionError(f"field {name!r} is not declared in the requirements")
    return fields[name]


def _scalar(v: Any, f: FieldDecl):
    if f.type == "enum" and v not in f.values:
        raise ConditionError(f"{v!r} is not a declared value of {f.name!r}")
    if f.type == "bool" and not isinstance(v, bool):
        raise ConditionError(f"{f.name!r} is bool, got {v!r}")
    if f.type == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
        raise ConditionError(f"{f.name!r} is numeric, got {v!r}")
    return float(v) if f.type == "number" else v


@dataclass
class CompiledSpec:
    decision_list: DecisionList | None
    spec: Spec | None
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    issues: list[Issue] = dc_field(default_factory=list)
    source_refs: dict[str, list[str]] = dc_field(default_factory=dict)  # rule id -> refs


def compile_spec(data: Any, version: str, fields: dict[str, FieldDecl]) -> CompiledSpec:
    def loc(ptr: str, excerpt: str | None = None) -> Location:
        return Location(artifact="spec", version=version, pointer=ptr, excerpt=excerpt)

    try:
        spec = Spec.model_validate(data)
    except ValidationError as e:
        return CompiledSpec(None, None, issues=[Issue(
            code="spec_schema", blocking=True, location=loc("/"),
            message=f"spec.json does not match the schema: {e.errors()[0]['msg']} at "
                    f"{'/'.join(map(str, e.errors()[0]['loc']))}")])

    out = CompiledSpec(None, spec)
    if spec.spec_version != version:
        out.issues.append(Issue(code="version_mismatch", blocking=True, location=loc("/spec_version"),
                                message=f"spec_version {spec.spec_version} != manifest {version}"))
    for extra in sorted((spec.model_extra or {}).keys()):
        out.coverage.append(CoverageItem(location=loc(f"/{extra}"), status="ignored",
                                         reason="unknown top-level key; not interpreted"))

    ids = [r.id for r in spec.rules]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        out.issues.append(Issue(code="duplicate_rule_id", blocking=True, location=loc("/rules"),
                                message=f"spec rule id {dup} appears more than once"))

    indexed = sorted(enumerate(spec.rules), key=lambda p: (p[1].priority, p[0]))
    prios = [r.priority for r in spec.rules]
    for p in sorted({p for p in prios if prios.count(p) > 1}):
        out.issues.append(Issue(code="priority_tie", blocking=False, location=loc("/rules"),
                                message=f"several spec rules share priority {p}; precedence is undefined"))

    rules: list[IRRule] = []
    ok = True
    for idx, r in indexed:
        ptr = f"/rules/{idx}"
        try:
            cond = compile_condition_json(r.when, fields)
        except ConditionError as e:
            ok = False
            out.coverage.append(CoverageItem(location=loc(ptr, r.id), status="unsupported",
                                             reason=f"rule {r.id}: {e}"))
            continue
        for extra in sorted((r.model_extra or {}).keys()):
            out.coverage.append(CoverageItem(location=loc(f"{ptr}/{extra}", r.id), status="ignored",
                                             reason=f"rule {r.id}: unknown key not interpreted"))
        out.coverage.append(CoverageItem(location=loc(ptr, r.id), status="supported",
                                         reason=f"rule {r.id} compiled"))
        out.source_refs[r.id] = list(r.source_refs)
        rules.append(IRRule(ref=r.id, condition=cond, route=r.route, location=loc(ptr, r.id)))

    default_route = spec.default.route if spec.default else None
    if spec.default:
        out.source_refs["default"] = list(spec.default.source_refs)
        out.coverage.append(CoverageItem(location=loc("/default"), status="supported",
                                         reason="default route"))
    if ok:
        out.decision_list = DecisionList(source="spec", version=version, rules=tuple(rules),
                                         default_route=default_route,
                                         default_location=loc("/default") if spec.default else None)
    return out
