"""Regenerate the per-fixture expectation files from actual runs.

Expectations are *recorded*, not hand-written: each fixture is audited against a
local server and the resulting per-check statuses are written to
`tests/fixtures/expected/<fixture>.yaml`. The calibration runner then compares
later runs against them, so a behaviour change shows up as a diff rather than as
a silently different score.

Review the generated files against docs/CHECKS.md before release: a recorded
expectation is only as good as the review behind it.

Usage:  uv run python scripts/generate-expectations.py
"""

from __future__ import annotations

import asyncio
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from conftest import _Handler  # noqa: E402
from fixtures.catalog import FIXTURES  # noqa: E402
from geoctl.audit import audit, build_report  # noqa: E402
from geoctl.config import Config  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "expected"


def serve(builder):  # type: ignore[no-untyped-def]
    handler = type("H", (_Handler,), {"site": builder()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def main() -> int:
    config = Config()
    config.fetch.allow_private = True
    config.fetch.timeout = 5.0
    config.audit.max_pages = 1
    config.eval.enabled = "false"

    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder, known_good, notes in FIXTURES:
        server, url = serve(builder)
        try:
            report = build_report(
                asyncio.run(audit(config, url, cache=None, use_cache=False)), config
            )
        finally:
            server.shutdown()
            server.server_close()

        statuses = {check.id: check.status for check in report.checks}
        document = {
            "fixture": name,
            "known_good": known_good,
            "covers": notes,
            "checks": statuses,
        }
        (OUT / f"{name}.yaml").write_text(
            yaml.safe_dump(document, sort_keys=True), encoding="utf-8"
        )
        failures = [k for k, v in statuses.items() if v == "fail"]
        print(f"{name:32} score={report.score.overall:6.1f} "
              f"known_good={known_good!s:5} fails={len(failures)} {failures[:4]}")

    print(f"\nWrote {len(FIXTURES)} expectation files to {OUT.relative_to(ROOT)}")
    print("Review them against docs/CHECKS.md before treating them as correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
