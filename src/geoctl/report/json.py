"""JSON reporter: the public contract (OUTPUT_SCHEMA).

`geoctl audit --format json` emits exactly one AuditReport. Consumers depend on
field names and meanings, so this module does no reshaping — it serializes the
model the rest of the pipeline already produced.
"""

from __future__ import annotations

import json

from ..models import AuditReport


def dumps(report: AuditReport, *, indent: int | None = 2) -> str:
    # exclude_none is deliberately off: a field being present with null is part
    # of the schema (eval is null when it did not run), and consumers are
    # documented to handle it.
    return json.dumps(
        report.model_dump(mode="json", exclude_none=False),
        indent=indent,
        ensure_ascii=False,
        sort_keys=False,
    )


def schema_json() -> str:
    """The published JSON Schema, generated from the Pydantic models."""
    return json.dumps(
        AuditReport.model_json_schema(),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


def write(report: AuditReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(report))
        fh.write("\n")


def write_schema(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(schema_json())
        fh.write("\n")