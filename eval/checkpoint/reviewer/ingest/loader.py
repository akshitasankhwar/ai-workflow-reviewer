"""Reads a bundle directory, enforces size limits (oversized -> reported, never truncated),
validates each file against contracts, records sha256 + version for every artifact,
then parses/compiles every artifact into the shared IR.

Anything that cannot be read becomes an entry in `incomplete_reasons`; the review can
then never PASS, because part of the evidence was not examined.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..contracts.artifacts import ApprovalsFile, Manifest
from ..contracts.common import CoverageItem, Issue, Location
from .code_compiler import CompiledCode, compile_code
from .requirements_parser import RequirementsDoc, parse_requirements
from .spec_compiler import CompiledSpec, compile_spec
from .workflow_compiler import CompiledWorkflow, compile_workflow

REQUIRED = ("requirements", "spec", "workflow", "code")


@dataclass
class RawArtifact:
    kind: str
    path: str
    version: str
    sha256: str
    size: int
    text: str


@dataclass
class LoadedBundle:
    root: Path
    manifest: Manifest | None = None
    raw: dict[str, RawArtifact] = dc_field(default_factory=dict)
    requirements: RequirementsDoc | None = None
    spec: CompiledSpec | None = None
    workflow: CompiledWorkflow | None = None
    code: CompiledCode | None = None
    approvals: ApprovalsFile | None = None
    issues: list[Issue] = dc_field(default_factory=list)
    coverage: list[CoverageItem] = dc_field(default_factory=list)
    incomplete_reasons: list[str] = dc_field(default_factory=list)

    @property
    def bundle_id(self) -> str:
        return self.manifest.bundle_id if self.manifest else self.root.name

    def versions(self) -> dict[str, str]:
        return {k: a.version for k, a in sorted(self.raw.items())}

    def input_hash(self) -> str:
        h = hashlib.sha256()
        for k in sorted(self.raw):
            h.update(f"{k}:{self.raw[k].version}:{self.raw[k].sha256}\n".encode())
        return h.hexdigest()

    def all_issues(self) -> list[Issue]:
        out = list(self.issues)
        for part in (self.requirements, self.spec, self.workflow, self.code):
            if part is not None:
                out.extend(part.issues)
        return out

    def all_coverage(self) -> list[CoverageItem]:
        out = list(self.coverage)
        for part in (self.requirements, self.spec, self.workflow, self.code):
            if part is not None:
                out.extend(part.coverage)
        return out


def _schema_msg(e: ValidationError) -> str:
    err = e.errors()[0]
    return f"{err['msg']} at {'/'.join(map(str, err['loc'])) or '/'}"


def _incomplete(b: LoadedBundle, code: str, msg: str, kind: str = "manifest",
                version: str = "?", pointer: str = "/") -> None:
    b.issues.append(Issue(code=code, message=msg, blocking=True,
                          location=Location(artifact=kind, version=version, pointer=pointer)))
    b.incomplete_reasons.append(f"{kind}: {msg}")


def _read(b: LoadedBundle, kind: str, ref_path: str, version: str, limit: int) -> RawArtifact | None:
    root = b.root.resolve()
    p = (root / ref_path).resolve()
    if root not in p.parents:
        _incomplete(b, "path_outside_bundle", f"{ref_path!r} points outside the bundle", kind, version)
        return None
    if not p.is_file():
        _incomplete(b, "missing_artifact", f"{ref_path} is listed in the manifest but not found",
                    kind, version)
        return None
    size = p.stat().st_size
    if size > limit:
        _incomplete(b, "oversized_artifact",
                    f"{ref_path} is {size} bytes, over the {limit}-byte limit; not reviewed",
                    kind, version)
        return None
    data = p.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        _incomplete(b, "undecodable_artifact", f"{ref_path} is not valid UTF-8 ({e.reason})",
                    kind, version)
        return None
    return RawArtifact(kind=kind, path=ref_path, version=version,
                       sha256=hashlib.sha256(data).hexdigest(), size=size, text=text)


def _json(b: LoadedBundle, raw: RawArtifact) -> Any:
    try:
        return json.loads(raw.text)
    except json.JSONDecodeError as e:
        _incomplete(b, "invalid_json", f"{raw.path}: {e.msg} at line {e.lineno}",
                    raw.kind, raw.version, f"L{e.lineno}")
        return None


def load_bundle(path: str | Path, config: dict[str, Any]) -> LoadedBundle:
    root = Path(path)
    limit = int(config["limits"]["max_artifact_bytes"])
    b = LoadedBundle(root=root)

    mpath = root / "manifest.json"
    if not mpath.is_file():
        _incomplete(b, "missing_manifest", f"manifest.json not found in {root.name}")
        return b
    if mpath.stat().st_size > limit:
        _incomplete(b, "oversized_artifact", "manifest.json is over the size limit")
        return b
    try:
        b.manifest = Manifest.model_validate_json(mpath.read_bytes())
    except ValidationError as e:
        _incomplete(b, "manifest_schema", f"manifest.json is invalid: {_schema_msg(e)}")
        return b

    for kind in REQUIRED:
        if kind not in b.manifest.artifacts:
            _incomplete(b, "missing_artifact", f"the manifest lists no {kind} artifact", kind)
    for kind, ref in sorted(b.manifest.artifacts.items()):
        raw = _read(b, kind, ref.path, ref.version, limit)
        if raw is not None:
            b.raw[kind] = raw

    if "requirements" not in b.raw:
        return b  # without the field declarations nothing else can be compiled
    req_raw = b.raw["requirements"]
    b.requirements = doc = parse_requirements(req_raw.text, req_raw.version)
    req_loc = Location(artifact="requirements", version=req_raw.version, pointer="/")
    if doc.revision is None:
        doc.issues.append(Issue(code="missing_revision", blocking=True, location=req_loc,
                                message="requirements.md declares no `revision:` line"))
    elif doc.revision != req_raw.version:
        doc.issues.append(Issue(code="version_mismatch", blocking=True, location=req_loc,
                                message=f"requirements revision {doc.revision} != manifest "
                                        f"version {req_raw.version}"))
    fields = doc.fields

    if (raw := b.raw.get("spec")) is not None and (data := _json(b, raw)) is not None:
        b.spec = compile_spec(data, raw.version, fields)
        sp = b.spec.spec
        if sp is not None and doc.revision and sp.implements_revision != doc.revision:
            b.spec.issues.append(Issue(
                code="stale_spec_revision", blocking=False,
                message=f"spec implements revision {sp.implements_revision}, "
                        f"requirements are at {doc.revision}",
                location=Location(artifact="spec", version=raw.version, pointer="/implements_revision")))
    if (raw := b.raw.get("workflow")) is not None and (data := _json(b, raw)) is not None:
        b.workflow = compile_workflow(data, raw.version, fields)
    if (raw := b.raw.get("code")) is not None:
        b.code = compile_code(raw.text, raw.version, fields, entrypoint=b.manifest.code_entrypoint)
    if (raw := b.raw.get("approvals")) is not None and (data := _json(b, raw)) is not None:
        try:
            b.approvals = ApprovalsFile.model_validate(data)
        except ValidationError as e:
            _incomplete(b, "approvals_schema", f"approvals.json is invalid: {_schema_msg(e)}",
                        "approvals", raw.version)
        else:
            for i, a in enumerate(b.approvals.approvals):
                for extra in sorted((a.model_extra or {}).keys()):
                    b.coverage.append(CoverageItem(
                        location=Location(artifact="approvals", version=raw.version,
                                          pointer=f"/approvals/{i}/{extra}"),
                        status="ignored",
                        reason=f"approval {a.id}: free-text field {extra!r} is never interpreted"))
    return b
