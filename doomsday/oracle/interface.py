"""The ONLY module search code (qsearch, classical) may import (V2 20 / 20.1). numpy + stdlib only: it must not import
gridtwin. Implementations live in dc_oracle.py / ac_oracle.py and may import gridtwin."""
from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Literal, Protocol, Sequence, runtime_checkable
import numpy as np

class CallCounter:
    """Cost accounting (V2 12.3 / 15.2): cost = UNIQUE outage sets queried, so duplicates and cache hits never inflate it.
    `computed` counts real cascade runs by this oracle instance (not a search cost)."""
    def __init__(self):
        self.reset()
    def reset(self):
        self.queries = 0; self.cache_hits = 0; self.computed = 0; self._unique: set = set()
    def record(self, key: tuple, hit: bool):
        self.queries += 1; self._unique.add(key)
        if hit: self.cache_hits += 1
        else: self.computed += 1
    @property
    def unique(self) -> int: return len(self._unique)
    def snapshot(self) -> dict:
        return {"unique_queried": self.unique, "queries": self.queries, "cache_hits": self.cache_hits, "computed": self.computed}

@dataclass(frozen=True)
class OracleRecord:
    """Everything the oracle reports about one outage set (no frames)."""
    S: float; S0: float; C: float; A: float; rounds: int; status: str
    S_total: float | None; nonconv_flag: bool; ladder_step: int | None; exhausted: bool; pmin_violation: bool; n_trips: int
    def to_dict(self) -> dict: return dict(self.__dict__)

@dataclass(frozen=True)
class GridFeatures:
    """Plain-numpy structural data for structure-exploiting methods (LODF pool, ML screen, MILP, surrogate, micro-oracle).
    A COPY of data: holding it does not couple search code to the grid implementation (approved resolution B)."""
    L: int; B: int
    bus_id: np.ndarray; branch_from_bus: np.ndarray; branch_to_bus: np.ndarray
    branch_keys: tuple; is_bridge: np.ndarray; is_transformer: np.ndarray
    base_flow_dc_mw: np.ndarray; base_loading_dc: np.ndarray; base_loading_ac: np.ndarray
    rating_dc_mw: np.ndarray; rating_ac_mva: np.ndarray
    phi: np.ndarray                     # L x L branch-to-branch sensitivity (V2 6.2); lodf_{l,m} = phi[l,m]/(1-phi[m,m])
    p_inj_mw: np.ndarray; load_mw: np.ndarray; gen_pmax_mw: np.ndarray; gen_bus_id: np.ndarray
    base_mva: float; grid_hash: str; order_fingerprint: str
    branch_x_pu: np.ndarray | None = None   # branch reactance (p.u.) -> DC susceptance 1/x; needed ONLY by the MILP baseline. Optional so
                                            # features/tables produced before Phase 4 still load (None => MILP refuses loudly)

@runtime_checkable
class Space(Protocol):
    L: int; k: int
    @property
    def N(self) -> int: ...
    def validate(self, outage) -> tuple: ...
    def rank(self, outage) -> int: ...
    def unrank(self, r) -> tuple: ...
    def unrank_batch(self, ranks) -> np.ndarray: ...

@runtime_checkable
class Oracle(Protocol):
    fidelity: Literal["dc", "ac"]
    space: Space
    cost_counter: CallCounter
    namespace: str                                   # deterministic cache namespace (grid hash + config hash + code version)
    def severity(self, outage: Sequence[int]) -> float: ...                 # S(x) in [0,1]
    def severity_batch(self, outages: np.ndarray) -> np.ndarray: ...        # shape (n,k) -> (n,)
    def evaluate(self, outage: Sequence[int]) -> OracleRecord: ...
    def is_high_severity(self, outage: Sequence[int], tau: float) -> bool: ...   # f_tau(x) = [S >= tau]
    def exceeds(self, outage: Sequence[int], y: float) -> bool: ...              # f_y(x) = [S > y] (strict, adaptive form)
    def structure(self) -> GridFeatures: ...
    def with_k(self, k: int) -> "Oracle": ...                                   # same predicate on another cardinality (beam search levels)


# ---------------------------------------------------------------------------------------------------------------------
# Common search plumbing (shared by classical/ and qsearch/): budgeted unique-evaluation accounting and the result record.
# ---------------------------------------------------------------------------------------------------------------------
BAND = 1e-9

class BudgetExhausted(Exception):
    """Raised by CountedEvaluator when a NEW unique evaluation would exceed the budget."""

class TargetReached(Exception):
    """Raised when stop_on_target is set and S >= target - band has been observed."""

@dataclass
class SearchResult:
    algorithm: str; params: dict; grid: str; fidelity: str; oracle_kind: str; L: int; k: int; N: int
    objective: str; seed: int | None; budget: int | None
    oracle_calls: int                # UNIQUE (j, set) evaluations sent to the oracle = the cost measure (V2 15.2)
    candidate_evaluations: int       # evaluation REQUESTS made by the algorithm (duplicates served from memo included)
    runtime_s: float; cpu_s: float
    best_severity: float; best_contingency: tuple; best_rank: int | None
    found_target: bool | None; discovery_calls: int | None; calls_to_within_1pct: int | None
    certified_stop_calls: int | None  # only algorithms with a principled stopping rule (brute force) set this
    completed: bool                   # algorithm terminated by its own rule (not by the budget)
    trace: list; aux: dict; exact: bool | None; label: str
    evaluated: dict | None = None     # {set: S} of every unique k-set evaluated (only if requested; never serialised)
    def to_dict(self) -> dict:
        d = dict(self.__dict__); d.pop("evaluated"); d["best_contingency"] = list(self.best_contingency); return d

class CountedEvaluator:
    """Wraps an Oracle for one search run. Memoises, so cost = unique sets; enforces the budget; records the
    improvement trace (calls, best S), and discovery of `target` (V2 12.3: discovery calls)."""
    def __init__(self, oracle, budget: int | None = None, target: float | None = None, stop_on_target: bool = False, band: float = BAND):
        self.oracle, self.space, self.k = oracle, oracle.space, oracle.space.k
        self.budget, self.target, self.stop_on_target, self.band = budget, target, stop_on_target, band
        self._orc = {self.k: oracle}; self.memo: dict = {}
        self.unique = 0; self.requests = 0
        self.best = -np.inf; self.best_set = None
        self.trace: list = []; self.discovery_calls = None; self.within1pct_calls = None

    def _oracle_for(self, j: int):
        if j not in self._orc:
            self._orc[j] = self.oracle.with_k(j)
        return self._orc[j]

    def _note(self, j, key, S):
        if j != self.k:
            return
        if S > self.best + self.band or self.best_set is None:
            self.best, self.best_set = float(S), key; self.trace.append([self.unique, float(S)])
        if self.target is not None:
            if self.discovery_calls is None and S >= self.target - self.band:
                self.discovery_calls = self.unique
            if self.within1pct_calls is None and S >= 0.99 * self.target - self.band:
                self.within1pct_calls = self.unique
            if self.stop_on_target and self.discovery_calls is not None:
                raise TargetReached()

    def batch(self, X, j: int | None = None) -> np.ndarray:
        """Evaluate rows of X (cardinality j, default k). New unique sets are evaluated and accounted for IN REQUEST ORDER:
        the i-th new set gets unique-count base+i+1 (this is what the trace and discovery counts record)."""
        j = self.k if j is None else j
        X = np.asarray(X)
        if X.ndim != 2 or X.shape[1] != j:
            raise ValueError(f"expected shape (n,{j}), got {X.shape}")
        keys = [tuple(sorted(int(v) for v in row)) for row in X]
        self.requests += len(keys)
        new, seen = [], set()
        for key in keys:
            if (j, key) not in self.memo and key not in seen:
                new.append(key); seen.add(key)
        room = len(new) if self.budget is None else max(0, self.budget - self.unique)
        todo = new[:room]
        base = self.unique
        first_idx = {}
        for i, key in enumerate(keys): first_idx.setdefault(key, i)
        if todo:
            vals = self._oracle_for(j).severity_batch(np.array(todo, dtype=np.int64))
            for pos, (key, v) in enumerate(zip(todo, vals)):
                self.memo[(j, key)] = float(v); self.unique = base + pos + 1
                try:
                    self._note(j, key, float(v))                # may raise TargetReached (after recording this set)
                except TargetReached:
                    self.requests -= len(keys) - (first_idx[key] + 1)      # requests after the discovering set were never served
                    raise
        if len(todo) < len(new):
            self.requests -= len(keys) - first_idx[new[len(todo)]]          # the refused request and everything after it
            raise BudgetExhausted()
        return np.array([self.memo[(j, key)] for key in keys], dtype=np.float64)

    def __call__(self, outage, j: int | None = None) -> float:
        j = self.k if j is None else j
        return float(self.batch(np.array([sorted(int(v) for v in outage)], dtype=np.int64), j)[0])

    @property
    def remaining(self) -> int | None:
        return None if self.budget is None else self.budget - self.unique

    def evaluated_sets(self) -> dict:
        return {key: v for (j, key), v in self.memo.items() if j == self.k}
