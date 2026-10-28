"""Predicate table (Tier B input) built ONLY through oracle.interface, and marked-set constructors for f_tau = [S >= tau] and f_y = [S > y]."""
from __future__ import annotations
import numpy as np
from ..oracle.interface import BAND
from .emulation import MarkedSet

class PredicateTable:
    def __init__(self, S: np.ndarray, band: float = BAND, construction_evals: int = 0):
        self.S = np.asarray(S, dtype=np.float64); self.N = len(self.S); self.band = band; self.construction_evals = int(construction_evals)
        self.Smax = float(self.S.max()) if self.N else float("nan"); self._cache: dict = {}
    @classmethod
    def from_oracle(cls, oracle, chunk: int = 100_000) -> "PredicateTable":
        sp, N = oracle.space, oracle.space.N; S = np.empty(N)
        for s in range(0, N, chunk):
            e = min(s + chunk, N); S[s:e] = oracle.severity_batch(sp.unrank_batch(np.arange(s, e, dtype=np.int64)))
        return cls(S, construction_evals=N)
    def marked_gt(self, y: float) -> MarkedSet:          # f_y(x) = [S > y]  (strict; ties never improve)
        key = ("gt", y)
        if key not in self._cache: self._cache[key] = MarkedSet(self.N, np.flatnonzero(self.S > y + self.band))
        return self._cache[key]
    def marked_ge(self, tau: float) -> MarkedSet:        # f_tau(x) = [S >= tau]
        key = ("ge", tau)
        if key not in self._cache: self._cache[key] = MarkedSet(self.N, np.flatnonzero(self.S >= tau - self.band))
        return self._cache[key]
    def verify_gt(self, x: int, y: float) -> bool: return bool(self.S[x] > y + self.band)
    def verify_ge(self, x: int, tau: float) -> bool: return bool(self.S[x] >= tau - self.band)
