"""Deterministic, order-independent content hash of INPUT grid data + a separate branch-order fingerprint.
Derived/solved quantities (ratings, solved slack output) are deliberately excluded: they follow from the inputs and the
configuration, and are reproducible to tolerance (V2 8.8), not bit-identical across machines."""
from __future__ import annotations
import hashlib, json
from .contingency import branch_keys, key_str

def _f(v) -> str:
    return repr(float(v))

def grid_content_hash(grid) -> str:
    keys = branch_keys(grid)
    buses = sorted((int(grid.bus_id[i]), int(grid.bus_type[i]), _f(grid.Pd[i]), _f(grid.Qd[i]), _f(grid.Gs[i]), _f(grid.Bs[i]),
                    _f(grid.Vmin[i]), _f(grid.Vmax[i])) for i in range(grid.n_bus))
    gens = sorted((int(grid.bus_id[grid.gen_bus[i]]), _f(grid.gen_Pg[i]), _f(grid.gen_Pmax[i]), _f(grid.gen_Pmin[i]),
                   _f(grid.gen_Qg[i]), _f(grid.gen_Qmax[i]), _f(grid.gen_Qmin[i]), _f(grid.gen_Vset[i]), int(grid.gen_status[i]))
                  for i in range(grid.n_gen))
    brs = sorted((keys[l], _f(grid.r[l]), _f(grid.x[l]), _f(grid.b[l]), _f(grid.tap[l]), _f(grid.shift[l]),
                  int(grid.br_status[l]), _f(grid.rate_a_case[l])) for l in range(grid.n_branch))
    blob = json.dumps({"base_mva": _f(grid.base_mva), "buses": buses, "gens": gens,
                       "branches": [[list(k)] + list(rest) for k, *rest in brs]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()

def order_fingerprint(grid) -> str:
    """Hash of the ORDERED branch-key list: differs whenever the case-file branch order differs."""
    blob = json.dumps([key_str(k) for k in branch_keys(grid)], separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
