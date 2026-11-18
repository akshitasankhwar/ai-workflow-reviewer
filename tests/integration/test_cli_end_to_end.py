"""CLI end to end on the base bundle."""
import json

from reviewer.cli import main

from tests.conftest import BASE_BUNDLE


def test_analyze_writes_json_and_exits_zero(tmp_path):
    out = tmp_path / "analysis.json"
    assert main(["analyze", str(BASE_BUNDLE), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["bundle_id"] == "b01_valid_base"
    assert data["approvals"]["applied"] == ["A1"]


def test_analyze_incomplete_bundle_exits_nonzero(tmp_path):
    (tmp_path / "empty").mkdir()
    assert main(["analyze", str(tmp_path / "empty"), "--out", str(tmp_path / "o.json")]) == 1


def test_review_base_bundle_passes(tmp_path):
    out = tmp_path / "report.json"
    assert main(["review", str(BASE_BUNDLE), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert {c["name"] for c in data["checks"]} >= {"spec_equivalence", "workflow_equivalence",
                                                     "code_equivalence", "coverage", "interaction"}


def test_review_with_disabled_check_exits_nonzero(tmp_path):
    out = tmp_path / "report.json"
    assert main(["review", str(BASE_BUNDLE), "--out", str(out), "--disable", "coverage"]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "INCOMPLETE"


def test_schemas_export(tmp_path):
    assert main(["schemas", "--out-dir", str(tmp_path)]) == 0
    assert list(tmp_path.glob("*.json"))
