"""Opt-in telemetry (TELEMETRY.md, ADR-005).

Hard rules this module exists to enforce:

- It imports nothing from the audit data models, so it *cannot* carry page
  content, URLs, or prompts even by accident.
- The payload is an allow-list, and a test asserts nothing else appears.
- Failures are swallowed; telemetry never changes an exit code or output.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import bucket_number, is_ci_env

TELEMETRY_VERSION = "1"
ENDPOINT = os.environ.get("GEOCTL_TELEMETRY_ENDPOINT", "")
TIMEOUT_SECONDS = 2.0

# The complete set of fields that may ever be sent. Anything not here is a bug.
ALLOWED_FIELDS = frozenset(
    {
        "telemetry_version",
        "install_id",
        "event",
        "command",
        "tool_version",
        "python_version",
        "os",
        "flags_used",
        "eval_enabled",
        "provider_family",
        "pages_bucket",
        "duration_bucket",
        "exit_code",
        "error_type",
    }
)

PAGES_BUCKETS = [(1, "1"), (6, "2-5"), (11, "6-10"), (26, "11-25"), (51, "26-50")]
DURATION_BUCKETS = [(1.0, "<1s"), (10.0, "1-10s"), (30.0, "10-30s"), (120.0, "30-120s")]

DISABLE_REASONS = {
    "config": "[telemetry] enabled = false in config",
    "do_not_track": "DO_NOT_TRACK=1",
    "env_off": "GEOCTL_TELEMETRY=0",
    "ci": "running in CI without GEOCTL_TELEMETRY=1",
    "not_enabled": "telemetry is opt-in and has not been enabled",
    "no_endpoint": "no telemetry endpoint is configured",
}


@dataclass
class Event:
    """Builds and filters the payload. No audit data can reach it."""

    command: str
    tool_version: str
    install_id: str
    flags_used: list[str] = field(default_factory=list)
    eval_enabled: bool = False
    provider_family: str | None = None
    pages: int = 0
    duration_ms: int = 0
    exit_code: int = 0
    error_type: str | None = None

    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "telemetry_version": TELEMETRY_VERSION,
            "install_id": self.install_id,
            "event": "command_run",
            "command": self.command,
            "tool_version": self.tool_version,
            "python_version": f"{platform.python_version_tuple()[0]}."
            f"{platform.python_version_tuple()[1]}",
            "os": platform.system().lower(),
            # Names only, never values: a flag value could be a URL.
            "flags_used": sorted({f.split("=", 1)[0] for f in self.flags_used}),
            "eval_enabled": self.eval_enabled,
            "provider_family": self.provider_family,
            "pages_bucket": bucket_number(self.pages, PAGES_BUCKETS),
            "duration_bucket": bucket_number(self.duration_ms / 1000, DURATION_BUCKETS),
            "exit_code": self.exit_code,
            "error_type": self.error_type,
        }
        # Allow-list, not deny-list: a new field must be added deliberately.
        return {k: v for k, v in data.items() if k in ALLOWED_FIELDS}


def install_id_path(config_dir: Path | None = None) -> Path:
    base = config_dir or Path.home() / ".config" / "geoctl"
    return base / "install_id"


def load_install_id(config_dir: Path | None = None, *, create: bool = False) -> str | None:
    """The random ID used to count unique installs. It identifies no one."""
    path = install_id_path(config_dir)
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        if not create:
            return None
        value = str(uuid.uuid4())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
        return value
    except OSError:
        return None


def rotate_install_id(config_dir: Path | None = None) -> str:
    """Delete and recreate, which is how a user requests their data removed."""
    path = install_id_path(config_dir)
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)
    return load_install_id(config_dir, create=True) or ""


def status(config_enabled: bool | None = None, config_dir: Path | None = None) -> dict[str, Any]:
    """Why telemetry is on or off, with the hard off-switches first."""
    dnt = os.environ.get("DO_NOT_TRACK")
    env = os.environ.get("GEOCTL_TELEMETRY")

    if dnt == "1":
        enabled, reason = False, DISABLE_REASONS["do_not_track"]
    elif env == "0":
        enabled, reason = False, DISABLE_REASONS["env_off"]
    elif env == "1":
        enabled, reason = True, "GEOCTL_TELEMETRY=1"
    elif is_ci_env() and os.environ.get("GEOCTL_TELEMETRY") != "1":
        # Checked before the endpoint, because a CI user with telemetry enabled in
        # their config should be told *why* it is still off.
        enabled, reason = False, DISABLE_REASONS["ci"]
    elif config_enabled is False:
        enabled, reason = False, DISABLE_REASONS["config"]
    elif config_enabled is True and not ENDPOINT:
        enabled, reason = False, DISABLE_REASONS["no_endpoint"]
    elif config_enabled is True:
        enabled, reason = True, "enabled in config"
    else:
        enabled, reason = False, DISABLE_REASONS["not_enabled"]

    return {
        "enabled": enabled,
        "reason": reason,
        "endpoint_configured": bool(ENDPOINT),
        "install_id": load_install_id(config_dir),
        "allowed_fields": sorted(ALLOWED_FIELDS),
    }


def send(event: Event, *, enabled: bool, config_dir: Path | None = None) -> bool:
    """Send one event. Returns whether it was sent. Never raises."""
    if not enabled:
        return False
    payload = event.payload()
    if os.environ.get("GEOCTL_TELEMETRY_DEBUG") == "1":
        print(f"telemetry payload: {json.dumps(payload, sort_keys=True)}", file=_stderr())
        return False
    if not ENDPOINT:
        return False
    try:
        import urllib.error
        import urllib.request

        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            ENDPOINT, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS):
            return True
    except Exception:
        return False


def _stderr() -> Any:
    import sys

    return sys.stderr


def sample_payload() -> str:
    """A realistic example for `geoctl telemetry show`."""
    return json.dumps(
        Event(
            command="audit",
            tool_version="0.1.0",
            install_id="00000000-0000-0000-0000-000000000000",
            flags_used=["--eval", "--format", "--max-pages"],
            eval_enabled=True,
            provider_family="openai",
            pages=10,
            duration_ms=4200,
            exit_code=0,
        ).payload(),
        indent=2,
        sort_keys=True,
    )


def schema() -> dict[str, Any]:
    return {
        "telemetry_version": TELEMETRY_VERSION,
        "allowed_fields": sorted(ALLOWED_FIELDS),
        "off_switches": sorted(DISABLE_REASONS.values()),
    }


def hostname_free_event(command: str) -> dict[str, Any]:
    """Guard used by the test suite: no hostname may appear in a payload."""
    event = Event(command=command, tool_version="0.1.0", install_id="x")
    payload = event.payload()
    host = socket.gethostname()
    assert host not in json.dumps(payload)
    return payload
