"""Quadratic surrogate of the cascade severity for QAOA (V2 14.1): S_hat(x) = c0 + sum_i h_i x_i + sum_{(i,j) in P} J_ij x_i x_j.
Fitted by ridge regression on sampled (x, S) pairs. QAOA optimises THIS surrogate, never S itself. numpy only (qsearch boundary rule)."""
from __future__ import annotations
from itertools import combinations
import numpy as np

def pair_set(L: int, features=None, mode: str = "all", lodf_top: int | None = None) -> list:
    """Quadratic support. mode='all': every pair (V2: exact for k=2). mode='sparse': pairs that are neighbours (share a bus), parallel
    (same end buses) or among the `lodf_top` largest |LODF| couplings (V2 14.1 sparsification). `features` is an oracle GridFeatures."""
    if mode == "all": return list(combinations(range(L), 2))
    if features is None: raise ValueError("sparse pair set needs GridFeatures")
    f, t = np.asarray(features.branch_from_bus), np.asarray(features.branch_to_bus); P = set()
    for i, j in combinations(range(L), 2):
        if {f[i], t[i]} & {f[j], t[j]}: P.add((i, j))                     # neighbours or parallel
    phi = np.asarray(features.phi); d = 1 - np.diag(phi); lodf = np.zeros((L, L))
    for m in range(L):
        if abs(d[m]) > 1e-9: lodf[:, m] = phi[:, m] / d[m]
    c = np.maximum(np.abs(lodf), np.abs(lodf.T)); np.fill_diagonal(c, 0)
    cand = sorted(((c[i, j], i, j) for i, j in combinations(range(L), 2)), reverse=True)[: (lodf_top if lodf_top is not None else 2 * L)]
    P |= {(i, j) for _, i, j in cand}
    return sorted(P)

class QuadraticSurrogate:
    def __init__(self, L: int, pairs: list, ridge: float = 1e-6):
        self.L, self.pairs, self.ridge = int(L), list(pairs), float(ridge); self.coef = None; self.fit_info = {}
    def design(self, X: np.ndarray) -> np.ndarray:
        """X: (n, k) outage index sets -> design matrix [1, x_1..x_L, x_i x_j for (i,j) in pairs]."""
        X = np.asarray(X); n = len(X); B = np.zeros((n, self.L)); B[np.repeat(np.arange(n), X.shape[1]), X.ravel()] = 1.0
        Q = np.stack([B[:, i] * B[:, j] for i, j in self.pairs], axis=1) if self.pairs else np.zeros((n, 0))
        return np.hstack([np.ones((n, 1)), B, Q])
    def fit(self, X, y) -> "QuadraticSurrogate":
        A = self.design(X); y = np.asarray(y, float); p = A.shape[1]
        reg = self.ridge * np.eye(p); reg[0, 0] = 0.0                       # do not shrink the intercept
        self.coef = np.linalg.solve(A.T @ A + reg, A.T @ y)
        sv = np.linalg.svd(A, compute_uv=False); tol = sv.max() * max(A.shape) * np.finfo(float).eps
        self.fit_info = {"n_train": int(len(y)), "n_params": int(p), "effective_rank": int((sv > tol).sum()), "ridge": self.ridge,
                         "note": "with |x| = k fixed, constant/linear/quadratic columns are partly collinear (V2 14.1); ridge resolves it"}
        return self
    def predict(self, X) -> np.ndarray: return self.design(X) @ self.coef
    def ising(self) -> dict:
        """Coefficients (c0, h, J) of S_hat as a function of bits x in {0,1}."""
        c0 = float(self.coef[0]); h = self.coef[1: 1 + self.L].copy(); J = {pr: float(v) for pr, v in zip(self.pairs, self.coef[1 + self.L:])}
        return {"c0": c0, "h": h, "J": J}

def r2(y, yhat) -> float:
    y, yhat = np.asarray(y, float), np.asarray(yhat, float); ss = ((y - yhat) ** 2).sum(); st = ((y - y.mean()) ** 2).sum()
    return float(1 - ss / st) if st > 0 else float("nan")
