"""Writes JSON Schema for every contract into /schemas.

    python scripts/export_schemas.py [out_dir]      (same as `reviewer schemas`)
"""
from __future__ import annotations

import sys

from reviewer.contracts import export

if __name__ == "__main__":
    for p in export(sys.argv[1] if len(sys.argv) > 1 else "schemas"):
        print(p)
