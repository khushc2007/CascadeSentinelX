"""Basic DC power flow (V2 6.1): B' theta = P, f = diag(b) A theta. PTDF/LODF/Woodbury arrive in Phase 2."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .islanding import grid_components

@dataclass
class DCResult:
    theta: np.ndarray        # rad
    flow_mw: np.ndarray      # signed, from -> to; 0 for out-of-service branches
    slack_pickup_mw: float   # injection the slack bus must supply beyond the given vector

def incidence(grid) -> np.ndarray:
    A = np.zeros((grid.n_branch, grid.n_bus))
    ar = np.arange(grid.n_branch)
    A[ar, grid.br_from] = 1.0
    A[ar, grid.br_to] = -1.0
    return A

def branch_susceptance(grid, status=None) -> np.ndarray:
    s = grid.br_status if status is None else np.asarray(status)
    return np.where(s > 0, 1.0 / grid.x, 0.0)

def dc_power_flow(grid, p_inj_mw, status=None, slack: int | None = None) -> DCResult:
    """Solve the connected DC network. p_inj_mw = net injection (gen - load) per bus; the slack bus
    injection is whatever closes the balance. Disconnected networks are rejected (islands: Phase 2)."""
    s = grid.br_status if status is None else np.asarray(status)
    ncomp, _ = grid_components(grid, s)
    if ncomp != 1:
        raise ValueError(f"DC power flow needs a connected network (found {ncomp} islands)")
    sl = grid.slack_bus if slack is None else slack
    p = np.asarray(p_inj_mw, dtype=np.float64) / grid.base_mva
    b = branch_susceptance(grid, s)
    A = incidence(grid)
    Bp = A.T @ (b[:, None] * A)
    keep = np.array([i for i in range(grid.n_bus) if i != sl])
    theta = np.zeros(grid.n_bus)
    theta[keep] = np.linalg.solve(Bp[np.ix_(keep, keep)], p[keep])
    flow = b * (A @ theta) * grid.base_mva
    return DCResult(theta=theta, flow_mw=flow, slack_pickup_mw=float(-p[keep].sum() * grid.base_mva))

def dc_base_injections(grid, ac) -> tuple[np.ndarray, float]:
    """V2 5.2 step 5 with resolution C: DC injections = AC bus active injections, with the slack
    generation reduced by the total AC losses so that sum(P)=0 (lossless DC). Returns (P_mw, losses_mw)."""
    p = np.array(ac.P_inj_mw, dtype=np.float64)
    loss = float(p.sum())
    p[grid.slack_bus] -= loss
    return p, loss


class DCSensitivities:
    """V2 6.2: branch-to-branch sensitivity Phi = diag(b) A B'^-1 A^T and the compensation (Woodbury) update
    f'_l = f_l + Phi[l,K] (I - Phi[K,K])^-1 f_K,  f'_K = 0.  Valid ONLY at fixed topology/injections (no islanding);
    island detection must be done by exact graph connectivity before calling post_outage_flows."""

    def __init__(self, grid, p_inj_mw, status=None):
        s = grid.br_status if status is None else np.asarray(status)
        if grid_components(grid, s)[0] != 1:
            raise ValueError("DCSensitivities requires a connected base network")
        self.grid, self.status = grid, np.array(s)
        b = branch_susceptance(grid, s)
        A = incidence(grid)
        Bp = A.T @ (b[:, None] * A)
        sl = grid.slack_bus
        keep = np.array([i for i in range(grid.n_bus) if i != sl])
        Binv = np.zeros((grid.n_bus, grid.n_bus))
        Binv[np.ix_(keep, keep)] = np.linalg.inv(Bp[np.ix_(keep, keep)])
        self.Phi = (b[:, None] * A) @ Binv @ A.T
        base = dc_power_flow(grid, p_inj_mw, s)
        self.flow0_mw = base.flow_mw

    def lodf(self, m: int) -> np.ndarray:
        """LODF_{.,m} = Phi_{.,m} / (1 - Phi_mm) (single outage of branch m)."""
        return self.Phi[:, m] / (1.0 - self.Phi[m, m])

    def post_outage_flows(self, K, sigma_min_limit: float = 1e-9) -> np.ndarray:
        K = np.asarray(sorted(set(int(k) for k in K)), dtype=int)
        f = self.flow0_mw.copy()
        if len(K) == 0:
            return f
        M = np.eye(len(K)) - self.Phi[np.ix_(K, K)]
        if np.linalg.svd(M, compute_uv=False).min() < sigma_min_limit:   # absolute test (cond() of a 1x1 is always 1)
            raise np.linalg.LinAlgError("I - Phi_KK is numerically singular (outage set disconnects the network)")
        z = np.linalg.solve(M, f[K])
        out = f + self.Phi[:, K] @ z
        out[K] = 0.0
        return out
