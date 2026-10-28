"""Tier B: EXACT CLASSICAL EMULATION of ideal Grover dynamics inside the weight-k subspace (V2 13.2, App. C). Not a quantum runtime.
Three equivalent forms (all tested against each other): closed form sin^2((2r+1)theta); class-collapsed recursion (O(1) memory);
full amplitude vector (inversion about the mean)."""
from __future__ import annotations
from math import asin, floor, pi, sqrt
import numpy as np

def theta_of(N: int, M: int) -> float:
    if not 0 <= M <= N or N < 1: raise ValueError("need 0 <= M <= N, N >= 1")
    return asin(sqrt(M / N))

def p_closed(r, N: int, M: int):
    return np.sin((2 * np.asarray(r) + 1) * theta_of(N, M)) ** 2

def optimal_r(N: int, M: int) -> int:
    """V2 12.1: r* = floor(pi/(4 theta)), sin(theta) = sqrt(M/N). (r* ~ pi/(4 theta) - 1/2 is the continuous optimum.) M=0 -> 0."""
    if M == 0: return 0
    return int(floor(pi / (4 * theta_of(N, M))))

def collapsed_trajectory(N: int, M: int, r_max: int):
    """alpha_r (marked amplitude), beta_r (unmarked amplitude); oracle -> (-alpha, beta); mu = (M(-alpha)+(N-M)beta)/N; diffuser 2mu - . (App. C.5)."""
    a = np.empty(r_max + 1); b = np.empty(r_max + 1); a[0] = b[0] = N ** -0.5
    for r in range(r_max):
        ap, bp = -a[r], b[r]; mu = (M * ap + (N - M) * bp) / N; a[r + 1] = 2 * mu - ap; b[r + 1] = 2 * mu - bp
    return a, b, M * a ** 2

def full_vector_trajectory(marked_mask: np.ndarray, r_max: int):
    """Amplitude vectors psi_r over the N weight-k states (rows) and P(marked) per r."""
    mk = np.asarray(marked_mask, bool); N = len(mk); psi = np.full(N, N ** -0.5); rows = [psi.copy()]
    for _ in range(r_max):
        psi = np.where(mk, -psi, psi); psi = 2 * psi.mean() - psi; rows.append(psi.copy())
    R = np.array(rows); return R, (R[:, mk] ** 2).sum(axis=1)

class MarkedSet:
    """Marked ranks inside Omega_k (sorted int64). Samples the measurement outcome after j ideal Grover iterations."""
    def __init__(self, N: int, ranks):
        self.N = int(N); self.ranks = np.unique(np.asarray(ranks, dtype=np.int64)); self.M = int(len(self.ranks))
        if self.M and (self.ranks[0] < 0 or self.ranks[-1] >= self.N): raise ValueError("marked rank out of range")
        self._adj = self.ranks - np.arange(self.M)                      # for mapping the u-th UNMARKED index to a rank
    @property
    def theta(self) -> float: return theta_of(self.N, self.M)
    def p_success(self, j: int) -> float:
        if self.M == 0: return 0.0
        if self.M == self.N: return 1.0
        return float(np.sin((2 * j + 1) * self.theta) ** 2)
    def unmarked_rank(self, u: int) -> int:
        return int(u + np.searchsorted(self._adj, u, side="right"))
    def sample(self, j: int, rng) -> int:
        if rng.random() < self.p_success(j): return int(self.ranks[int(rng.integers(self.M))])
        return self.unmarked_rank(int(rng.integers(self.N - self.M)))
