"""Deterministic quasi-steady-state cascade (V2 section 8). One engine, mode = 'dc' | 'ac'.

Implementation decisions where V2 is silent (documented in docs/CASCADE_DECISIONS.md):
  * State carried across rounds: per-bus load factor (monotone non-increasing: curtailed/lost load is never restored)
    and per-generator set-point (lossless dispatch). Balance is applied per island every round.
  * Dispatch is lossless: base slack generation is reduced by total AC losses (resolution C), so a no-outage AC
    cascade reproduces the base AC state; in AC the island slack absorbs losses.
  * Island slack = bus of the largest-Pmax in-service generator in the island (V2 7); ties -> lowest generator index.
    The original base slack bus is NOT given priority.
  * rounds = number of solved power-flow rounds. EXHAUSTED: S is taken from the last SOLVED round.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .ac import scheduled, solve_ac
from .dc import DCSensitivities, dc_power_flow
from .contingency import branch_keys
from .islanding import connected_components, extract_island
from .severity import severity_metrics

TOL_BAL = 1e-9
FP_INT_BITS = 4                     # V2 17.1: 4 integer bits (incl. sign), b-4 fractional, per unit on base MVA

def quantize_pu(x, bits: int, flags: dict | None = None):
    """Two's-complement Q(4, bits-4) round-to-nearest with saturation (counted in flags['fixed_point_saturations']).
    Models input/output quantisation of the DC flow solve; it is NOT a bit-exact model of every reversible arithmetic step."""
    lsb = 2.0 ** -(bits - FP_INT_BITS); hi = 2.0 ** (FP_INT_BITS - 1) - lsb; lo = -(2.0 ** (FP_INT_BITS - 1))
    y = np.round(np.asarray(x, float) / lsb) * lsb
    if flags is not None:
        n = int(np.sum((y > hi) | (y < lo)))
        if n: flags["fixed_point_saturations"] = flags.get("fixed_point_saturations", 0) + n
    return np.clip(y, lo, hi)

@dataclass
class CascadeResult:
    outage: list
    mode: str
    policy: str
    S: float
    S0: float
    C: float
    A: float
    rounds: int
    trips_per_round: list
    islands_per_round: list
    status: str                     # STABLE | EXHAUSTED | TOTAL_LOSS
    flags: dict
    S_total: float | None           # AC only: failed islands fully lost (bound); equals S when no ladder was used
    ladder_step: int | None
    served_fraction_by_round: list
    final_out_of_service: list
    frames: list = field(default_factory=list)
    balance_log: list | None = None

    def to_dict(self, frames: bool = True) -> dict:
        d = {"outage": self.outage, "mode": self.mode, "policy": self.policy,
             "metrics": {"S": self.S, "S0": self.S0, "C": self.C, "A": self.A, "rounds": self.rounds,
                         "status": self.status, "ladder_step": self.ladder_step, "S_total": self.S_total},
             "trips_per_round": self.trips_per_round, "islands_per_round": self.islands_per_round,
             "flags": self.flags, "final_out_of_service": self.final_out_of_service}
        if frames:
            d["frames"] = self.frames
        return d

def lossless_dispatch(bp) -> np.ndarray:
    """Base generator set-points with the slack-bus generator reduced by the AC losses (so sum(Pg) = sum(Pd))."""
    g = bp.grid
    pg = g.gen_Pg.astype(np.float64).copy()
    idx = [i for i in range(g.n_gen) if g.gen_bus[i] == g.slack_bus and g.gen_status[i] > 0]
    pg[idx[0]] -= bp.dc_loss_pickup_mw
    return pg

class CascadeEngine:
    def __init__(self, bp, cfg):
        self.bp, self.g, self.cfg = bp, bp.grid, cfg
        self.pg0 = lossless_dispatch(bp)
        self.initial_load = float(self.g.total_load_mw)
        self._sens = None
        keys = branch_keys(self.g)
        order = sorted(range(self.g.n_branch), key=lambda l: keys[l])
        self.key_rank = np.empty(self.g.n_branch, dtype=np.int64); self.key_rank[order] = np.arange(self.g.n_branch)

    @property
    def sens(self) -> DCSensitivities:
        if self._sens is None:
            self._sens = DCSensitivities(self.g, self.bp.dc_injections_mw, self.g.br_status)
        return self._sens

    # ---- balance (V2 8.2 steps 5-6) -------------------------------------------------------------------------------
    def _balance(self, buses, gens, pg, factor, flags):
        g, cc = self.g, self.cfg.cascade
        load = float((g.Pd[buses] * factor[buses]).sum())
        gen = float(pg[gens].sum())
        delta = gen - load
        if abs(delta) <= TOL_BAL:
            return
        if delta > 0:                                    # surplus: scale generation down pro-rata
            pg[gens] = pg[gens] * (load / gen) if gen > 0 else pg[gens]
            if np.any(pg[gens] < g.gen_Pmin[gens] - 1e-9):
                flags["pmin_violation"] = True
            return
        deficit = -delta
        if cc.redispatch == "up_and_down":
            head = np.maximum(g.gen_Pmax[gens] - pg[gens], 0.0)
            H = float(head.sum())
            if H > 0:
                add = min(deficit, H)
                pg[gens] = pg[gens] + add * head / H
                deficit -= add
        if deficit > TOL_BAL:                            # remaining deficit: uniform pro-rata load curtailment
            factor[buses] = factor[buses] * ((load - deficit) / load)

    # ---- island power flow --------------------------------------------------------------------------------------
    @staticmethod
    def _island_slack(g, gens):
        j = max(gens, key=lambda i: (g.gen_Pmax[i], -int(g.bus_id[g.gen_bus[i]]), -i))   # ties -> lowest bus id (table-order independent)
        return int(g.gen_bus[j])

    def _ac_try(self, sub, nm):
        res = solve_ac(sub, tol=nm.ac_tol_pu, max_iter=nm.ac_max_iter)             # flat start
        if res.converged:
            return res
        p = sub.bus_gen_pg_mw() - sub.Pd                                           # retry once from DC-angle init
        th = dc_power_flow(sub, p).theta
        _, vset = scheduled(sub)
        return solve_ac(sub, tol=nm.ac_tol_pu, max_iter=nm.ac_max_iter, V0=vset * np.exp(1j * th))

    def _island_flows(self, mode, buses, gens, status, pg, factor, r, flags, ladder_mode, events):
        """Return (loading_u over sub-branches, global branch idx) and possibly updates factor (ladder)."""
        g, nm = self.g, self.cfg.numerics
        slack = self._island_slack(g, gens)
        sub, br, _ = extract_island(g, buses, status, pg, factor, slack)
        if len(br) == 0:
            return br, np.zeros(0)
        if mode == "dc":
            q = nm.fixed_point_bits
            if q is None:
                fl = dc_power_flow(sub, sub.bus_gen_pg_mw() - sub.Pd).flow_mw
                return br, np.abs(fl) / g.rating_dc[br]
            base = g.base_mva                                # (E12) Q-format: injections, flows and ratings quantised
            pin = quantize_pu((sub.bus_gen_pg_mw() - sub.Pd) / base, q, flags) * base
            fl = quantize_pu(dc_power_flow(sub, pin).flow_mw / base, q, flags) * base
            rt = np.maximum(quantize_pu(g.rating_dc[br] / base, q, flags), 2.0 ** -(q - 4)) * base
            return br, np.abs(fl) / rt
        res = self._ac_try(sub, nm)
        if res.converged:
            return br, res.apparent_mva / g.rating_ac[br]
        flags["nonconv_flag"] = True                                               # STATIC_INFEASIBLE (V2 8.3, 8.6)
        step = self.cfg.cascade.ladder_step
        if ladder_mode == "ladder":
            nsteps = int(round(1.0 / step))
            for j in range(1, nsteps):
                c = 1.0 - step * j
                sub_j = sub.with_(Pd=sub.Pd * c, Qd=sub.Qd * c)
                resj = self._ac_try(sub_j, nm)
                if resj.converged:
                    factor[buses] *= c
                    events.append({"round": r, "step": j, "scale": c, "buses": [int(g.bus_id[b]) for b in buses]})
                    flags["ladder_step"] = flags.get("ladder_step") or j
                    return br, resj.apparent_mva / g.rating_ac[br]
        factor[buses] = 0.0                                                         # de-energize the island
        events.append({"round": r, "step": "deenergized", "scale": 0.0, "buses": [int(g.bus_id[b]) for b in buses]})
        return br, np.zeros(len(br))

    # ---- main loop (V2 8.1) ------------------------------------------------------------------------------------
    def run(self, outage, mode: str | None = None, policy: str | None = None, ladder: str = "ladder",
            fast: bool = False, record_balance: bool = False, _bound: bool = True) -> CascadeResult:
        g, cc, nm = self.g, self.cfg.cascade, self.cfg.numerics
        mode = mode or cc.mode_default
        policy = policy or cc.trip_policy
        if mode not in ("dc", "ac"):
            raise ValueError("mode must be 'dc' or 'ac'")
        outage = [int(i) for i in outage]
        if len(set(outage)) != len(outage) or any(i < 0 or i >= g.n_branch or g.br_status[i] == 0 for i in outage):
            raise ValueError(f"invalid outage set {outage}")
        status = g.br_status.copy(); status[outage] = 0
        pg = self.pg0.copy(); factor = np.ones(g.n_bus)
        flags = {"pmin_violation": False, "nonconv_flag": False, "ladder_step": None, "exhausted": False}
        events, frames, trips_pr, isl_pr, served_pr, blog = [], [], [], [], [], ([] if record_balance else None)
        served_mw = 0.0; out_status = None
        for r in range(cc.max_rounds):
            ncomp, labels = connected_components(g.n_bus, g.br_from, g.br_to, status)
            u = np.zeros(g.n_branch); served_mw = 0.0; energized = []
            base_state = (np.array_equal(pg, self.pg0) and np.all(factor == 1.0))
            fast_ok = fast and mode == "dc" and ncomp == 1 and base_state and nm.fixed_point_bits is None and \
                bool(np.all(status[g.br_status > 0] >= 0))
            for c in range(ncomp):
                buses = np.flatnonzero(labels == c)
                gens = [i for i in range(g.n_gen) if g.gen_status[i] > 0 and g.gen_Pmax[i] > 0 and labels[g.gen_bus[i]] == c]
                if not gens:
                    factor[buses] = 0.0                      # dead island: all load lost, no flow solved
                    if blog is not None:
                        blog.append({"round": r, "buses": buses.tolist(), "dead": True, "gen_mw": 0.0, "load_mw": 0.0})
                    continue
                gens = np.array(gens)
                self._balance(buses, gens, pg, factor, flags)
                if blog is not None:
                    blog.append({"round": r, "buses": buses.tolist(), "dead": False, "gen_mw": float(pg[gens].sum()),
                                 "load_mw": float((g.Pd[buses] * factor[buses]).sum())})
                if fast_ok:
                    K = np.flatnonzero((g.br_status > 0) & (status == 0))
                    try:
                        f = self.sens.post_outage_flows(K)
                        ok_fast = True
                    except np.linalg.LinAlgError:
                        ok_fast = False
                    if ok_fast:
                        m = status > 0
                        u[m] = np.abs(f[m]) / g.rating_dc[m]
                    else:
                        br, uu = self._island_flows(mode, buses, list(gens), status, pg, factor, r, flags, ladder, events)
                        u[br] = uu
                else:
                    br, uu = self._island_flows(mode, buses, list(gens), status, pg, factor, r, flags, ladder, events)
                    u[br] = uu
                served_mw += float((g.Pd[buses] * factor[buses]).sum())
                energized.extend(buses.tolist())
            over = np.flatnonzero((status > 0) & (u > cc.trip_factor + nm.overload_tol))
            if r == 0:
                served0 = served_mw
            served_pr.append(served_mw / self.initial_load); isl_pr.append(int(ncomp))
            if over.size == 0 or served_mw <= 0.0:
                tripped = []
            elif policy == "all_overloaded":
                tripped = over.tolist()
            else:                                            # most_overloaded_first; ties -> lowest branch key
                best = over[u[over] == u[over].max()]             # exact ties -> lowest branch KEY (file-order independent)
                tripped = [int(best[np.argmin(self.key_rank[best])])]
            frames.append({"round": r, "out_of_service": np.flatnonzero(status == 0).tolist(),
                           "tripped": tripped, "overloaded": over.tolist(),
                           "load_served": served_mw / self.initial_load, "islands": int(ncomp),
                           "loading": {str(int(l)): float(u[l]) for l in np.flatnonzero(status > 0)},
                           "energized_buses": [int(g.bus_id[b]) for b in sorted(energized)]})
            trips_pr.append(tripped)
            if served_mw <= 0.0:
                out_status = "TOTAL_LOSS"; break
            if over.size == 0:
                out_status = "STABLE"; break
            status[tripped] = 0
        else:
            out_status = "EXHAUSTED"; flags["exhausted"] = True
        m = severity_metrics(served_mw, served0, self.initial_load)
        S_total = None
        if mode == "ac":
            S_total = m["S"]
            if events and ladder == "ladder" and _bound:
                S_total = self.run(outage, mode, policy, ladder="total_loss", _bound=False).S
        flags["ladder_events"] = events
        return CascadeResult(outage=sorted(outage), mode=mode, policy=policy, S=m["S"], S0=m["S0"], C=m["C"], A=m["A"],
                             rounds=len(frames), trips_per_round=trips_pr, islands_per_round=isl_pr, status=out_status,
                             flags=flags, S_total=S_total, ladder_step=flags["ladder_step"],
                             served_fraction_by_round=served_pr, final_out_of_service=np.flatnonzero(status == 0).tolist(),
                             frames=frames, balance_log=blog)

def run_cascade(bp, outage, cfg, **kw) -> CascadeResult:
    """Convenience wrapper (builds an engine per call; reuse CascadeEngine for batches)."""
    return CascadeEngine(bp, cfg).run(outage, **kw)
