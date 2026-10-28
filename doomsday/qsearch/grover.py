"""Grover with KNOWN M (V2 12, problem 1): toy and validation runs only."""
from __future__ import annotations
import numpy as np
from .accounting import QuantumCounter
from .emulation import MarkedSet, optimal_r

def grover_known_M(marked: MarkedSet, rng, r: int | None = None) -> dict:
    r = optimal_r(marked.N, marked.M) if r is None else int(r); cnt = QuantumCounter(); x = marked.sample(r, rng)
    cnt.attempt(r); cnt.verify(x)
    return {"r": r, "p_success": marked.p_success(r), "x": x, "is_marked": bool(np.isin(x, marked.ranks)), "counter": cnt}
