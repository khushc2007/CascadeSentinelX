"""Tier A1 toy problems: m candidate branches, exactly k outages (N = C(m,k) = 15..56 for m=6..8). The marked set is computed CLASSICALLY through
the oracle and compiled into the phase oracle (a lookup): the toy demonstrates circuit correctness, never a speedup. The candidate shortlist
is supplied by the caller and is NEVER evidence of scaling (V2 5.4)."""
from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
import numpy as np
from ..oracle.interface import BAND
from .circuits import grover_circuit, check_masks
from .emulation import full_vector_trajectory
from .statevec import run

@dataclass
class ToyProblem:
    m: int; k: int; candidates: tuple; masks: list; global_sets: list; S: np.ndarray; marked_masks: list; rule: str
    @property
    def N(self) -> int: return len(self.masks)
    @property
    def M(self) -> int: return len(self.marked_masks)
    def marked_mask_bool(self) -> np.ndarray:
        mm = set(self.marked_masks); return np.array([x in mm for x in self.masks])

def build_toy(oracle, candidates, rule: str = "max", tau: float | None = None) -> ToyProblem:
    cand = tuple(int(c) for c in candidates); m, k = len(cand), oracle.space.k
    if len(set(cand)) != m: raise ValueError("duplicate candidates")
    if not 1 <= k <= m: raise ValueError("need 1 <= k <= m")
    subsets = list(combinations(range(m), k))                           # local qubit subsets, lexicographic
    masks = [sum(1 << q for q in s) for s in subsets]
    gsets = [tuple(sorted(cand[q] for q in s)) for s in subsets]
    S = oracle.severity_batch(np.array(gsets, dtype=np.int64))        # classical computation of the predicate (Tier A1 lookup)
    if rule == "max": sel = S >= S.max() - BAND
    elif rule == "threshold":
        if tau is None: raise ValueError("tau required")
        sel = S >= tau - BAND
    else: raise ValueError("rule must be 'max' or 'threshold'")
    return ToyProblem(m, k, cand, masks, gsets, S, [mk for mk, s in zip(masks, sel) if s], rule)

def circuit_probabilities(toy: ToyProblem, r_max: int) -> dict:
    """Run the gate-level Grover circuit (NumPy statevector) for r = 0..r_max; returns P(marked) per r, per-state probabilities over the
    N weight-k states, and the probability leaked OUTSIDE the weight-k subspace (must be ~0)."""
    idx = {mk: i for i, mk in enumerate(toy.masks)}; wk = np.array([bin(b).count("1") == toy.k for b in range(1 << toy.m)])
    pm, per_state, leak = [], [], []
    for r in range(r_max + 1):
        st = run(grover_circuit(toy.m, toy.k, toy.marked_masks, r)); p = np.abs(st) ** 2
        per_state.append(np.array([p[mk] for mk in toy.masks])); pm.append(float(sum(p[mk] for mk in toy.marked_masks))); leak.append(float(p[~wk].sum()))
    return {"p_marked": np.array(pm), "per_state": np.array(per_state), "leak_outside_weight_k": np.array(leak)}

def emulation_probabilities(toy: ToyProblem, r_max: int) -> dict:
    R, pm = full_vector_trajectory(toy.marked_mask_bool(), r_max); return {"p_marked": pm, "per_state": R ** 2}
