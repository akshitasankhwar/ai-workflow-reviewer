"""Bundle loading, incompleteness, and the requirement trace."""
from reviewer.pipeline import analysis_to_json, analyze

from tests.conftest import BASE_BUNDLE, read_json, write_json


def test_base_bundle_is_clean(config):
    a = analyze(BASE_BUNDLE, config)
    assert a.bundle.incomplete_reasons == []
    assert [i for i in a.issues if i.blocking] == []
    assert a.resolved.applied == ["A1"]
    for rid, e in a.refmap.entries.items():
        assert e.spec and e.workflow and e.code, rid
    assert any(c.status == "ignored" and c.location.pointer.endswith("/note") for c in a.coverage)
    analysis_to_json(a)


def test_input_hash_is_stable_and_content_sensitive(config, bundle_copy):
    h1 = analyze(bundle_copy, config).bundle.input_hash()
    assert analyze(bundle_copy, config).bundle.input_hash() == h1
    p = bundle_copy / "code" / "router.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert analyze(bundle_copy, config).bundle.input_hash() != h1


def test_missing_artifact_is_incomplete(config, bundle_copy):
    (bundle_copy / "workflow.json").unlink()
    a = analyze(bundle_copy, config)
    assert a.bundle.incomplete_reasons
    assert any(i.code == "missing_artifact" and i.blocking for i in a.issues)


def test_oversized_artifact_is_incomplete_not_truncated(config, bundle_copy):
    p = bundle_copy / "code" / "router.py"
    p.write_text(p.read_text(encoding="utf-8") + "#" * 300_000, encoding="utf-8")
    a = analyze(bundle_copy, config)
    assert any(i.code == "oversized_artifact" for i in a.issues)
    assert a.bundle.code is None


def test_invalid_json_is_incomplete(config, bundle_copy):
    (bundle_copy / "spec.json").write_text("{ not json", encoding="utf-8")
    a = analyze(bundle_copy, config)
    assert any(i.code == "invalid_json" for i in a.issues)


def test_path_escape_is_rejected(config, bundle_copy):
    m = read_json(bundle_copy / "manifest.json")
    m["artifacts"]["code"]["path"] = "../../secret.py"
    write_json(bundle_copy / "manifest.json", m)
    assert any(i.code == "path_outside_bundle" for i in analyze(bundle_copy, config).issues)


def test_revision_mismatch_is_blocking(config, bundle_copy):
    m = read_json(bundle_copy / "manifest.json")
    m["artifacts"]["requirements"]["version"] = "r2"
    write_json(bundle_copy / "manifest.json", m)
    a = analyze(bundle_copy, config)
    assert any(i.code == "version_mismatch" and i.blocking for i in a.issues)


def test_unknown_reference_is_reported(config, bundle_copy):
    wf = read_json(bundle_copy / "workflow.json")
    for n in wf["nodes"]:
        if n.get("rule_ref") == "R2":
            n["rule_ref"] = "R7"
    write_json(bundle_copy / "workflow.json", wf)
    codes = {i.code for i in analyze(bundle_copy, config).issues}
    assert {"unknown_ref", "unmapped_requirement"} <= codes
