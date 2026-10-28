"""Synthetic thermal ratings, V2 5.3:  R = max((1+h)*base_flow, s_floor), per engine, from ONE AC base point.
AC rating uses |S| (MVA); DC rating uses the AC *active* flow |P| (MW), as printed in 5.3.
Branch flow magnitude = max over the two branch ends (convention chosen here; V2 does not specify)."""
from __future__ import annotations
import numpy as np

def synthesize_ratings(grid, ac, h: float, floor_frac: float, dc_flow_mw=None):
    """dc_flow_mw (Phase 7, E3c 'per-engine ratings'): if given, the DC rating base is |DC base flow| instead of the
    AC active flow printed in V2 5.3 (the default, dc_flow_mw=None, is unchanged)."""
    mask = grid.br_status > 0
    s0 = ac.apparent_mva
    p0 = np.maximum(np.abs(ac.Sf_mva.real), np.abs(ac.St_mva.real)) if dc_flow_mw is None else np.abs(np.asarray(dc_flow_mw, float))
    floor_ac = floor_frac * float(s0[mask].max())
    floor_dc = floor_frac * float(p0[mask].max())
    r_ac = np.where(mask, np.maximum((1 + h) * s0, floor_ac), np.nan)
    r_dc = np.where(mask, np.maximum((1 + h) * p0, floor_dc), np.nan)
    return grid.with_(rating_ac=r_ac, rating_dc=r_dc), {"floor_ac_mva": floor_ac, "floor_dc_mw": floor_dc}


def post_outage_max_flows(grid, ac, dc_inj_mw, mode: str) -> np.ndarray:
    """max over non-bridge single outages of the post-outage branch flow magnitude (MW for DC, MVA for AC).
    Injections are unchanged (non-islanding outage, no rebalancing needed); AC slack picks up losses."""
    from .ac import solve_ac
    from .dc import dc_power_flow
    from .islanding import bridges
    br = set(bridges(grid))
    out = np.zeros(grid.n_branch)
    for l in range(grid.n_branch):
        if grid.br_status[l] == 0 or l in br:
            continue
        s = grid.br_status.copy(); s[l] = 0
        if mode == "dc":
            f = np.abs(dc_power_flow(grid, dc_inj_mw, s).flow_mw)
        else:
            res = solve_ac(grid, s)
            if not res.converged:
                res = solve_ac(grid, s, V0=ac.V)
            if not res.converged:
                raise RuntimeError(f"AC N-1 outage of branch {grid.branch_label(l)} did not converge; "
                                   "cannot build N-1 covering AC rating")
            f = res.apparent_mva
        out = np.maximum(out, np.where(s > 0, f, 0.0))
    return out

def synthesize_ratings_n1_covering(grid, ac, dc_inj_mw, h: float, floor_frac: float, m: float, dc_flow_mw=None):
    """IMPLEMENTATION/CALIBRATION EXTENSION (NOT V2 5.3). Added because the V2 baseline rule cannot satisfy V2 5.2 step 6
    on IEEE-14 (measured: results/phase1_rating_feasibility.json). Per engine:
        R_l = max( (1+h)*base_l , (1+m)*max_{non-bridge single outages} post_l , s_floor )
    The first and third terms are exactly the V2 5.3 rule, which is retained as the baseline in the returned info."""
    base_grid, info = synthesize_ratings(grid, ac, h, floor_frac, dc_flow_mw)
    post_ac = post_outage_max_flows(grid, ac, dc_inj_mw, "ac")
    post_dc = post_outage_max_flows(grid, ac, dc_inj_mw, "dc")
    mask = grid.br_status > 0
    r_ac = np.where(mask, np.maximum(base_grid.rating_ac, (1 + m) * post_ac), np.nan)
    r_dc = np.where(mask, np.maximum(base_grid.rating_dc, (1 + m) * post_dc), np.nan)
    info = dict(info, family="n1_covering", margin_m=m,
                baseline_rating_ac=base_grid.rating_ac.copy(), baseline_rating_dc=base_grid.rating_dc.copy(),
                n_branches_covering_term_binds_ac=int(np.sum(mask & (r_ac > base_grid.rating_ac + 1e-12))),
                n_branches_covering_term_binds_dc=int(np.sum(mask & (r_dc > base_grid.rating_dc + 1e-12))))
    return grid.with_(rating_ac=r_ac, rating_dc=r_dc), info


# ---- Phase 7 (E11 rating families, V2 17) -------------------------------------------------------------------------------
def branch_voltage_class(grid) -> np.ndarray:
    """Base-kV class of each branch = max(BASE_KV) of its two end buses (transformers take the higher side).
    A case without BASE_KV data (all zero, e.g. MATPOWER case14) has a single class 0."""
    kv = np.zeros(grid.n_bus) if grid.bus_base_kv is None else np.asarray(grid.bus_base_kv, float)
    return np.maximum(kv[grid.br_from], kv[grid.br_to])

def synthesize_ratings_voltage_class(grid, ac, h: float, floor_frac: float, dc_flow_mw=None):
    """IMPLEMENTATION INTERPRETATION of V2 17 'nominal MVA by voltage class' (V2 gives no class values): every branch in a
    base-kV class gets the same rating, (1+h) x the largest base flow in that class, per engine, then the V2 5.3 floor.
    This decouples ratings from each branch's own base flow (the property E11 tests)."""
    mask = grid.br_status > 0
    s0 = ac.apparent_mva
    p0 = np.maximum(np.abs(ac.Sf_mva.real), np.abs(ac.St_mva.real)) if dc_flow_mw is None else np.abs(np.asarray(dc_flow_mw, float))
    cls = branch_voltage_class(grid); r_ac = np.full(grid.n_branch, np.nan); r_dc = np.full(grid.n_branch, np.nan); per = {}
    for c in np.unique(cls[mask]):
        sel = mask & (cls == c)
        r_ac[sel] = (1 + h) * float(s0[sel].max()); r_dc[sel] = (1 + h) * float(p0[sel].max())
        per[repr(float(c))] = {"n_branches": int(sel.sum()), "rating_ac_mva": float(r_ac[sel][0]), "rating_dc_mw": float(r_dc[sel][0])}
    floor_ac = floor_frac * float(s0[mask].max()); floor_dc = floor_frac * float(p0[mask].max())
    r_ac = np.where(mask, np.maximum(r_ac, floor_ac), np.nan); r_dc = np.where(mask, np.maximum(r_dc, floor_dc), np.nan)
    return grid.with_(rating_ac=r_ac, rating_dc=r_dc), {"family": "voltage_class", "classes_kv": per, "n_classes": len(per),
                                                         "floor_ac_mva": floor_ac, "floor_dc_mw": floor_dc}

class RatingDataError(ValueError):
    pass

def ratings_from_case_file(grid):
    """V2 17 'case-file ratings': MATPOWER RATE_A (MVA) for AC and, as a stated proxy, the same number in MW for DC.
    Fails loudly when any in-service branch has no rating (RATE_A = 0), as in MATPOWER case14 and case118."""
    mask = grid.br_status > 0; ra = np.asarray(grid.rate_a_case, float)
    missing = int(np.sum(mask & (ra <= 0)))
    if missing:
        raise RatingDataError(f"case file has no RATE_A for {missing} in-service branches; rating.family=case_file is not applicable to {grid.name}")
    r = np.where(mask, ra, np.nan)
    return grid.with_(rating_ac=r.copy(), rating_dc=r.copy()), {"family": "case_file", "dc_proxy": "RATE_A MVA used as MW"}

def perturb_ratings(grid, frac: float, seed: int):
    """Multiply every rating (AC and DC alike) by an independent U(1-frac, 1+frac) factor (V2 17: +-10%, 50 draws)."""
    if frac <= 0: return grid, {}
    mult = np.random.default_rng(seed).uniform(1 - frac, 1 + frac, grid.n_branch)
    return grid.with_(rating_ac=grid.rating_ac * mult, rating_dc=grid.rating_dc * mult), {"perturb_frac": frac, "perturb_seed": seed,
                                                                                           "multiplier_min": float(mult.min()), "multiplier_max": float(mult.max())}
