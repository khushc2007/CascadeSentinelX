"""classical_search(): the common benchmark interface for every classical method (V2 20.1)."""
from __future__ import annotations
import time
import numpy as np
from ..oracle.interface import BudgetExhausted, CountedEvaluator, SearchResult, TargetReached
from . import methods_basic as mb, methods_structural as ms

METHODS = {"brute": mb.brute_force, "random": mb.random_search, "hillclimb": mb.hill_climb, "beam": mb.beam_search,
           "sa": mb.simulated_annealing, "ga": mb.genetic_algorithm, "lodf_pool": ms.lodf_pool, "ml_screen": ms.ml_screen,
           "milp": ms.milp_interdiction, "bnb": ms.branch_and_bound}
LABELS = {"bnb": "[PROPOSED/stretch] heuristic, not exact", "milp": "static DC interdiction (different severity definition)"}
STOCHASTIC = {"random", "hillclimb", "sa", "ga", "ml_screen"}

def classical_search(oracle, method: str, budget: int | None = None, seed: int = 0, grid: str = "grid",
                     target: float | None = None, stop_on_target: bool = False, keep_evaluated: bool = False, **params) -> SearchResult:
    if method not in METHODS: raise KeyError(f"unknown method {method!r}; have {sorted(METHODS)}")
    ev = CountedEvaluator(oracle, budget=budget, target=target, stop_on_target=stop_on_target)
    rng = np.random.default_rng(seed)
    t0, c0 = time.perf_counter(), time.process_time(); info = {"completed": True}
    try:
        info = METHODS[method](ev, rng, **params)
    except (BudgetExhausted, TargetReached) as e:
        info = {"completed": False, "aux": {"stopped_by": type(e).__name__}}
    rt, cpu = time.perf_counter() - t0, time.process_time() - c0
    sp = oracle.space
    best = ev.best_set
    N = sp.N
    return SearchResult(
        algorithm=method, params=dict(params), grid=grid, fidelity=oracle.fidelity, oracle_kind=getattr(oracle, "kind", "cascade"),
        L=sp.L, k=sp.k, N=N, objective="max_severity", seed=seed if method in STOCHASTIC else None, budget=budget,
        oracle_calls=ev.unique, candidate_evaluations=ev.requests, runtime_s=rt, cpu_s=cpu,
        best_severity=float(ev.best) if best is not None else float("nan"), best_contingency=best or (),
        best_rank=sp.rank(best) if best is not None else None,
        found_target=None if target is None else ev.discovery_calls is not None,
        discovery_calls=ev.discovery_calls, calls_to_within_1pct=ev.within1pct_calls,
        certified_stop_calls=ev.unique if info.get("certified") and info.get("completed") else None,
        completed=bool(info.get("completed", True)), trace=ev.trace, aux=info.get("aux", {}), exact=info.get("exact"),
        label=LABELS.get(method, ""), evaluated=ev.evaluated_sets() if keep_evaluated else None)
