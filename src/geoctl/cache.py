"""Disk cache for fetches and LLM calls.

Reproducibility is a product promise (PRD §9): identical inputs must give
identical results at zero cost. Both buckets are therefore content-addressed,
never time-addressed.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from .util import content_hash

DEFAULT_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "geoctl"


class Cache:
    """Thin diskcache wrapper that degrades to a no-op rather than raising.

    A cache miss must never fail an audit, so a corrupt or unwritable cache
    directory turns every operation into a miss.
    """

    def __init__(self, directory: str | Path | None = None, enabled: bool = True) -> None:
        self.directory = Path(directory) if directory else DEFAULT_CACHE_DIR
        self.enabled = enabled
        self._store: Any | None = None
        self._broken = False
        if enabled:
            self._open()

    def _open(self) -> None:
        try:
            from diskcache import Cache as DiskCache

            self.directory.mkdir(parents=True, exist_ok=True)
            self._store = DiskCache(str(self.directory))
        except Exception:
            self._store = None
            self._broken = True

    @property
    def store(self) -> Any:
        """The backing store, or None.

        A property rather than a bare attribute so callers get one narrowing
        point instead of None-checks at every call site.
        """
        return self._store

    @property
    def available(self) -> bool:
        """Whether the store is usable.

        Checked as `is not None`, never by truthiness: diskcache defines
        __len__, so an *empty* cache is falsy and `if not self._store` would skip
        every write on a fresh cache — the cache could then never fill.
        """
        return self._store is not None

    def key(self, namespace: str, *parts: Any) -> str:
        return f"{namespace}:{content_hash(*parts)}"

    def get(self, namespace: str, *parts: Any) -> Any | None:
        store = self.store
        if store is None:
            return None
        try:
            return store.get(self.key(namespace, *parts))
        except Exception:
            return None

    def set(self, namespace: str, value: Any, *parts: Any,
            expire: float | None = None) -> None:
        """Store `value` under a key derived from `namespace` and `parts`.

        The key deliberately excludes `value`: with the value inside the hash, a
        later `get(namespace, *parts)` would compute a different key and the cache
        would silently never hit.
        """
        store = self.store
        if store is None:
            return
        try:
            store.set(self.key(namespace, *parts), value, expire=expire)
        except Exception:
            return

    def fetch(self, namespace: str, *parts: Any) -> tuple[Any | None, bool]:
        """Return (value, was_hit)."""
        value = self.get(namespace, *parts)
        return value, value is not None

    def stats(self) -> dict[str, Any]:
        store = self.store
        if store is None:
            return {"directory": str(self.directory), "enabled": self.enabled,
                    "entries": 0, "size_bytes": 0, "unavailable": True}
        try:
            return {
                "directory": str(self.directory),
                "enabled": True,
                "entries": len(store),
                "size_bytes": store.volume(),
            }
        except Exception:
            return {"directory": str(self.directory), "enabled": True, "entries": 0,
                    "size_bytes": 0, "unavailable": True}

    def clear(self, namespace: str | None = None) -> int:
        store = self.store
        if store is None:
            return 0
        prefix = f"{namespace}:" if namespace else ""
        try:
            keys = [k for k in store.iterkeys() if k.startswith(prefix)]
            for k in keys:
                del store[k]
            return len(keys)
        except Exception:
            return 0

    def close(self) -> None:
        store = self.store
        if store is not None:
            with contextlib.suppress(Exception):
                store.close()
        self._store = None


# Namespaces, so `geoctl cache clear --llm` cannot drop fetched pages.
NS_FETCH = "fetch"
NS_EXTRACT = "extract"
NS_LLM = "llm"
NS_EMBED = "embed"