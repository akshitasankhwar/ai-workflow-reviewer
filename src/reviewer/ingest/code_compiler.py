"""Restricted Python -> IR using `ast` only. The code is inspected, never executed.

Three separate stages:
  1. syntax check      ast.parse
  2. inspection        a walker that accepts only the subset below
  3. execution         never done; behaviour comes from the compiled IR

Accepted subset
  module level : docstring, NAME = <constant expression>, one `def <entrypoint>(ticket)`
  constants    : int/float/str/bool literals, + - * / on them, minutes(n) hours(n) seconds(n) days(n),
                 tuples of literals
  function     : docstring, if/elif/else, `return "<route>"`, `return None`/`return`, `pass`,
                 aliases `x = ticket.get("f")`, `x = ticket.get("f", d)`, `x = ticket["f"]`
  conditions   : and/or/not, comparisons (chained ok, either side), `is None`/`is not None`,
                 == != < <= > >=, in/not in a tuple, truthiness of bool and enum/string fields

Python runtime semantics are preserved so the reviewer can see crashes and fall-through:
  ticket["f"] on a missing key        -> KeyError       -> route __error__
  ticket.get("f") compared with <,>   -> TypeError      -> route __error__
  reaching the end of the function    -> returns None   -> route __none__
Comments of the form `# ref: R3` attach requirement ids to the next return (evidence only).
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field as dc_field
from typing import Any

from ..contracts.common import CoverageItem, Issue, Location
from ..contracts.ir import (
    FALSE, NO_ROUTE, TRUE, Compare, Cond, Const, DecisionList, Eq, FieldDecl, In, IRRule, Missing,
    and_, not_, or_,
)
from . import units

_UNIT_HELPERS = {"seconds", "minutes", "hours", "days"}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
_CMP = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}
_REF = re.compile(r"#\s*ref\s*:\s*(?P<ids>[A-Za-z0-9_\-, ]+)", re.I)


class Unsupported(ValueError):
    def __init__(self, node: ast.AST | None, message: str):
        super().__init__(message)
        self.lineno = getattr(node, "lineno", None)


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None


@dataclass(frozen=True)
class Access:
    """A ticket field read: how it behaves when the field is missing."""
    field: str
    mode: str          # "get" | "index"
    default: Any = None


@dataclass
class CompiledCode:
    decision_list: DecisionList | None
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    issues: list[Issue] = dc_field(default_factory=list)
    refs_by_line: dict[int, list[str]] = dc_field(default_factory=dict)


class _Compiler:
    def __init__(self, source: str, version: str, fields: dict[str, FieldDecl], entry: str):
        self.src_lines = source.splitlines()
        self.version = version
        self.fields = fields
        self.entry = entry
        self.consts: dict[str, Any] = {}
        self.aliases: dict[str, Access] = {}
        self.param = "ticket"
        self.out = CompiledCode(None)
        self.out.refs_by_line = _ref_comments(source)

    def loc(self, lineno: int | None) -> Location:
        excerpt = self.src_lines[lineno - 1].strip()[:200] if lineno and lineno <= len(self.src_lines) else None
        return Location(artifact="code", version=self.version,
                        pointer=f"L{lineno}" if lineno else "/", line=lineno, excerpt=excerpt)

    def unsupported(self, lineno: int | None, reason: str) -> None:
        self.out.coverage.append(CoverageItem(location=self.loc(lineno), status="unsupported", reason=reason))

    # ------------------------------------------------------------ module
    def run(self, tree: ast.Module) -> CompiledCode:
        func = None
        ok = True
        for i, stmt in enumerate(tree.body):
            if i == 0 and _is_docstring(stmt):
                continue
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                try:
                    self.consts[stmt.targets[0].id] = self.const(stmt.value)
                    self.out.coverage.append(CoverageItem(location=self.loc(stmt.lineno), status="supported",
                                                          reason=f"constant {stmt.targets[0].id}"))
                except Unsupported as e:
                    ok = False
                    self.unsupported(stmt.lineno, f"constant: {e}")
                continue
            if isinstance(stmt, ast.FunctionDef) and stmt.name == self.entry and func is None:
                func = stmt
                continue
            ok = False
            self.unsupported(stmt.lineno, f"{type(stmt).__name__} at module level is outside the supported subset")

        if func is None:
            self.out.issues.append(Issue(code="no_entrypoint", blocking=True, location=self.loc(None),
                                         message=f"no function named {self.entry!r}"))
            return self.out
        a = func.args
        if len(a.args) != 1 or a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs or func.decorator_list:
            self.unsupported(func.lineno, "entrypoint must take exactly one plain argument, no decorators")
            return self.out
        self.param = a.args[0].arg
        body = func.body[1:] if func.body and _is_docstring(func.body[0]) else func.body
        try:
            rules, fall = self.block(body, TRUE, None)
        except Unsupported as e:
            self.unsupported(e.lineno, str(e))
            return self.out
        self.out.coverage.append(CoverageItem(location=self.loc(func.lineno), status="supported",
                                              reason=f"function {self.entry} compiled"))
        if ok:
            self.out.decision_list = DecisionList(
                source="code", version=self.version, rules=tuple(rules),
                default_route=None if fall == FALSE else NO_ROUTE,
                default_location=None if fall == FALSE else self.loc(func.end_lineno))
        return self.out

    # ------------------------------------------------------------ statements
    def block(self, stmts: list[ast.stmt], cur: Cond, ref: str | None) -> tuple[list[IRRule], Cond]:
        rules: list[IRRule] = []
        for k, s in enumerate(stmts):
            if cur == FALSE:
                self.out.issues.append(Issue(code="unreachable_code", location=self.loc(s.lineno),
                                             message="statement after an unconditional return"))
                break
            if isinstance(s, ast.Pass) or _is_docstring(s):
                continue
            if isinstance(s, ast.Return):
                route = self.route_of(s)
                r = self.ref_at(s.lineno) or ref
                rules.append(IRRule(ref=r, condition=cur, route=route, location=self.loc(s.lineno)))
                cur = FALSE
                continue
            if isinstance(s, ast.Assign):
                self.alias(s)
                continue
            if isinstance(s, ast.If):
                c = self.cond(s.test)
                r = self.ref_at(s.lineno) or ref
                tr, tf = self.block(s.body, and_(cur, c), r)
                fr, ff = self.block(s.orelse, and_(cur, not_(c)), r) if s.orelse else ([], and_(cur, not_(c)))
                rules += tr + fr
                cur = or_(tf, ff)
                continue
            raise Unsupported(s, f"{type(s).__name__} statement is outside the supported subset")
        return rules, cur

    def ref_at(self, lineno: int) -> str | None:
        ids = self.out.refs_by_line.get(lineno) or self.out.refs_by_line.get(lineno - 1)
        return ids[0] if ids else None

    def route_of(self, s: ast.Return) -> str:
        if s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None):
            return NO_ROUTE
        v = self.const(s.value)
        if not isinstance(v, str):
            raise Unsupported(s, "return value must be a route string")
        return v

    def alias(self, s: ast.Assign) -> None:
        if len(s.targets) != 1 or not isinstance(s.targets[0], ast.Name):
            raise Unsupported(s, "only simple `name = ticket...` assignments are supported")
        name = s.targets[0].id
        acc = self.access(s.value)
        if acc is None:
            raise Unsupported(s, f"assignment to {name} is not a ticket field read")
        self.aliases[name] = acc

    # ------------------------------------------------------------ expressions
    def access(self, e: ast.expr) -> Access | None:
        if isinstance(e, ast.Name) and e.id in self.aliases:
            return self.aliases[e.id]
        if isinstance(e, ast.Subscript) and _is_name(e.value, self.param):
            key = self.const(e.slice)
            return Access(self.field(key, e).name, "index")
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) and e.func.attr == "get"
                and _is_name(e.func.value, self.param) and not e.keywords and 1 <= len(e.args) <= 2):
            key = self.const(e.args[0])
            f = self.field(key, e)
            default = self.const(e.args[1]) if len(e.args) == 2 else None
            if isinstance(default, Quantity):
                default = self.to_field_unit(default, f, e)
            return Access(f.name, "get", default)
        return None

    def field(self, key: Any, node: ast.AST) -> FieldDecl:
        if not isinstance(key, str):
            raise Unsupported(node, "ticket field name must be a string literal or constant")
        if key not in self.fields:
            raise Unsupported(node, f"field {key!r} is not declared in the requirements")
        return self.fields[key]

    def const(self, e: ast.expr) -> Any:
        if isinstance(e, ast.Constant) and isinstance(e.value, (int, float, str, bool)) or \
                (isinstance(e, ast.Constant) and e.value is None):
            return e.value
        if isinstance(e, ast.Name) and e.id in self.consts:
            return self.consts[e.id]
        if isinstance(e, ast.Tuple) or isinstance(e, ast.List) or isinstance(e, ast.Set):
            return tuple(self.const(x) for x in e.elts)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.USub):
            v = self.const(e.operand)
            if isinstance(v, Quantity):
                return Quantity(-v.value, v.unit)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return -v
        if isinstance(e, ast.BinOp) and isinstance(e.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            l, r = self.const(e.left), self.const(e.right)
            return _arith(e, l, r)
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id in _UNIT_HELPERS
                and len(e.args) == 1 and not e.keywords):
            v = self.const(e.args[0])
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise Unsupported(e, f"{e.func.id}() needs a number")
            return Quantity(float(v), e.func.id)
        raise Unsupported(e, f"expression `{ast.unparse(e)}` is not a supported constant")

    def to_field_unit(self, q: Quantity, f: FieldDecl, node: ast.AST) -> float:
        try:
            return units.convert(q.value, q.unit, f.unit)
        except units.UnitError as err:
            raise Unsupported(node, str(err)) from err

    def cond(self, e: ast.expr) -> Cond:
        if isinstance(e, ast.BoolOp):
            parts = [self.cond(v) for v in e.values]
            return and_(*parts) if isinstance(e.op, ast.And) else or_(*parts)
        if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
            return not_(self.cond(e.operand))
        if isinstance(e, ast.Compare):
            parts = []
            left = e.left
            for op, right in zip(e.ops, e.comparators):
                parts.append(self.compare(left, op, right, e))
                left = right
            return and_(*parts)
        if isinstance(e, ast.Constant) and isinstance(e.value, bool):
            return Const(value=e.value)
        acc = self.access(e)
        if acc is not None:
            return self.truthy(acc, e)
        raise Unsupported(e, f"condition `{ast.unparse(e)}` is outside the supported subset")

    def truthy(self, acc: Access, node: ast.AST) -> Cond:
        f = self.fields[acc.field]
        om = "error" if acc.mode == "index" else "false"
        if f.type == "bool":
            return Eq(field=f.name, value=True, on_missing=om, default=acc.default)
        if f.type in ("enum", "string") and acc.default is None:
            missing = Missing(field=f.name, on_missing=om)
            return not_(missing)
        raise Unsupported(node, f"truthiness of {f.type} field {f.name!r} is ambiguous (0 / '' are falsy)")

    def compare(self, left: ast.expr, op: ast.cmpop, right: ast.expr, node: ast.AST) -> Cond:
        if isinstance(op, (ast.Is, ast.IsNot)):
            acc, other = self.access(left), right
            if acc is None:
                acc, other = self.access(right), left
            if acc is None or not (isinstance(other, ast.Constant) and other.value is None):
                raise Unsupported(node, "`is` is supported only as `<field> is None`")
            if acc.default is not None:
                c: Cond = FALSE
            else:
                c = Missing(field=acc.field, on_missing="error" if acc.mode == "index" else "false")
            return not_(c) if isinstance(op, ast.IsNot) else c
        if isinstance(op, (ast.In, ast.NotIn)):
            acc = self.access(left)
            if acc is None:
                raise Unsupported(node, "`in` is supported only as `<field> in (<values>)`")
            vals = self.const(right)
            if not isinstance(vals, tuple):
                raise Unsupported(node, "`in` needs a tuple/list of literals")
            f = self.fields[acc.field]
            vals = tuple(self.value_for(v, f, node) for v in vals)
            c = In(field=f.name, values=vals, on_missing="error" if acc.mode == "index" else "false",
                   default=acc.default)
            return not_(c) if isinstance(op, ast.NotIn) else c
        sym = _CMP.get(type(op))
        if sym is None:
            raise Unsupported(node, f"operator {type(op).__name__} is not supported")
        acc, other = self.access(left), right
        if acc is None:
            acc, other, sym = self.access(right), left, _FLIP[sym]
        if acc is None:
            raise Unsupported(node, "comparison must involve a ticket field")
        f = self.fields[acc.field]
        value = self.const(other)
        if sym in ("==", "!="):
            c = Eq(field=f.name, value=self.value_for(value, f, node),
                   on_missing="error" if acc.mode == "index" else "false", default=acc.default)
            return not_(c) if sym == "!=" else c
        if f.type != "number":
            raise Unsupported(node, f"ordering comparison on non-numeric field {f.name!r}")
        num = self.value_for(value, f, node)
        # None < 30 raises TypeError in Python 3, so a missing value is an error for get() too.
        return Compare(field=f.name, op=sym, value=num, on_missing="error", default=acc.default)

    def value_for(self, v: Any, f: FieldDecl, node: ast.AST):
        if isinstance(v, Quantity):
            if f.type != "number":
                raise Unsupported(node, f"unit value compared with non-numeric field {f.name!r}")
            return self.to_field_unit(v, f, node)
        if f.type == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise Unsupported(node, f"{f.name!r} is numeric, compared with {v!r}")
            return float(v)
        if f.type == "enum" and v not in f.values:
            raise Unsupported(node, f"{v!r} is not a declared value of {f.name!r}")
        if f.type == "bool" and not isinstance(v, bool):
            raise Unsupported(node, f"{f.name!r} is bool, compared with {v!r}")
        return v


def _arith(node: ast.BinOp, l: Any, r: Any) -> Any:
    def num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    op = type(node.op)
    if isinstance(l, Quantity) or isinstance(r, Quantity):
        if op in (ast.Add, ast.Sub) and isinstance(l, Quantity) and isinstance(r, Quantity):
            rv = units.convert(r.value, r.unit, l.unit)
            return Quantity(l.value + rv if op is ast.Add else l.value - rv, l.unit)
        if op in (ast.Mult, ast.Div) and isinstance(l, Quantity) and num(r):
            return Quantity(l.value * r if op is ast.Mult else l.value / r, l.unit)
        if op is ast.Mult and isinstance(r, Quantity) and num(l):
            return Quantity(l * r.value, r.unit)
        raise Unsupported(node, "unsupported arithmetic on unit values")
    if num(l) and num(r):
        if op is ast.Div and r == 0:
            raise Unsupported(node, "division by zero in constant")
        return {ast.Add: l + r, ast.Sub: l - r, ast.Mult: l * r}.get(op, l / r if op is ast.Div else None)
    raise Unsupported(node, "arithmetic only on numbers")


def _is_docstring(s: ast.stmt) -> bool:
    return isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str)


def _is_name(e: ast.expr, name: str) -> bool:
    return isinstance(e, ast.Name) and e.id == name


def _ref_comments(source: str) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and (m := _REF.search(tok.string)):
                out[tok.start[0]] = [i.strip() for i in m.group("ids").split(",") if i.strip()]
    except (tokenize.TokenError, SyntaxError):
        pass
    return out


def compile_code(source: str, version: str, fields: dict[str, FieldDecl],
                 entrypoint: str = "route") -> CompiledCode:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        out = CompiledCode(None)
        out.issues.append(Issue(code="code_syntax", blocking=True,
                                location=Location(artifact="code", version=version,
                                                  pointer=f"L{e.lineno}", line=e.lineno),
                                message=f"syntax error: {e.msg}"))
        return out
    return _Compiler(source, version, fields, entrypoint).run(tree)
