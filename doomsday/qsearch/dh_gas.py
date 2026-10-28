"""Durr-Hoyer maximum finding with a BBHT subroutine (GAS-style threshold ascent), Tier B EXACT EMULATION; V2 12.2 specification, implemented once.
Marks S > y (strict, tie band 1e-9); on success y <- S[x] and the schedule restarts; stop when the schedule is exhausted with no improvement
for `patience` consecutive attempts. NOTE: V2's pseudocode leaves `verifications` uninitialised and is silent on M=0 (S_max = y0); here
M=0 means the marked set is empty, the ideal circuit leaves the uniform superposition untouched, and the attempt simply fails."""
from __future__ import annotations
import time
from math import ceil, log2, sqrt
import numpy as np
from ..oracle.interface import BAND, SearchResult
from .accounting import QuantumCounter
from .predicate import PredicateTable

DH_BOUND = lambda N: 22.5 * sqrt(N) + 1.4 * log2(N) ** 2          # proven expected-call bound (Durr-Hoyer), for reference only

def dh_max(pt: PredicateTable, rng, y0: float = 0.0, lam: float = 6 / 5, m_cap: float | None = None, budget: int | None = None,
           patience: int = 3, record_log: bool = False, max_attempts: int = 1_000_000) -> dict:
    """max_attempts is a SAFETY VALVE against a non-terminating predicate (never reached by correct runs: strict '>' guarantees termination)."""
    N = pt.N; m_cap = sqrt(N) if m_cap is None else m_cap; band = pt.band
    cnt = QuantumCounter(pt.construction_evals); y, best, fails = y0, None, 0
    trace_q, disc_q, disc_v, why = [], None, None, "patience"
    while fails < patience:
        if budget is not None and cnt.quantum_oracle_calls >= budget: why = "budget"; break
        marked = pt.marked_gt(y); m, found = 1.0, False
        while m <= m_cap:
            if budget is not None and cnt.quantum_oracle_calls >= budget: why = "budget"; break
            if cnt.attempts >= max_attempts: raise RuntimeError(f"Durr-Hoyer exceeded max_attempts={max_attempts}: non-terminating predicate?")
            j = int(rng.integers(0, ceil(m))); x = marked.sample(j, rng); cnt.attempt(j); cnt.verify(x); ok = pt.verify_gt(x, y)
            if record_log: cnt.log.append({"y": y, "m": m, "j": j, "x": x, "success": ok})
            if ok:
                y, best, found = float(pt.S[x]), x, True; trace_q.append([cnt.quantum_oracle_calls, y])
                if disc_q is None and y >= pt.Smax - band: disc_q, disc_v = cnt.quantum_oracle_calls, cnt.verifications
                break
            m *= lam
        if why == "budget": break
        fails = 0 if found else fails + 1
    return {"best": best, "y": y, "counter": cnt, "trace_quantum_calls": trace_q, "discovery_quantum_calls": disc_q,
            "discovery_verifications": disc_v, "terminated_by": why, "found_Smax": disc_q is not None}

def durr_hoyer(oracle, seed: int = 0, y0: float = 0.0, grid: str = "grid", budget: int | None = None, patience: int = 3, lam: float = 6 / 5,
               pt: PredicateTable | None = None, record_log: bool = False) -> SearchResult:
    """SearchResult for Durr-Hoyer on `oracle`. oracle_calls = UNIQUE CLASSICAL verifications (comparable with classical baselines only
    loosely: the headline quantum cost is aux['accounting']['quantum_oracle_calls']); the N-evaluation table construction is in aux."""
    t0 = time.perf_counter(); pt = pt or PredicateTable.from_oracle(oracle); sp = oracle.space
    r = dh_max(pt, np.random.default_rng(seed), y0, lam, None, budget, patience, record_log); cnt = r["counter"]
    best = sp.unrank(r["best"]) if r["best"] is not None else ()
    trace = [[cnt.unique_verifications, r["y"]]] if r["best"] is not None else []
    return SearchResult(
        algorithm="durr_hoyer_tierB", params={"y0": y0, "lam": lam, "patience": patience}, grid=grid, fidelity=oracle.fidelity,
        oracle_kind="EMULATED (Tier B, ideal amplitude amplification; not a quantum runtime)", L=sp.L, k=sp.k, N=sp.N, objective="max_severity",
        seed=seed, budget=budget, oracle_calls=cnt.unique_verifications, candidate_evaluations=cnt.verifications,
        runtime_s=time.perf_counter() - t0, cpu_s=0.0, best_severity=r["y"] if r["best"] is not None else float("nan"), best_contingency=best,
        best_rank=r["best"], found_target=r["found_Smax"], discovery_calls=r["discovery_verifications"], calls_to_within_1pct=None,
        certified_stop_calls=None, completed=r["terminated_by"] == "patience", trace=trace, exact=None,
        label="[EMULATED] Tier B exact classical emulation of ideal Durr-Hoyer; NOT a quantum runtime; no speedup claim",
        aux={"accounting": cnt.to_dict(), "trace_quantum_calls": r["trace_quantum_calls"], "discovery_quantum_calls": r["discovery_quantum_calls"],
             "terminated_by": r["terminated_by"], "Smax": pt.Smax, "dh_proven_bound_for_reference": DH_BOUND(sp.N),
             "stopping_rule": "patience (empirical failure probability, not a guarantee)", "attempt_log": cnt.log if record_log else None})
