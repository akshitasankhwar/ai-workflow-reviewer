"""Shared fixtures: the base requirements text, its field declarations, and a writable
copy of the base bundle so tests can mutate one artifact at a time.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from reviewer.config import load_config
from reviewer.ingest.requirements_parser import parse_requirements

ROOT = Path(__file__).resolve().parents[1]
BASE_BUNDLE = ROOT / "bundles" / "dev" / "b01_valid_base"
BASE_REQUIREMENTS = (BASE_BUNDLE / "requirements.md").read_text(encoding="utf-8")


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def base_doc():
    return parse_requirements(BASE_REQUIREMENTS, "r1")


@pytest.fixture
def fields(base_doc):
    return base_doc.fields


@pytest.fixture
def bundle_copy(tmp_path):
    dst = tmp_path / "bundle"
    shutil.copytree(BASE_BUNDLE, dst)
    return dst


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
