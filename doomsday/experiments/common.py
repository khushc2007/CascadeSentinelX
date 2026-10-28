"""Shared experiment helpers: base points, truth tables generated under the CURRENT oracle namespace (never silently reused from other code versions)."""
from __future__ import annotations
import dataclasses
import numpy as np
from ..config import load_config
from ..gridtwin.ac import solve_ac
from ..gridtwin.base import BasePoint, build_base_point
from ..gridtwin.dc import dc_base_injections, dc_power_flow
from ..gridtwin.identity import grid_content_hash, order_fingerprint
from ..gridtwin.loader import parse_matpower
from ..oracle.factory import make_oracle
from ..oracle.table_oracle import TableOracle, generate_truth_table

def base_point(grid="ieee14", cfg=None, **overrides):
    cfg = load_config(overrides=overrides or None) if (cfg is None or overrides) else cfg
    return cfg, build_base_point(grid, cfg)

def get_tables(ctx, fid: str, ks, grid="ieee14", cfg=None, bp=None) -> TableOracle:
    """TableOracle with tables for every k in ks (DC: all k from 1; AC: from min(ks)), generated under this code version's namespace."""
    cfg = cfg or ctx.cfg; bp = bp or build_base_point(grid, cfg); top = max(ks); dirs = []
    for j in range(1 if fid == "dc" else min(ks), top + 1):
        dirs.append(generate_truth_table(make_oracle(fid, j, cfg, bp=bp, use_cache=False), ctx.tables_dir, grid_name=grid, chunk=5000))
    return TableOracle.load(dirs, top, expect_namespace=make_oracle(fid, top, cfg, bp=bp, use_cache=False).namespace)

def toy_base_point(case_text: str, rating, name="toy") -> BasePoint:
    g0 = parse_matpower(case_text, name); ac = solve_ac(g0, tol=1e-12); p, loss = dc_base_injections(g0, ac)
    r = np.broadcast_to(np.asarray(rating, float), (g0.n_branch,)).copy(); g = g0.with_(rating_ac=r, rating_dc=r.copy())
    return BasePoint(g, ac, dc_power_flow(g, p), p, loss, {"family": "manual"}, [], grid_content_hash(g0), order_fingerprint(g0))

def with_dc_ratings(bp, rating_dc): return dataclasses.replace(bp, grid=bp.grid.with_(rating_dc=np.asarray(rating_dc, float)))
def with_ratings(bp, rating_dc=None, rating_ac=None):
    g = bp.grid; return dataclasses.replace(bp, grid=g.with_(rating_dc=g.rating_dc if rating_dc is None else np.asarray(rating_dc, float), rating_ac=g.rating_ac if rating_ac is None else np.asarray(rating_ac, float)))

CHAIN4 = """mpc.baseMVA = 100;
mpc.bus = [ 1 3 0 0 0 0 1 1.0 0 0 1 1.1 0.9; 2 1 40 0 0 0 1 1.0 0 0 1 1.1 0.9; 3 1 60 0 0 0 1 1.0 0 0 1 1.1 0.9; 4 2 0 0 0 0 1 1.0 0 0 1 1.1 0.9; ];
mpc.gen = [ 1 70 0 100 -100 1.0 100 1 100 0; 4 30 0 100 -100 1.0 100 1 50 0; ];
mpc.branch = [ 1 2 0 0.1 0 0 0 0 0 0 1; 2 3 0 0.1 0 0 0 0 0 0 1; 3 4 0 0.1 0 0 0 0 0 0 1; ];"""
TRIANGLE = """mpc.baseMVA = 100;
mpc.bus = [ 1 3 0 0 0 0 1 1.0 0 0 1 1.1 0.9; 2 1 60 0 0 0 1 1.0 0 0 1 1.1 0.9; 3 1 40 0 0 0 1 1.0 0 0 1 1.1 0.9; ];
mpc.gen = [ 1 100 0 100 -100 1.0 100 1 300 0; ];
mpc.branch = [ 1 2 0 0.1 0 0 0 0 0 0 1; 1 3 0 0.1 0 0 0 0 0 0 1; 2 3 0 0.1 0 0 0 0 0 0 1; ];"""
PARALLEL = """mpc.baseMVA = 100;
mpc.bus = [ 1 3 0 0 0 0 1 1.0 0 0 1 1.1 0.9; 2 1 100 0 0 0 1 1.0 0 0 1 1.1 0.9; ];
mpc.gen = [ 1 100 0 200 -200 1.0 100 1 300 0; ];
mpc.branch = [ 1 2 0 0.1 0 0 0 0 0 0 1; 1 2 0 0.1 0 0 0 0 0 0 1; ];"""
LADDER = """mpc.baseMVA = 100;
mpc.bus = [ 1 3 0 0 0 0 1 1.0 0 0 1 1.1 0.9; 2 1 60 0 0 0 1 1.0 0 0 1 1.1 0.9; ];
mpc.gen = [ 1 60 0 500 -500 1.0 100 1 500 0; ];
mpc.branch = [ 1 2 0 1.0 0 0 0 0 0 0 1; 1 2 0 1.0 0 0 0 0 0 0 1; ];"""

def protocol_parts(config: dict, name: str, protocol: str, skip=()) -> list:
    """NOT_RUN parts for every pre-registered dataset that is not available+verified (never substituted by another dataset)."""
    from .framework import unavailable_part, dataset_info
    from .specs import PRE
    return [unavailable_part(f"{name}[{d['name']}]", d["name"], protocol) for d in config["datasets"] if d["role"] == PRE and d["name"] not in skip
            and not (dataset_info(d["name"])["available"] and dataset_info(d["name"])["verified"])]

# ---- Phase 7 helpers -----------------------------------------------------------------------------------------------------------------
import math as _math
from pathlib import Path as _Path
from ..config import config_hash as _config_hash
_BP_CACHE: dict = {}
INLINE_TABLE_LIMIT = 250_000          # tables larger than this must be pre-built (scripts/generate_truth_table.py); never built inline

def cfg_for(grid: str, overrides: dict | None = None):
    return load_config(overrides={"grid": grid, **(overrides or {})})

def bp_cached(grid: str, cfg):
    key = (grid, _config_hash(cfg))
    if key not in _BP_CACHE: _BP_CACHE[key] = build_base_point(grid, cfg)
    return _BP_CACHE[key]

class TableMissing(LookupError):
    pass

def tables_for(ctx, grid: str, fid: str, ks, cfg=None) -> TableOracle:
    """TableOracle over pre-built (or small, inline-built) tables for every k needed (DC: 1..max(ks); AC: min(ks)..max(ks)).
    Raises TableMissing for a large table that has not been pre-built completely."""
    from math import comb
    from ..oracle.table_oracle import table_dir_name
    cfg = cfg or cfg_for(grid); bp = bp_cached(grid, cfg); top = max(ks); dirs = []
    for j in range(1 if fid == "dc" else min(ks), top + 1):
        o = make_oracle(fid, j, cfg, bp=bp, use_cache=False)
        d = _Path(ctx.tables_dir) / table_dir_name(grid, fid, j, o.namespace); m = d / "meta.json"
        done = m.exists() and __import__("json").loads(m.read_text()).get("complete")
        if not done and d.exists() and any(d.iterdir()):          # partial or in-progress table: never write into it inline
            raise TableMissing(f"{grid} {fid} k={j} table at {d} is incomplete or being generated; finish it with scripts/generate_truth_table.py")
        if not done and o.space.N > INLINE_TABLE_LIMIT:
            raise TableMissing(f"{grid} {fid} k={j} table (N={o.space.N}) is not pre-built under {ctx.tables_dir}")
        dirs.append(generate_truth_table(o, ctx.tables_dir, grid_name=grid, chunk=5000))
    return TableOracle.load(dirs, top, expect_namespace=make_oracle(fid, top, cfg, bp=bp, use_cache=False).namespace)

def qstats(a) -> dict | None:
    a = np.asarray(a, float)
    if not len(a): return None
    return {"mean": float(a.mean()), "median": float(np.median(a)), "p95": float(np.percentile(a, 95)), "max": float(a.max()), "min": float(a.min()), "n": int(len(a))}

def boot_ci(a, seed: int = 12345, B: int = 2000):
    a = np.asarray(a, float)
    if len(a) < 2: return None
    rng = np.random.default_rng(seed); m = rng.choice(a, (B, len(a))).mean(axis=1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]

def loglog_fit(points):
    pts = [(n, c) for n, c in points if c and c > 0 and n > 1]
    if len(pts) < 3: return None
    x = np.log([p[0] for p in pts]); y = np.log([p[1] for p in pts]); A = np.vstack([x, np.ones_like(x)]).T
    (a, b), res, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ np.array([a, b]); ss = float(((y - yhat) ** 2).sum()); st = float(((y - y.mean()) ** 2).sum())
    return {"exponent": float(a), "coefficient": float(_math.exp(b)), "n_points": len(pts), "r2": (1 - ss / st) if st > 0 else None,
            "points": [[float(n), float(c)] for n, c in pts]}
