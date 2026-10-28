"""Deterministic keys (V2 20: cache key = grid hash + config hash + code version)."""
from __future__ import annotations
import hashlib, json
from functools import lru_cache
from pathlib import Path
from .. import __version__
from ..config import Config, config_hash, config_to_dict

_PKG = Path(__file__).resolve().parent.parent

def code_version(roots=None) -> str:
    """SHA-256 over (relative path, bytes) of every .py file in the packages that influence severities."""
    roots = [_PKG / "gridtwin", _PKG / "oracle", _PKG / "config.py"] if roots is None else [Path(r) for r in roots]
    h = hashlib.sha256(__version__.encode())
    files = []
    for r in roots:
        files += sorted(r.rglob("*.py")) if r.is_dir() else [r]
    for f in sorted(files, key=lambda p: p.as_posix()):
        h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()

@lru_cache(maxsize=1)
def _default_code_version() -> str:
    return code_version()

def oracle_config_dict(cfg: Config, fidelity: str, fast_path: bool) -> dict:
    """Only settings that can change a severity. Search/quantum/resource/severity-threshold settings are excluded so that
    changing them cannot invalidate (or wrongly reuse) cached severities."""
    d = config_to_dict(cfg)
    return {"rating": d["rating"], "stress_lambda": d["stress_lambda"], "cascade": d["cascade"],
            "numerics": d["numerics"], "fidelity": fidelity, "fast_path": bool(fast_path)}

def make_namespace(grid_hash: str, order_fp: str, cfg: Config, fidelity: str, fast_path: bool = False,
                   code_ver: str | None = None) -> str:
    blob = json.dumps({"grid": grid_hash, "order": order_fp, "config": config_hash(oracle_config_dict(cfg, fidelity, fast_path)),
                       "code": code_ver or _default_code_version()}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
