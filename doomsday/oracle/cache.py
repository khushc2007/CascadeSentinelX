"""Result cache keyed by outage tuple inside a deterministic namespace. A cache can only be attached to an oracle whose
namespace matches, so stale or foreign results cannot be reused silently."""
from __future__ import annotations
import json
from pathlib import Path
from .interface import OracleRecord

class CacheNamespaceError(RuntimeError):
    pass

class ResultCache:
    def __init__(self, namespace: str, path: str | Path | None = None):
        self.namespace, self.path, self._d = namespace, (Path(path) if path else None), {}
    def get(self, key: tuple):
        return self._d.get(key)
    def put(self, key: tuple, rec: OracleRecord):
        self._d[key] = rec
    def __len__(self) -> int: return len(self._d)
    def __contains__(self, key) -> bool: return key in self._d
    def save(self, path: str | Path | None = None):
        p = Path(path or self.path)
        data = {"namespace": self.namespace, "records": [[list(k), r.to_dict()] for k, r in sorted(self._d.items())]}
        p.write_text(json.dumps(data, allow_nan=True))
    @classmethod
    def load(cls, path: str | Path, namespace: str) -> "ResultCache":
        data = json.loads(Path(path).read_text())
        if data.get("namespace") != namespace:
            raise CacheNamespaceError("cache file was produced under a different grid/config/code namespace; refusing to reuse")
        c = cls(namespace, path)
        for k, d in data["records"]:
            c._d[tuple(k)] = OracleRecord(**d)
        return c
