"""Common benchmark interface for search methods (V2 15.2). Records, per run: algorithm, grid, k, objective, oracle calls
(unique), candidate evaluations (requests), runtime, best severity, best contingency, plus discovery/within-1% calls, success at
budgets expressed in multiples of sqrt(N) and fractions of N, and coverage of the reference tie-expanded top-10/100.
Evidence label of everything produced here: [MEASURED] Phase 4 benchmark DIAGNOSTIC (not the E7 experiment)."""
from __future__ import annotations
import math
import numpy as np
from ..classical import STOCHASTIC, classical_search
from .ranking_metrics import BAND, distinct_levels, s_T, tie_expanded_topT

LABEL = "[MEASURED] Phase 4 benchmark diagnostic (not E7): IEEE-14 only, truth-table oracle, untuned a-priori hyper-parameters"

def reference(table) -> dict:
    """Ground truth from the (complete, deterministic) truth table. Success is always judged against Smax with the 1e-9 band."""
    S = table.all_severities(); N = len(S); smax = float(S.max())
    r = {"N": N, "k": table.k, "Smax": smax, "M_at_Smax": int((S >= smax - BAND).sum()), "maximizer_ranks": np.flatnonzero(S >= smax - BAND).tolist(),
         "frac_S_gt_0": float((S > BAND).mean())}
    for T in (10, 100):
        if T <= N:
            e = tie_expanded_topT(S, T); r[f"top{T}"] = {"s_T": s_T(S, T), "tie_expanded_size": int(len(e)), "ranks": e.tolist(),
                                                        "distinct_levels": distinct_levels(S[e])}
    return r

def budgets_for(N: int) -> dict:
    q = math.sqrt(N)
    return {"1*sqrtN": math.ceil(q), "5*sqrtN": math.ceil(5 * q), "10*sqrtN": math.ceil(10 * q), "22.5*sqrtN": math.ceil(22.5 * q),
            "0.1N": math.ceil(0.1 * N), "0.25N": math.ceil(0.25 * N), "0.5N": math.ceil(0.5 * N)}

def _best_at(trace, b):
    v = None
    for c, s in trace:
        if c <= b: v = s
    return v

def run_one(oracle, method: str, params: dict, seed: int, budget: int | None, grid: str, ref: dict, ac_table=None) -> dict:
    res = classical_search(oracle, method, budget=budget, seed=seed, grid=grid, target=ref["Smax"], keep_evaluated=True, **params)
    d = res.to_dict(); sp = oracle.space
    d["params"] = dict(params); d["success"] = bool(res.best_severity >= ref["Smax"] - BAND)
    d["gap_to_Smax"] = ref["Smax"] - res.best_severity
    d["success_at"] = {name: (res.discovery_calls is not None and res.discovery_calls <= b) for name, b in budgets_for(ref["N"]).items()}
    d["best_at"] = {name: _best_at(res.trace, b) for name, b in budgets_for(ref["N"]).items()}
    ev_ranks = set(sp.rank_batch(np.array(sorted(res.evaluated), dtype=np.int64).reshape(-1, sp.k)).tolist()) if res.evaluated else set()
    for T in (10, 100):
        if f"top{T}" in ref:
            R = set(ref[f"top{T}"]["ranks"]); d[f"coverage_top{T}"] = len(R & ev_ranks) / len(R)
    if ac_table is not None and res.best_contingency:
        d["ac_severity_of_best"] = ac_table.severity(res.best_contingency)
    d["n_evaluated_sets"] = len(ev_ranks)
    return d

def aggregate(rows: list, ref: dict) -> dict:
    """Group by (algorithm, params); statistics over seeds. Discovery statistics are over successful runs only; failures are counted."""
    groups: dict = {}
    for r in rows: groups.setdefault((r["algorithm"], tuple(sorted(r["params"].items(), key=lambda kv: kv[0]))), []).append(r)
    out = {}
    for (alg, par), rs in groups.items():
        disc = np.array([r["discovery_calls"] for r in rs if r["discovery_calls"] is not None], dtype=float)
        a = {"algorithm": alg, "params": dict(par), "k": ref["k"], "N": ref["N"], "n_runs": len(rs), "n_success": int(sum(r["success"] for r in rs)),
             "success_rate": float(np.mean([r["success"] for r in rs])),
             "success_rate_at": {b: float(np.mean([r["success_at"][b] for r in rs])) for b in rs[0]["success_at"]},
             "discovery_calls": ({"mean": float(disc.mean()), "median": float(np.median(disc)), "p95": float(np.percentile(disc, 95)), "n": int(len(disc))} if len(disc) else None),
             "discovery_over_sqrtN_mean": float(disc.mean() / math.sqrt(ref["N"])) if len(disc) else None,
             "oracle_calls_mean": float(np.mean([r["oracle_calls"] for r in rs])), "candidate_evaluations_mean": float(np.mean([r["candidate_evaluations"] for r in rs])),
             "runtime_s_mean": float(np.mean([r["runtime_s"] for r in rs])), "best_severity_mean": float(np.mean([r["best_severity"] for r in rs])),
             "best_severity_min": float(np.min([r["best_severity"] for r in rs])), "completed_fraction": float(np.mean([r["completed"] for r in rs])),
             "certified_stop_calls": rs[0]["certified_stop_calls"], "exact": rs[0]["exact"], "label": rs[0]["label"]}
        for T in (10, 100):
            if f"coverage_top{T}" in rs[0]: a[f"coverage_top{T}_mean"] = float(np.mean([r[f"coverage_top{T}"] for r in rs]))
        if "ac_severity_of_best" in rs[0]: a["ac_severity_of_best_mean"] = float(np.mean([r["ac_severity_of_best"] for r in rs]))
        out[f"{alg}|{dict(par)}"] = a
    return out

def fit_alpha(points) -> dict | None:
    """Fitted exponent in calls ~ kappa * N^alpha from >=3 (N, mean discovery calls) points (log-log least squares).
    With 3 values of k on ONE grid this is indicative only."""
    pts = [(n, c) for n, c in points if c and c > 0]
    if len(pts) < 3: return None
    x = np.log([p[0] for p in pts]); y = np.log([p[1] for p in pts]); A = np.vstack([x, np.ones_like(x)]).T
    (alpha, lk), *_ = np.linalg.lstsq(A, y, rcond=None)
    return {"alpha": float(alpha), "kappa": float(math.exp(lk)), "n_points": len(pts), "caveat": "few points on one grid: indicative only"}

SUITE = [("brute", {}), ("random", {}), ("hillclimb", {"n_starts": 5}), ("beam", {"width": 5}), ("beam", {"width": 20}), ("beam", {"width": 100}),
         ("sa", {}), ("ga", {}), ("lodf_pool", {"m": 8}), ("lodf_pool", {"m": 12}), ("lodf_pool", {"m": 16}), ("ml_screen", {}),
         ("milp", {"n_solutions": 5}), ("bnb", {"theta": 0.5}), ("bnb", {"theta": 0.8})]

def run_suite(oracle, grid: str, ref: dict, seeds=range(50), suite=SUITE, budget_frac: float = 0.5, ac_table=None) -> list:
    rows = []; N = ref["N"]
    for method, params in suite:
        stoch = method in STOCHASTIC
        budget = None if method in ("brute", "milp") else math.ceil(budget_frac * N)
        for seed in (seeds if stoch else [0]):
            rows.append(run_one(oracle, method, params, seed, budget, grid, ref, ac_table))
    return rows
