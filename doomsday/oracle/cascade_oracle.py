"""Common implementation of the Oracle protocol on top of the cascade engine (DC or AC fidelity)."""
from __future__ import annotations
import numpy as np
from ..gridtwin.base import BasePoint
from ..gridtwin.cascade import CascadeEngine
from ..gridtwin.contingency import ContingencySpace, branch_keys, space_for_grid
from ..gridtwin.dc import DCSensitivities
from ..gridtwin.identity import grid_content_hash, order_fingerprint
from ..gridtwin.islanding import bridges
from ..gridtwin.security import loading
from .cache import CacheNamespaceError, ResultCache
from .hashing import make_namespace
from .interface import CallCounter, GridFeatures, OracleRecord

class CascadeOracle:
    fidelity: str = ""

    def __init__(self, bp: BasePoint, cfg, k: int, cache: ResultCache | None = None, use_cache: bool = True,
                 fast_path: bool = False, _engine: CascadeEngine | None = None, _namespace: str | None = None,
                 _family: CallCounter | None = None):
        if self.fidelity not in ("dc", "ac"):
            raise TypeError("use DCOracle or ACOracle")
        self.bp, self.cfg, self.fast_path = bp, cfg, bool(fast_path)
        self._engine = _engine or CascadeEngine(bp, cfg)
        ghash = bp.grid_hash or grid_content_hash(bp.grid); ofp = bp.order_fingerprint or order_fingerprint(bp.grid)
        self.namespace = _namespace or make_namespace(ghash, ofp, cfg, self.fidelity, self.fast_path)
        self.space: ContingencySpace = space_for_grid(bp.grid, k)
        self.cost_counter = CallCounter()                 # this instance (one cardinality): unique SETS queried here
        self.family_counter = _family if _family is not None else CallCounter()   # shared by all with_k siblings: unique (k, set)
        if cache is not None and cache.namespace != self.namespace:
            raise CacheNamespaceError("cache namespace does not match this oracle's grid/config/code namespace")
        self.cache = (cache if cache is not None else ResultCache(self.namespace)) if use_cache else None
        self._structure = None

    # ---- pure function of (outage set, configuration) ----------------------------------------------------------
    def _compute(self, outage: tuple) -> OracleRecord:
        r = self._engine.run(list(outage), mode=self.fidelity, fast=self.fast_path)
        return OracleRecord(S=r.S, S0=r.S0, C=r.C, A=r.A, rounds=r.rounds, status=r.status, S_total=r.S_total,
                            nonconv_flag=bool(r.flags["nonconv_flag"]), ladder_step=r.ladder_step,
                            exhausted=bool(r.flags["exhausted"]), pmin_violation=bool(r.flags["pmin_violation"]),
                            n_trips=int(sum(len(t) for t in r.trips_per_round)))

    def evaluate(self, outage) -> OracleRecord:
        key = self.space.validate(outage)                      # exactly-k validation + canonical sorted tuple
        rec = self.cache.get(key) if self.cache is not None else None
        hit = rec is not None
        if rec is None:
            rec = self._compute(key)
            if self.cache is not None:
                self.cache.put(key, rec)
        self.cost_counter.record(key, hit)
        self.family_counter.record((self.space.k, key), hit)
        return rec

    def severity(self, outage) -> float:
        return self.evaluate(outage).S                         # AC: S_ladder (V2 8.6: rankings use S_ladder)

    def severity_batch(self, outages) -> np.ndarray:
        a = np.asarray(outages)
        if a.ndim != 2 or a.shape[1] != self.space.k:
            raise ValueError(f"outages must have shape (n, {self.space.k}), got {a.shape}")
        return np.array([self.evaluate(row).S for row in a], dtype=np.float64)

    def severity_ranks(self, ranks) -> np.ndarray:
        return self.severity_batch(self.space.unrank_batch(ranks))

    def is_high_severity(self, outage, tau: float) -> bool:
        return self.severity(outage) >= tau - self.cfg.numerics.tie_band          # f_tau = [S >= tau], tie-band tolerant

    def exceeds(self, outage, y: float) -> bool:
        return self.severity(outage) > y + self.cfg.numerics.tie_band            # strict f_y = [S > y]: ties never count

    def is_cascade_driven(self, outage, tau: float, delta: float) -> bool:
        r = self.evaluate(outage); tb = self.cfg.numerics.tie_band
        return r.S >= tau - tb and r.C >= delta - tb

    def cascade(self, outage):
        """Full CascadeResult with frames for display/animation. Bypasses cache and cost accounting."""
        return self._engine.run(list(self.space.validate(outage)), mode=self.fidelity, fast=self.fast_path)

    def with_k(self, k: int) -> "CascadeOracle":
        """Sibling oracle for another cardinality: shares engine and cache (keys are the sets themselves), fresh counter."""
        return type(self)(self.bp, self.cfg, k, cache=self.cache, use_cache=self.cache is not None,
                          fast_path=self.fast_path, _engine=self._engine, _namespace=self.namespace, _family=self.family_counter)

    def structure(self) -> GridFeatures:
        if self._structure is None:
            g, bp = self.bp.grid, self.bp
            br = set(bridges(g)); sens = self._engine.sens
            lo = lambda arr: np.array(arr, dtype=np.float64)
            self._structure = GridFeatures(
                L=g.n_branch, B=g.n_bus, bus_id=g.bus_id.copy(),
                branch_from_bus=g.bus_id[g.br_from].copy(), branch_to_bus=g.bus_id[g.br_to].copy(),
                branch_keys=tuple(branch_keys(g)), is_bridge=np.array([l in br for l in range(g.n_branch)]),
                is_transformer=g.br_is_transformer.copy(), base_flow_dc_mw=lo(bp.dc.flow_mw),
                base_loading_dc=lo(loading(bp, "dc")[0]), base_loading_ac=lo(loading(bp, "ac")[0]),
                rating_dc_mw=lo(g.rating_dc), rating_ac_mva=lo(g.rating_ac), phi=lo(sens.Phi),
                p_inj_mw=lo(bp.dc_injections_mw), load_mw=lo(g.Pd),
                gen_pmax_mw=lo(g.gen_Pmax), gen_bus_id=g.bus_id[g.gen_bus].copy(), base_mva=float(g.base_mva),
                grid_hash=bp.grid_hash, order_fingerprint=bp.order_fingerprint, branch_x_pu=lo(g.x))
            for a in vars(self._structure).values():
                if isinstance(a, np.ndarray): a.setflags(write=False)
        return self._structure
