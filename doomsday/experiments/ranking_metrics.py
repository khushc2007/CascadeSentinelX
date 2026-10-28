"""Tie-aware top-T stability metrics (approved decision 2).
s_T = T-th largest severity; tie-expanded top-T = { i : S_i >= s_T - band }. PRIMARY stability result = Jaccard of the
tie-expanded sets across variants. Deterministic top-T (order by (-S, index), cut at T) overlap is SECONDARY only."""
from __future__ import annotations
import numpy as np
from scipy.stats import rankdata

BAND = 1e-9

def s_T(S, T: int) -> float:
    S = np.asarray(S, dtype=np.float64)
    if not 1 <= T <= len(S):
        raise ValueError("T must be in [1, N]")
    return float(np.sort(S)[::-1][T - 1])

def tie_expanded_topT(S, T: int, band: float = BAND) -> np.ndarray:
    S = np.asarray(S, dtype=np.float64)
    return np.flatnonzero(S >= s_T(S, T) - band)

def deterministic_topT(S, T: int) -> np.ndarray:
    S = np.asarray(S, dtype=np.float64)
    return np.lexsort((np.arange(len(S)), -S))[:T]          # primary key -S, secondary index

def jaccard(a, b) -> float:
    a, b = set(np.asarray(a).tolist()), set(np.asarray(b).tolist())
    return 1.0 if not (a | b) else len(a & b) / len(a | b)

def distinct_levels(values, band: float = BAND) -> int:
    """Number of severity levels: sorted values split where the gap exceeds `band`."""
    v = np.sort(np.asarray(values, dtype=np.float64))[::-1]
    return 0 if len(v) == 0 else 1 + int(np.sum(v[:-1] - v[1:] > band))

def spearman(Sa, Sb) -> float:
    """Spearman rho with average ranks for ties (ties are the norm here). NaN if either vector is constant."""
    ra, rb = rankdata(Sa, method="average"), rankdata(Sb, method="average")
    if np.ptp(ra) == 0 or np.ptp(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])

def topT_stability(Sa, Sb, Ts=(10, 100), band: float = BAND) -> dict:
    """Both variants must score the SAME candidate list in the same order. Top-T entries are marked informative=False when
    T > N, or when s_T <= band in either variant (the 'top-T' region is then just the all-zero plateau)."""
    Sa, Sb = np.asarray(Sa, dtype=np.float64), np.asarray(Sb, dtype=np.float64)
    if Sa.shape != Sb.shape or Sa.ndim != 1:
        raise ValueError("severity vectors must be 1-D and aligned")
    out = {"N": len(Sa), "spearman": spearman(Sa, Sb)}
    for T in Ts:
        if T > len(Sa):
            out[f"top{T}"] = {"feasible": False, "reason": f"T={T} > N={len(Sa)}"}; continue
        ea, eb = tie_expanded_topT(Sa, T, band), tie_expanded_topT(Sb, T, band)
        da, db = deterministic_topT(Sa, T), deterministic_topT(Sb, T)
        sa, sb = s_T(Sa, T), s_T(Sb, T)
        out[f"top{T}"] = {"feasible": True, "informative": bool(sa > band and sb > band),
                          "s_T": [sa, sb], "tie_expanded_size": [len(ea), len(eb)],
                          "tie_expanded_jaccard": jaccard(ea, eb),                       # PRIMARY
                          "distinct_levels_in_region": [distinct_levels(Sa[ea], band), distinct_levels(Sb[eb], band)],
                          "deterministic_overlap_secondary": len(set(da.tolist()) & set(db.tolist())) / T,
                          "deterministic_jaccard_secondary": jaccard(da, db)}
    return out
