"""Parse requirements.md (controlled English) into anchored, structured requirements.

Document layout
---------------
    revision: r1
    ## Fields
    - `category` (enum: billing, technical, account)
    - `wait_time` (number, minutes)
    - `vip` (bool)
    ## Rules
    - [R1] If `category` is missing, route to `manual_review`.
    - [R2] Otherwise, if `priority` is `urgent`, route to `priority_queue`.
    - [R3] Otherwise, if `wait_time` is at least 30 minutes, route to `escalation`.
    - [R9] Otherwise, route to `normal_queue`.

Rule order in the Rules section is precedence. Field names and values are backticked.

Supported sentence patterns
---------------------------
    If|When <cond>, [then] route|send|assign [it|the ticket] to `X`.
        [, unless <cond>]                       -> rule applies only when <cond> is false
        [; except if|when <cond>, route to `Y`]  -> ordered exceptions, checked first
    [Otherwise,] route [all other tickets|everything else] to `X`.   -> default

Conditions: `and` binds tighter than `or`; parentheses group; `not` negates.
    `f` is missing | is absent | is not set
    `f` is present | is set | is provided | is not missing
    `f` is `v` | equals `v` | is not `v`
    `f` is one of `a`, `b` or `c` | is not one of ...
    `f` is at least N [unit] | is N [unit] or more | reaches N      ->  >=
    `f` is at most N [unit]  | is N [unit] or less                  ->  <=
    `f` is more than / greater than / over / above N | exceeds N    ->  >
    `f` is less than / fewer than / under / below N                 ->  <
    `f` is exactly N [unit]
    `f` is true | is false        (bool fields)
Units: seconds, minutes, hours, days (and short forms), converted to the field's unit.

Anything else in the Rules section is reported as unsupported; hedged wording
(about, around, roughly, soon, ...) is reported as ambiguous. Neither is guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from ..contracts.artifacts import Requirement, RequirementException
from ..contracts.common import CoverageItem, Issue, Location
from ..contracts.ir import (
    Compare, Cond, Eq, FieldDecl, In, Missing, and_, not_, or_,
)
from . import units

AMBIGUOUS_WORDS = {
    "about", "around", "roughly", "approximately", "nearly", "almost", "soon", "quickly",
    "long", "several", "some", "usually", "generally", "typically", "probably", "maybe",
    "possibly", "likely", "reasonable", "appropriate", "significant", "etc",
}

_RULE_LINE = re.compile(r"^\s*[-*]\s*\[(?P<id>[^\]]+)\]\s*(?P<body>.+?)\s*$")
_FIELD_LINE = re.compile(r"^\s*[-*]\s*`(?P<name>[^`]+)`\s*\((?P<decl>[^)]*)\)")
_REVISION = re.compile(r"^\s*revision\s*:\s*(?P<rev>\S+)\s*$", re.I)
_HEADING = re.compile(r"^\s*#{1,6}\s*(?P<title>.+?)\s*$")
_VERB = r"(?:route|send|assign)\s+(?:it\s+|the\s+ticket\s+|all\s+other\s+tickets\s+|everything\s+else\s+)?to"
_DEFAULT = re.compile(rf"^{_VERB}\s+`(?P<route>[^`]+)`\s*\.?$", re.I)
_CONDITIONAL = re.compile(
    rf"^(?:if|when)\s+(?P<cond>.+?),?\s+(?:then\s+)?{_VERB}\s+`(?P<route>[^`]+)`(?P<rest>.*)$",
    re.I | re.S,
)
_EXCEPT = re.compile(
    rf"^\s*;\s*except\s+(?:if|when)\s+(?P<cond>.+?),?\s+{_VERB}\s+`(?P<route>[^`]+)`", re.I | re.S
)
_UNLESS = re.compile(r"^\s*,?\s*unless\s+(?P<cond>.+?)(?=\s*;|\s*$)", re.I | re.S)


class ParseError(ValueError):
    def __init__(self, message: str, ambiguous: bool = False):
        super().__init__(message)
        self.ambiguous = ambiguous


@dataclass
class RequirementsDoc:
    version: str
    revision: str | None
    fields: dict[str, FieldDecl]
    requirements: list[Requirement]
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    issues: list[Issue] = dc_field(default_factory=list)

    def by_id(self) -> dict[str, Requirement]:
        return {r.id: r for r in self.requirements}


# ---------------------------------------------------------------- tokenizer

_TOKEN = re.compile(r"`(?P<q>[^`]*)`|(?P<n>\d+(?:\.\d+)?)|(?P<p>[(),])|(?P<w>[A-Za-z_][A-Za-z_'-]*)|(?P<sp>\s+)|(?P<bad>.)")


def _tokenize(text: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for m in _TOKEN.finditer(text):
        if m.group("sp"):
            continue
        if m.group("q") is not None:
            out.append(("Q", m.group("q")))
        elif m.group("n"):
            out.append(("N", float(m.group("n"))))
        elif m.group("p"):
            out.append(("P", m.group("p")))
        elif m.group("w"):
            out.append(("W", m.group("w").lower()))
        else:
            ch = m.group("bad")
            if ch in ".;:":
                continue
            raise ParseError(f"unexpected character {ch!r}")
    return out


class _CondParser:
    def __init__(self, text: str, fields: dict[str, FieldDecl]):
        self.toks = _tokenize(text)
        self.i = 0
        self.fields = fields
        hedges = {v for k, v in self.toks if k == "W"} & AMBIGUOUS_WORDS
        if hedges:
            raise ParseError(f"hedged wording: {', '.join(sorted(hedges))}", ambiguous=True)

    # -- token helpers
    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def word(self, *options: str) -> bool:
        kind, val = self.peek()
        if kind == "W" and val in options:
            self.i += 1
            return True
        return False

    def words(self, *seq: str) -> bool:
        for k, w in enumerate(seq):
            kind, val = self.peek(k)
            if kind != "W" or val != w:
                return False
        self.i += len(seq)
        return True

    def expect(self, kind: str):
        k, v = self.peek()
        if k != kind:
            raise ParseError(f"expected {kind} at token {self.i}, found {v!r}")
        self.i += 1
        return v

    # -- grammar
    def parse(self) -> Cond:
        c = self.disj()
        if self.i != len(self.toks):
            raise ParseError(f"unparsed text starting at {self.peek()[1]!r}")
        return c

    def disj(self) -> Cond:
        parts = [self.conj()]
        while self.word("or"):
            parts.append(self.conj())
        return or_(*parts)

    def conj(self) -> Cond:
        parts = [self.atom()]
        while self.word("and"):
            parts.append(self.atom())
        return and_(*parts)

    def atom(self) -> Cond:
        self.word("either", "both")
        if self.peek() == ("P", "("):
            self.i += 1
            c = self.disj()
            if self.peek() != ("P", ")"):
                raise ParseError("unbalanced parenthesis")
            self.i += 1
            return c
        if self.word("not"):
            return not_(self.atom())
        self.word("the")
        kind, name = self.peek()
        if kind != "Q":
            raise ParseError(f"expected a backticked field, found {name!r}")
        self.i += 1
        if name not in self.fields:
            raise ParseError(f"undeclared field `{name}`")
        return self.predicate(self.fields[name])

    def number(self, f: FieldDecl) -> float:
        n = self.expect("N")
        kind, val = self.peek()
        unit = None
        if kind == "W" and units.is_unit(val):
            unit = val
            self.i += 1
        if f.type != "number":
            raise ParseError(f"numeric comparison on non-numeric field `{f.name}`")
        try:
            return units.convert(n, unit, f.unit)
        except units.UnitError as e:
            raise ParseError(str(e)) from e

    def value(self, f: FieldDecl):
        kind, val = self.peek()
        if kind == "Q":
            self.i += 1
            v: object = val
            if f.type == "bool":
                if val.lower() not in ("true", "false"):
                    raise ParseError(f"`{f.name}` is bool, got `{val}`")
                v = val.lower() == "true"
            elif f.type == "number":
                v = float(val)
        elif kind == "W" and val in ("true", "false") and f.type == "bool":
            self.i += 1
            v = val == "true"
        else:
            raise ParseError(f"expected a value for `{f.name}`, found {val!r}")
        if f.type == "enum" and v not in f.values:
            raise ParseError(f"`{v}` is not a declared value of `{f.name}`")
        return v

    def value_list(self, f: FieldDecl) -> tuple:
        vals = [self.value(f)]
        while True:
            k, v = self.peek()
            k2, _ = self.peek(1)
            if (k == "P" and v == ",") or (k == "W" and v == "or"):
                # `or` continues the list only when a bare value follows (not a field).
                if k2 == "Q" and self.peek(2) not in (("W", "is"), ("W", "equals"),
                                                      ("W", "exceeds"), ("W", "reaches")):
                    self.i += 1
                    self.word("or")
                    vals.append(self.value(f))
                    continue
            return tuple(vals)

    def predicate(self, f: FieldDecl) -> Cond:
        n = f.name
        if self.word("equals"):
            return Eq(field=n, value=self.value(f))
        if self.word("exceeds"):
            return Compare(field=n, op=">", value=self.number(f))
        if self.word("reaches"):
            return Compare(field=n, op=">=", value=self.number(f))
        if not self.word("is"):
            raise ParseError(f"expected 'is' after `{n}`")
        if self.word("missing", "absent", "empty") or self.words("not", "set") \
                or self.words("not", "provided"):
            return Missing(field=n)
        if self.word("present", "set", "provided") or self.words("not", "missing"):
            return not_(Missing(field=n))
        if self.words("not", "one", "of"):
            return not_(In(field=n, values=self.value_list(f)))
        if self.words("one", "of"):
            return In(field=n, values=self.value_list(f))
        if self.word("not"):
            return not_(Eq(field=n, value=self.value(f)))
        if self.words("at", "least"):
            return Compare(field=n, op=">=", value=self.number(f))
        if self.words("at", "most"):
            return Compare(field=n, op="<=", value=self.number(f))
        if self.words("more", "than") or self.words("greater", "than") or self.word("over", "above"):
            return Compare(field=n, op=">", value=self.number(f))
        if self.words("less", "than") or self.words("fewer", "than") or self.word("under", "below"):
            return Compare(field=n, op="<", value=self.number(f))
        if self.word("exactly"):
            v = self.number(f)
            return and_(Compare(field=n, op=">=", value=v), Compare(field=n, op="<=", value=v))
        if self.peek()[0] == "N":
            v = self.number(f)
            if self.words("or", "more") or self.words("or", "longer") or self.words("or", "above"):
                return Compare(field=n, op=">=", value=v)
            if self.words("or", "less") or self.words("or", "fewer") or self.words("or", "below"):
                return Compare(field=n, op="<=", value=v)
            return and_(Compare(field=n, op=">=", value=v), Compare(field=n, op="<=", value=v))
        return Eq(field=n, value=self.value(f))


def parse_condition(text: str, fields: dict[str, FieldDecl]) -> Cond:
    return _CondParser(text, fields).parse()


# ---------------------------------------------------------------- document

def _parse_field(name: str, decl: str) -> FieldDecl:
    parts = [p.strip() for p in decl.split(",")]
    head = parts[0].lower()
    if head.startswith("enum"):
        first = head.split(":", 1)[1].strip() if ":" in head else ""
        values = [v.strip("` ") for v in ([first] if first else []) + parts[1:] if v.strip("` ")]
        return FieldDecl(name=name, type="enum", values=tuple(values))
    if head == "number":
        unit = parts[1].lower() if len(parts) > 1 and parts[1] else None
        if unit is not None:
            units.canonical(unit)
        return FieldDecl(name=name, type="number", unit=unit)
    if head in ("bool", "boolean"):
        return FieldDecl(name=name, type="bool", values=(False, True))
    if head == "string":
        return FieldDecl(name=name, type="string")
    raise ParseError(f"unknown field type {head!r}")


def _parse_rule(rid: str, body: str, fields: dict[str, FieldDecl]):
    text = re.sub(r"^\s*otherwise\s*,?\s*", "", body, flags=re.I).strip()
    m = _DEFAULT.match(text)
    if m:
        return None, m.group("route"), (), True
    m = _CONDITIONAL.match(text)
    if not m:
        hedges = {w.lower() for w in re.findall(r"[A-Za-z]+", text.replace("`", " "))} & AMBIGUOUS_WORDS
        raise ParseError(
            "hedged wording: " + ", ".join(sorted(hedges)) if hedges
            else "sentence does not match a supported rule pattern",
            ambiguous=bool(hedges),
        )
    cond = parse_condition(m.group("cond"), fields)
    rest = m.group("rest").strip()
    um = _UNLESS.match(rest)
    if um:
        cond = and_(cond, not_(parse_condition(um.group("cond"), fields)))
        rest = rest[um.end():]
    exceptions = []
    while True:
        em = _EXCEPT.match(rest)
        if not em:
            break
        exceptions.append(RequirementException(
            condition=parse_condition(em.group("cond"), fields), route=em.group("route")))
        rest = rest[em.end():]
    if rest.strip(" .;"):
        raise ParseError(f"unsupported trailing clause {rest.strip()!r}")
    return cond, m.group("route"), tuple(exceptions), False


def parse_requirements(text: str, version: str) -> RequirementsDoc:
    fields: dict[str, FieldDecl] = {}
    reqs: list[Requirement] = []
    coverage: list[CoverageItem] = []
    issues: list[Issue] = []
    revision = None
    section = ""
    pending_rules: list[tuple[int, str, str, str]] = []

    def loc(lineno: int, line: str) -> Location:
        return Location(artifact="requirements", version=version, pointer=f"L{lineno}",
                        line=lineno, excerpt=line.strip()[:200])

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if (m := _REVISION.match(line)):
            revision = m.group("rev")
            continue
        if (m := _HEADING.match(line)):
            section = m.group("title").strip().lower()
            continue
        if section.startswith("field"):
            fm = _FIELD_LINE.match(line)
            if not fm:
                coverage.append(CoverageItem(location=loc(lineno, line), status="unsupported",
                                             reason="field declaration not understood"))
                continue
            try:
                fields[fm.group("name")] = _parse_field(fm.group("name"), fm.group("decl"))
            except (ParseError, units.UnitError) as e:
                coverage.append(CoverageItem(location=loc(lineno, line), status="unsupported",
                                             reason=f"field declaration: {e}"))
            continue
        if section.startswith("rule"):
            rm = _RULE_LINE.match(line)
            if not rm:
                coverage.append(CoverageItem(
                    location=loc(lineno, line), status="unsupported",
                    reason="text in Rules section without a [ID] anchor; not interpreted"))
                continue
            pending_rules.append((lineno, line, rm.group("id").strip(), rm.group("body")))
            continue
        routing_words = re.search(r"\b(route|routed|send|sent|assign|escalat|queue)", line, re.I)
        coverage.append(CoverageItem(
            location=loc(lineno, line),
            status="ambiguous" if routing_words else "ignored",
            reason=("routing language outside the Rules section; not treated as a requirement"
                    if routing_words else "non-normative text"),
        ))

    seen: set[str] = set()
    for lineno, line, rid, body in pending_rules:
        location = loc(lineno, line)
        if rid in seen:
            issues.append(Issue(code="duplicate_requirement_id", blocking=True, location=location,
                                message=f"requirement id {rid} appears more than once"))
            continue
        seen.add(rid)
        try:
            cond, route, exceptions, is_default = _parse_rule(rid, body, fields)
        except ParseError as e:
            coverage.append(CoverageItem(location=location,
                                         status="ambiguous" if e.ambiguous else "unsupported",
                                         reason=f"[{rid}] {e}"))
            continue
        reqs.append(Requirement(id=rid, order=len(reqs), text=body, condition=cond, route=route,
                                is_default=is_default, location=location, exceptions=exceptions))
        coverage.append(CoverageItem(location=location, status="supported", reason=f"[{rid}] parsed"))

    if not fields:
        issues.append(Issue(code="no_fields", blocking=True, message="no ## Fields section found"))
    defaults = [r for r in reqs if r.is_default]
    if len(defaults) > 1:
        issues.append(Issue(code="multiple_defaults", blocking=True, location=defaults[1].location,
                            message="more than one default requirement"))
    elif defaults and defaults[0] is not reqs[-1]:
        issues.append(Issue(code="default_not_last", blocking=False, location=defaults[0].location,
                            message="requirements after the default can never apply"))
    return RequirementsDoc(version=version, revision=revision, fields=fields,
                           requirements=reqs, coverage=coverage, issues=issues)
