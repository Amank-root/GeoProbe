"""Small helpers with no geoctl dependencies: IDs, time, text similarity."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(now_ms: int | None = None) -> str:
    """A lexicographically sortable 26-char ID (ULID, Crockford base32)."""
    ms = now_ms if now_ms is not None else int(time.time() * 1000)
    rand = secrets.randbits(80)
    out = ""
    v = ms
    for _ in range(10):
        out = _B32[v & 0x1F] + out
        v >>= 5
    v = rand
    for _ in range(16):
        out = _B32[v & 0x1F] + out
        v >>= 5
    return out


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    return (dt or utc_now()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(*parts: Any) -> str:
    """Stable hash for cache keys and prompts. Sorted so dict order cannot leak in."""
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, (dict, list, tuple)):
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        else:
            h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()


_WS = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def similarity(a: str, b: str) -> float:
    """Token-level Jaccard similarity in 0..1.

    Deliberately not embedding-based: parity is a no-key check, and a
    deterministic lexical measure is what makes ACC-002 reproducible.
    """
    ta = set(normalize_ws(a).lower().split())
    tb = set(normalize_ws(b).lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def binomial_ci95(rate: float, n: int) -> tuple[float, float]:
    """95% CI on a proportion. Returns (0,0) for an empty sample.

    EVALS §4.2 treats this width as the resolution of the eval, and the
    threshold gate refuses to fire on a wide CI, so this must be the real
    binomial interval and not a normal approximation.
    """
    if n <= 0:
        return (0.0, 0.0)
    se = math.sqrt(max(rate * (1.0 - rate), 0.0) / n)
    return (max(0.0, rate - 1.96 * se), min(1.0, rate + 1.96 * se))


def bucket_number(value: float, buckets: Sequence[tuple[float, str]]) -> str:
    for edge, label in buckets:
        if value < edge:
            return label
    return buckets[-1][1]


def is_ci_env() -> bool:
    ci_vars = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "BUILDKITE", "CIRCLECI")
    if any(os.environ.get(v) for v in ci_vars):
        return True
    return bool(os.environ.get("CONTINUOUS_INTEGRATION"))


def strip_tags(html: str) -> str:
    return normalize_ws(re.sub(r"<[^>]+>", " ", html or ""))
