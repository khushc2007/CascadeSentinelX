from __future__ import annotations
from ..config import load_config
from ..gridtwin.base import build_base_point
from .ac_oracle import ACOracle
from .cache import ResultCache
from .dc_oracle import DCOracle
from .interface import Oracle

def make_oracle(fidelity: str, k: int, cfg=None, grid=None, cache: ResultCache | None = None,
                use_cache: bool = True, fast_path: bool = False, bp=None) -> Oracle:
    cfg = cfg or load_config()
    bp = bp or build_base_point(grid or cfg.grid, cfg)
    cls = {"dc": DCOracle, "ac": ACOracle}.get(fidelity)
    if cls is None:
        raise ValueError("fidelity must be 'dc' or 'ac'")
    return cls(bp, cfg, k, cache=cache, use_cache=use_cache, fast_path=fast_path)
