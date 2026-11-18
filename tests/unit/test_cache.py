"""Changing any artifact or approval invalidates a cached PASS; failed answers are never cached."""
from reviewer.pipeline import review

from tests.conftest import read_json, write_json


def test_cache_hit_then_invalidated_by_approval_change(bundle_copy, config, tmp_path):
    config["cache"] = {"enabled": True, "dir": str(tmp_path / "c")}
    first = review(bundle_copy, config, model="fake")
    second = review(bundle_copy, config, model="fake")
    assert first.status == second.status == "PASS"
    assert second.model_usage.response_source == "cache" and second.model_usage.calls == 0

    ap = next(bundle_copy.glob("approvals*"))
    ap.write_text(ap.read_text(encoding="utf-8").replace("25", "35"), encoding="utf-8")
    third = review(bundle_copy, config, model="fake")
    assert third.model_usage.cache_key != first.model_usage.cache_key
    assert third.model_usage.response_source == "fake"
    assert third.status != "PASS"         # deterministic checks are always recomputed


def test_failed_answer_not_cached(bundle_copy, config, tmp_path):
    config["cache"] = {"enabled": True, "dir": str(tmp_path / "c")}
    review(bundle_copy, config, model="fake", fake_script="invented_ref")
    assert not any((tmp_path / "c").glob("*.json"))
