"""Secure-base checks, V2 5.2 step 6: no base overload, and every non-bridge single outage settles with zero
overload trips, per engine. For a non-islanding single outage 'zero trips' is exactly 'no overload in the
round-0 solution', so a one-round static solve is equivalent to the cascade for this check."""
from __future__ import annotations
import numpy as np
from .ac import solve_ac
from .dc import dc_power_flow
from .islanding import bridges

def loading(bp, mode: str, status=None):
    g = bp.grid
    if mode == "dc":
        res = dc_power_flow(g, bp.dc_injections_mw, status)
        return np.abs(res.flow_mw) / g.rating_dc, True
    ac = solve_ac(g, status)
    return ac.apparent_mva / g.rating_ac, ac.converged

def base_overloads(bp, mode: str, tol: float = 1e-9):
    u, _ = loading(bp, mode)
    m = bp.grid.br_status > 0
    return [int(l) for l in np.flatnonzero(m & (u > 1.0 + tol))], u

def n1_report(bp, mode: str, tol: float = 1e-9) -> dict:
    g = bp.grid
    br = set(bridges(g))
    rows = []
    for l in range(g.n_branch):
        if g.br_status[l] == 0:
            continue
        if l in br:
            rows.append(dict(branch=l, label=g.branch_label(l), bridge=True)); continue
        s = g.br_status.copy(); s[l] = 0
        if mode == "dc":
            u, ok = loading(bp, "dc", s)
        else:
            ac = solve_ac(g, s)
            if not ac.converged:                      # retry warm-started from the base-case voltages
                ac = solve_ac(g, s, V0=bp.ac.V)
            u, ok = ac.apparent_mva / g.rating_ac, ac.converged
        u = np.where(s > 0, u, 0.0)
        over = [int(j) for j in np.flatnonzero(u > 1.0 + tol)]
        rows.append(dict(branch=l, label=g.branch_label(l), bridge=False, converged=bool(ok),
                         max_loading=float(u.max()), worst_branch=int(u.argmax()), overloads=over))
    viol = [r for r in rows if not r["bridge"] and (r["overloads"] or not r["converged"])]
    base_over, ubase = base_overloads(bp, mode, tol)
    return dict(mode=mode, base_overloads=base_over, base_max_loading=float(np.nanmax(ubase)),
                n_branches=len(rows), n_bridges=len(br), n1_violations=len(viol),
                violating_outages=[r["label"] for r in viol], rows=rows,
                secure=(not base_over) and not viol)
