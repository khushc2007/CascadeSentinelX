"""BBHT (Boyer-Brassard-Hoyer-Tapp) search for an UNKNOWN number of marked states, Tier B emulation, V2 12 / 12.2 conventions:
schedule m = 1, lam, lam^2, ... <= m_cap (default sqrt(N)); each attempt draws j uniform in {0..ceil(m)-1}, applies j ideal Grover iterations,
measures, and verifies classically. A schedule that ends without success counts as one failure; `patience` consecutive failures stop the
search ('not found'). The failure probability is estimated empirically (never asserted)."""
from __future__ import annotations
from math import ceil, sqrt
import numpy as np
from .accounting import QuantumCounter

def bbht_search(marked, verify, rng, lam: float = 6 / 5, m_cap: float | None = None, budget: int | None = None, patience: int = 3,
                counter: QuantumCounter | None = None, record_log: bool = False) -> dict:
    """`marked`: MarkedSet; `verify(x) -> bool` the classical check. Returns dict(found, x, counter, terminated_by, log)."""
    N = marked.N; m_cap = sqrt(N) if m_cap is None else m_cap; cnt = counter or QuantumCounter()
    fails, found, x_found, why = 0, False, None, "patience"
    while fails < patience and not found:
        if budget is not None and cnt.quantum_oracle_calls >= budget: why = "budget"; break
        m = 1.0
        while m <= m_cap and not found:
            if budget is not None and cnt.quantum_oracle_calls >= budget: why = "budget"; break
            j = int(rng.integers(0, ceil(m))); x = marked.sample(j, rng); cnt.attempt(j); cnt.verify(x); ok = bool(verify(x))
            if record_log: cnt.log.append({"m": m, "j": j, "x": x, "success": ok})
            if ok: found, x_found = True, x; break
            m *= lam
        else:
            pass
        if why == "budget": break
        if not found: fails += 1
    return {"found": found, "x": x_found, "counter": cnt, "terminated_by": "found" if found else why}
