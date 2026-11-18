"""Shared intermediate representation every artifact compiles into.

A routing policy is an ordered decision list: the first rule whose condition holds
decides the route, otherwise the default route applies.

Missing-value semantics: a field is missing when its key is absent or its value is None.
For a field predicate on a missing value:
  * `on_missing="false"`  -> the predicate is False (spec, workflow, requirements);
  * `on_missing="error"`  -> evaluation fails, as Python would raise (code only);
  * `default` set         -> the default value is used instead.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from .common import ArtifactKind, Location, Strict

Scalar = Union[bool, int, float, str]
OnMissing = Literal["false", "error"]

ERROR_ROUTE = "__error__"
NO_ROUTE = "__none__"


class Const(Strict):
    kind: Literal["const"] = "const"
    value: bool


class Missing(Strict):
    kind: Literal["missing"] = "missing"
    field: str
    on_missing: OnMissing = "false"


class Compare(Strict):
    kind: Literal["cmp"] = "cmp"
    field: str
    op: Literal["<", "<=", ">", ">="]
    value: float
    on_missing: OnMissing = "false"
    default: float | None = None


class Eq(Strict):
    kind: Literal["eq"] = "eq"
    field: str
    value: Scalar
    on_missing: OnMissing = "false"
    default: Scalar | None = None


class In(Strict):
    kind: Literal["in"] = "in"
    field: str
    values: tuple[Scalar, ...]
    on_missing: OnMissing = "false"
    default: Scalar | None = None


class And(Strict):
    kind: Literal["and"] = "and"
    args: tuple["Cond", ...]


class Or(Strict):
    kind: Literal["or"] = "or"
    args: tuple["Cond", ...]


class Not(Strict):
    kind: Literal["not"] = "not"
    arg: "Cond"


Cond = Annotated[Union[Const, Missing, Compare, Eq, In, And, Or, Not], Field(discriminator="kind")]

TRUE = Const(value=True)
FALSE = Const(value=False)

for _m in (And, Or, Not):
    _m.model_rebuild()


class FieldDecl(Strict):
    name: str
    type: Literal["number", "enum", "bool", "string"]
    unit: str | None = None
    values: tuple[Scalar, ...] = ()


class IRRule(Strict):
    ref: str | None
    condition: Cond
    route: str
    location: Location


class DecisionList(Strict):
    source: ArtifactKind
    version: str
    rules: tuple[IRRule, ...]
    default_route: str | None
    default_location: Location | None = None


# ---- smart constructors (constant folding keeps compiled conditions small) ----

def and_(*args: Cond) -> Cond:
    flat: list[Cond] = []
    for a in args:
        if isinstance(a, Const):
            if not a.value:
                return FALSE
            continue
        flat.extend(a.args if isinstance(a, And) else (a,))
    if not flat:
        return TRUE
    return flat[0] if len(flat) == 1 else And(args=tuple(flat))


def or_(*args: Cond) -> Cond:
    flat: list[Cond] = []
    for a in args:
        if isinstance(a, Const):
            if a.value:
                return TRUE
            continue
        flat.extend(a.args if isinstance(a, Or) else (a,))
    if not flat:
        return FALSE
    return flat[0] if len(flat) == 1 else Or(args=tuple(flat))


def not_(arg: Cond) -> Cond:
    if isinstance(arg, Const):
        return Const(value=not arg.value)
    if isinstance(arg, Not):
        return arg.arg
    return Not(arg=arg)


def walk(cond: Cond):
    """Yield every node of a condition tree."""
    yield cond
    if isinstance(cond, (And, Or)):
        for a in cond.args:
            yield from walk(a)
    elif isinstance(cond, Not):
        yield from walk(cond.arg)


def render(cond: Cond) -> str:
    """Human-readable form used in findings and explanations."""
    if isinstance(cond, Const):
        return "true" if cond.value else "false"
    if isinstance(cond, Missing):
        return f"{cond.field} is missing"
    if isinstance(cond, Compare):
        return f"{cond.field} {cond.op} {cond.value:g}"
    if isinstance(cond, Eq):
        return f"{cond.field} == {cond.value!r}"
    if isinstance(cond, In):
        return f"{cond.field} in {list(cond.values)!r}"
    if isinstance(cond, Not):
        return f"not ({render(cond.arg)})"
    joiner = " and " if isinstance(cond, And) else " or "
    return "(" + joiner.join(render(a) for a in cond.args) + ")"
