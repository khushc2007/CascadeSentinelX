"""Top-T ranking (V2 12, Problem 5), Tier B EXACT EMULATION: repeated Durr-Hoyer maximum finding with an exclusion list.
Round j marks f(x) = [S(x) > y AND x not in found-list]. Implemented by running the tested dh_max on a predicate table whose excluded
entries are -inf: such x can never satisfy S > y, which is exactly the exclusion-list predicate. A coherent oracle would need T*k extra
comparators for the exclusion test (V2: reported separately, see `exclusion_comparators`). Expected cost ~ sum_{j<=T} sqrt(N/j) ~ 2 sqrt(NT)."""
from __future__ import annotations
from math import sqrt
import numpy as np
from .dh_gas import dh_max
from .predicate import PredicateTable

def expected_topT_cost(N: int, T: int) -> float:
    """V2's design-stage scaling sum_{j=1..T} sqrt(N/j) (approximately 2 sqrt(NT))."""
    return float(sum(sqrt(N / j) for j in range(1, T + 1)))

def top_t(pt: PredicateTable, T: int, rng, y0: float = -1.0, patience: int = 3, lam: float = 6 / 5) -> dict:
    """Find T sets in decreasing order of S. y0 = -1 (below every S in [0,1]) so the first round marks every non-excluded set, as in
    textbook Durr-Hoyer with a random initial threshold. Returns found ranks, per-round accounting and correctness against the table."""
    if not 1 <= T <= pt.N: raise ValueError("need 1 <= T <= N")
    S = pt.S.copy(); found, rounds = [], []; q_total = q_disc_sum = ver_total = 0
    for j in range(T):
        sub = PredicateTable(S, band=pt.band)
        r = dh_max(sub, rng, y0=y0, lam=lam, patience=patience); c = r["counter"]
        q_total += c.quantum_oracle_calls; ver_total += c.verifications
        if r["best"] is None: rounds.append({"j": j + 1, "found": None, "quantum_calls": c.quantum_oracle_calls}); break
        x = int(r["best"]); found.append(x); S[x] = -np.inf
        q_disc_sum += r["discovery_quantum_calls"] if r["discovery_quantum_calls"] is not None else c.quantum_oracle_calls
        rounds.append({"j": j + 1, "found": x, "S": float(pt.S[x]), "is_round_max": bool(r["found_Smax"]), "quantum_calls": c.quantum_oracle_calls,
                       "discovery_quantum_calls": r["discovery_quantum_calls"]})
    true_sorted = np.sort(pt.S)[::-1][:T]; got = np.array([pt.S[x] for x in found])
    correct = len(found) == T and bool(np.all(np.abs(got - true_sorted) <= pt.band))          # values match the true top-T (ties allowed)
    return {"found": found, "values": got.tolist(), "correct_topT_values": correct, "rounds": rounds, "quantum_oracle_calls": q_total,
            "discovery_quantum_calls_sum": q_disc_sum, "classical_verifications": ver_total, "expected_design_cost": expected_topT_cost(pt.N, T),
            "two_sqrt_NT": 2 * sqrt(pt.N * T), "table_construction_evals": pt.construction_evals}

def exclusion_comparators(T: int, k: int) -> int:
    """Extra comparators a coherent oracle needs to test x against a found-list of T sets of k indices each (V2 Problem 5 note)."""
    return T * k


# ---- threshold-list variant (Phase 10 finding) -------------------------------------------------------------------------------------
# E9 development found that V2's literal 'repeated maximum finding with an exclusion list' costs ~T * sqrt(N) (each round still searches
# ~N sets for a single maximum), NOT sum_j sqrt(N/j). The O(sqrt(NT)) behaviour V2 quotes belongs to the threshold-list scheme
# (Durr-Heiligman-Hoyer-Mhalla style): keep T candidates, mark any x outside the list with S(x) > min(list), replace the minimum on success,
# stop when a BBHT search with patience finds nothing. Both are reported by E9; neither is claimed beyond its measured behaviour.
from .bbht import bbht_search
from .emulation import MarkedSet

def top_t_threshold(pt: PredicateTable, T: int, rng, patience: int = 3, lam: float = 6 / 5) -> dict:
    if not 1 <= T <= pt.N: raise ValueError("need 1 <= T <= N")
    S, band, N = pt.S, pt.band, pt.N
    lst = [int(x) for x in rng.choice(N, T, replace=False)]                        # initial list: T classical samples (reported separately)
    inlist = np.zeros(N, bool); inlist[lst] = True; q_total = ver = 0; swaps = 0
    while True:
        i_min = min(range(T), key=lambda i: S[lst[i]]); y = float(S[lst[i_min]])
        ms = MarkedSet(N, np.flatnonzero((S > y + band) & ~inlist))
        r = bbht_search(ms, lambda x: bool(S[x] > y + band and not inlist[x]), rng, lam=lam, patience=patience)
        q_total += r["counter"].quantum_oracle_calls; ver += r["counter"].verifications
        if not r["found"]: break
        x = int(r["x"]); inlist[lst[i_min]] = False; lst[i_min] = x; inlist[x] = True; swaps += 1
    got = np.sort(S[lst])[::-1]; true_sorted = np.sort(S)[::-1][:T]
    return {"found": sorted(lst, key=lambda i: -S[i]), "values": got.tolist(), "correct_topT_values": bool(np.all(np.abs(got - true_sorted) <= band)),
            "quantum_oracle_calls": q_total, "classical_verifications": ver, "initial_classical_samples": T, "replacements": swaps,
            "expected_design_cost": expected_topT_cost(N, T), "two_sqrt_NT": 2 * sqrt(N * T), "table_construction_evals": pt.construction_evals}
