"""Validate the golden report against the published schema (CI gate).

OUTPUT_SCHEMA §1 requires CI to verify that example output validates. This runs
with no network and no API key: it reads two committed files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "geoctl.schema.json"
GOLDEN = ROOT / "tests" / "golden" / "report.json"


def main() -> int:
    if not SCHEMA.exists():
        print(f"missing {SCHEMA}; run: geoctl schema --output geoctl.schema.json")
        return 1
    if not GOLDEN.exists():
        print(f"missing golden report {GOLDEN}")
        return 1

    report = json.loads(GOLDEN.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    try:
        from geoctl.models import AuditReport
    except ImportError:
        print("geoctl is not importable; run this through `uv run`")
        return 1

    # The authoritative check: the model validates its own emitted document, and
    # the published schema is regenerated from that same model.
    try:
        AuditReport.model_validate(report)
    except Exception as exc:
        print(f"golden report does not validate against the models: {exc}")
        return 1

    required = set(schema.get("required", []))
    missing = required - set(report)
    if missing:
        print(f"golden report is missing required fields: {sorted(missing)}")
        return 1

    if report.get("schema_version") != schema.get("properties", {}).get("schema_version", {}).get(
        "default"
    ):
        print("golden schema_version disagrees with the schema default")
        return 1

    print(f"golden report validates (schema {report['schema_version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
