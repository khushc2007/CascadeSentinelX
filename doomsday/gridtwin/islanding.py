"""Exact graph connectivity (V2 6.2, 8.1 step 3): connectivity is authoritative."""
from __future__ import annotations
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components as _cc

def connected_components(n_bus: int, br_from, br_to, status) -> tuple[int, np.ndarray]:
    """Components of the in-service graph. Returns (count, label per bus)."""
    m = np.asarray(status) > 0
    f, t = np.asarray(br_from)[m], np.asarray(br_to)[m]
    a = coo_matrix((np.ones(len(f)), (f, t)), shape=(n_bus, n_bus))
    return _cc(a, directed=False)

def grid_components(grid, status=None):
    s = grid.br_status if status is None else status
    return connected_components(grid.n_bus, grid.br_from, grid.br_to, s)

def bridges(grid, status=None) -> list[int]:
    """Branches whose single removal disconnects the network. Parallel branches are never bridges."""
    s = (grid.br_status if status is None else np.asarray(status)).copy()
    n0, _ = grid_components(grid, s)
    out = []
    for l in np.flatnonzero(s > 0):
        s2 = s.copy(); s2[l] = 0
        if grid_components(grid, s2)[0] > n0:
            out.append(int(l))
    return out


def extract_island(grid, buses, status, pg_mw, load_factor, slack_bus: int):
    """Build a self-contained sub-Grid for one electrical island (V2 8.1 steps 3-7).
    Loads (P and Q) are scaled by load_factor, generator set-points by pg_mw (lossless dispatch; the island slack
    is free in AC). Returns (sub_grid, global_branch_idx, global_gen_idx). Only in-service branches inside the island
    are kept, so the sub-grid is connected by construction."""
    from .model import PQ, PV, SLACK
    buses = np.asarray(buses, dtype=int)
    nb = grid.n_bus
    loc = -np.ones(nb, dtype=int); loc[buses] = np.arange(len(buses))
    inb = np.zeros(nb, bool); inb[buses] = True
    br = np.flatnonzero((np.asarray(status) > 0) & inb[grid.br_from] & inb[grid.br_to])
    gi = np.flatnonzero(inb[grid.gen_bus])
    has_gen = np.zeros(nb, bool)
    live = gi[grid.gen_status[gi] > 0]
    has_gen[grid.gen_bus[live]] = True
    bt = np.where(grid.bus_type[buses] == SLACK, PV, grid.bus_type[buses])
    bt = np.where((bt == PV) & ~has_gen[buses], PQ, bt)
    bt[loc[slack_bus]] = SLACK
    f = np.asarray(load_factor)[buses]
    sub = grid.with_(
        name=f"{grid.name}[island]", bus_id=grid.bus_id[buses], bus_type=bt,
        Pd=grid.Pd[buses] * f, Qd=grid.Qd[buses] * f, Gs=grid.Gs[buses], Bs=grid.Bs[buses],
        Vmin=grid.Vmin[buses], Vmax=grid.Vmax[buses],
        br_from=loc[grid.br_from[br]], br_to=loc[grid.br_to[br]], r=grid.r[br], x=grid.x[br], b=grid.b[br],
        tap=grid.tap[br], shift=grid.shift[br], br_status=np.ones(len(br), dtype=int),
        br_is_transformer=grid.br_is_transformer[br], rate_a_case=grid.rate_a_case[br],
        rating_ac=grid.rating_ac[br], rating_dc=grid.rating_dc[br],
        gen_bus=loc[grid.gen_bus[gi]], gen_Pg=np.asarray(pg_mw)[gi], gen_Qg=grid.gen_Qg[gi],
        gen_Pmax=grid.gen_Pmax[gi], gen_Pmin=grid.gen_Pmin[gi], gen_Qmax=grid.gen_Qmax[gi],
        gen_Qmin=grid.gen_Qmin[gi], gen_Vset=grid.gen_Vset[gi], gen_status=grid.gen_status[gi],
        bus_base_kv=None if grid.bus_base_kv is None else grid.bus_base_kv[buses])
    return sub, br, gi
