"""Base operating point, V2 5.2, built in the specified order (steps 1-5; step 6 is security.py)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .ac import ACResult, solve_ac
from .dc import DCResult, dc_base_injections, dc_power_flow
from .identity import grid_content_hash, order_fingerprint
from .loader import load_grid
from .model import Grid
from .ratings import (perturb_ratings, ratings_from_case_file, synthesize_ratings, synthesize_ratings_n1_covering,
                      synthesize_ratings_voltage_class)
from .scaling import apply_stress

class BasePointError(RuntimeError):
    pass

@dataclass
class BasePoint:
    grid: Grid              # stressed grid, slack Pg updated to the AC solution, ratings attached
    ac: ACResult
    dc: DCResult
    dc_injections_mw: np.ndarray
    dc_loss_pickup_mw: float
    rating_info: dict
    warnings: list
    grid_hash: str = ""          # content hash of the INPUT grid (before stress), file-order independent
    order_fingerprint: str = ""  # hash of the ordered branch-key list (file order)

def build_base_point(grid_or_name, cfg) -> BasePoint:
    g = load_grid(grid_or_name) if isinstance(grid_or_name, str) else grid_or_name   # step 1
    ghash, ofp = grid_content_hash(g), order_fingerprint(g)
    g = apply_stress(g, cfg.stress_lambda)                                           # step 2
    nm = cfg.numerics
    ac = solve_ac(g, tol=nm.ac_tol_pu, max_iter=nm.ac_max_iter)                      # step 3
    if not ac.converged:
        raise BasePointError(f"base AC power flow did not converge (mismatch {ac.mismatch_pu:.3e} p.u.)")
    lo, hi = nm.voltage_band
    if ac.Vm.min() < lo or ac.Vm.max() > hi:
        raise BasePointError(f"base voltages outside [{lo},{hi}] p.u.: min {ac.Vm.min():.4f}, max {ac.Vm.max():.4f}")
    warns = []
    # record the solved slack generation in the grid (first in-service generator at the slack bus takes the residual)
    pg = g.gen_Pg.copy(); qg = g.gen_Qg.copy()
    sl = g.slack_bus
    idx = [i for i in range(g.n_gen) if g.gen_bus[i] == sl and g.gen_status[i] > 0]
    others = sum(pg[i] for i in idx[1:])
    pg[idx[0]] = ac.bus_gen_p_mw[sl] - others
    if pg[idx[0]] > g.gen_Pmax[idx[0]] + 1e-9 or pg[idx[0]] < g.gen_Pmin[idx[0]] - 1e-9:
        warns.append(f"slack generator Pg={pg[idx[0]]:.3f} MW outside [{g.gen_Pmin[idx[0]]},{g.gen_Pmax[idx[0]]}]")
    g = g.with_(gen_Pg=pg)
    p_dc, loss = dc_base_injections(g, ac)    # step 5 (derived from the AC solution only; computed before step 4 because the
    rc = cfg.rating                           # n1_covering extension needs DC injections to evaluate DC post-outage flows)
    dcf = dc_power_flow(g, p_dc).flow_mw if rc.dc_basis == "dc_flow" else None      # E3c per-engine ratings (default: V2 5.3)
    if rc.family == "proportional":           # V2 5.3 baseline
        g, info = synthesize_ratings(g, ac, rc.headroom_h, rc.floor_frac, dcf)         # step 4
        info = dict(info, family="proportional")
    elif rc.family == "n1_covering":          # implementation extension, see docs/RATING_EXTENSION.md
        g, info = synthesize_ratings_n1_covering(g, ac, p_dc, rc.headroom_h, rc.floor_frac, rc.n1_margin_m, dcf)
    elif rc.family == "voltage_class":        # E11 family (interpretation documented in ratings.py)
        g, info = synthesize_ratings_voltage_class(g, ac, rc.headroom_h, rc.floor_frac, dcf)
    else:                                     # case_file (E11)
        g, info = ratings_from_case_file(g)
    g, pinfo = perturb_ratings(g, rc.perturb_frac, rc.perturb_seed)
    info = dict(info, dc_basis=rc.dc_basis, **pinfo)
    dc = dc_power_flow(g, p_dc)
    return BasePoint(g, ac, dc, p_dc, loss, info, warns, ghash, ofp)
