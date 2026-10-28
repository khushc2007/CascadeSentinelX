"""Stress scaling (V2 5.2 step 2)."""
from __future__ import annotations
import numpy as np

def apply_stress(grid, lam: float):
    """Scale all loads (P and Q) by lam >= 1 and every non-slack in-service generator's Pg by lam,
    clamped to [Pmin, Pmax]. The slack-bus generation is left unchanged here; the AC solve of the
    base point determines it (and it is checked against Pmax by the base-point builder)."""
    if lam < 1.0:
        raise ValueError("stress lambda must be >= 1")
    sl = grid.slack_bus
    pg = grid.gen_Pg.copy()
    for i in range(grid.n_gen):
        if grid.gen_status[i] > 0 and grid.gen_bus[i] != sl:
            pg[i] = np.clip(lam * pg[i], grid.gen_Pmin[i], grid.gen_Pmax[i])
    return grid.with_(Pd=grid.Pd * lam, Qd=grid.Qd * lam, gen_Pg=pg, load_scale=grid.load_scale * lam)
