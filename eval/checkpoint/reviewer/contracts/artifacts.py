"""Input schemas for the JSON artifacts of a bundle, plus the parsed requirement record.

Conditions in spec.json and workflow.json use this JSON form (`ConditionJSON`):
  {"missing": "category"}                      field is missing
  {"present": "category"}                      field is not missing
  {"field": "wait_time", "op": ">=", "value": 30, "unit": "minutes"}
  {"field": "priority", "op": "==", "value": "urgent"}     also "!="
  {"field": "tier", "op": "in", "values": ["vip", "gold"]}
  {"all": [c, ...]}   {"any": [c, ...]}   {"not": c}
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .common import Location, Strict
from .ir import Cond

ConditionJSON = dict[str, Any]


class Loose(BaseModel):
    """Input models keep unknown keys visible instead of failing on them."""

    model_config = ConfigDict(extra="allow", frozen=True)


# ---------------- manifest.json ----------------

class ArtifactRef(Strict):
    path: str
    version: str


class Manifest(Strict):
    bundle_id: str
    artifacts: dict[Literal["requirements", "spec", "workflow", "code", "approvals"], ArtifactRef]
    code_entrypoint: str = "route"


# ---------------- spec.json ----------------

class SpecRule(Loose):
    id: str
    priority: int = Field(description="Lower value is evaluated first; array order is irrelevant.")
    when: ConditionJSON
    route: str
    source_refs: list[str] = []


class SpecDefault(Loose):
    route: str
    source_refs: list[str] = []


class Spec(Loose):
    spec_version: str
    implements_revision: str
    rules: list[SpecRule]
    default: SpecDefault | None = None


# ---------------- workflow.json ----------------

class WorkflowNode(Loose):
    id: str
    type: Literal["decision", "route"]
    condition: ConditionJSON | None = None
    on_true: str | None = None
    on_false: str | None = None
    route: str | None = None
    rule_ref: str | None = None


class Workflow(Loose):
    workflow_version: str
    start: str
    nodes: list[WorkflowNode]


# ---------------- approvals.json ----------------

class ThresholdChange(Strict):
    value: float
    unit: str | None = None
    field: str | None = None


class AddRequirement(Strict):
    id: str
    text: str
    after: str | None = Field(None, description="Insert after this requirement id; None = first.")


class Change(Strict):
    requirement: str
    set_threshold: ThresholdChange | None = None
    set_route: str | None = None
    remove: bool = False
    add: AddRequirement | None = None


class Approval(Loose):
    """Only the top-level metadata is trusted; free-text fields are never interpreted."""

    id: str
    status: Literal["approved", "pending", "rejected", "withdrawn"]
    approver: str | None = None
    decided_at: str | None = None
    applies_to_revision: str
    sequence: int | None = None
    changes: list[Change]


class ApprovalsFile(Loose):
    approvals: list[Approval] = []


# ---------------- parsed requirements ----------------

class Requirement(Strict):
    """One normative sentence of requirements.md, compiled to IR."""

    id: str
    order: int
    text: str
    condition: Cond | None
    route: str
    is_default: bool
    location: Location
    exceptions: tuple["RequirementException", ...] = ()


class RequirementException(Strict):
    """`except if D, route to Y` inside requirement R: (C and D) -> Y, ahead of R."""

    condition: Cond
    route: str


Requirement.model_rebuild()
