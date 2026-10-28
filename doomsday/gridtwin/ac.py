"""AC power flow: Newton-Raphson, polar form, PV/PQ/slack (V2 7). Generator Q limits OFF (V2 default).
Island handling, DC-angle restart and the curtailment ladder arrive in Phase 2."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .islanding import grid_components
from .model import PQ, PV, SLACK

@dataclass
class ACResult:
    converged: bool
    iterations: int
    mismatch_pu: float
    V: np.ndarray               # complex p.u.
    P_inj_mw: np.ndarray        # net bus injection (gen - load), MW
    Q_inj_mvar: np.ndarray
    bus_gen_p_mw: np.ndarray
    bus_gen_q_mvar: np.ndarray
    Sf_mva: np.ndarray          # complex, from end, 0 if out of service
    St_mva: np.ndarray
    losses_mw: float

    @property
    def Vm(self): return np.abs(self.V)
    @property
    def Va_deg(self): return np.degrees(np.angle(self.V))
    @property
    def apparent_mva(self): return np.maximum(np.abs(self.Sf_mva), np.abs(self.St_mva))

def branch_admittances(grid, status=None):
    s = (grid.br_status if status is None else np.asarray(status)) > 0
    ys = 1.0 / (grid.r + 1j * grid.x)
    tap = grid.tap * np.exp(1j * grid.shift)
    ytt = ys + 1j * grid.b / 2.0
    yff = ytt / (tap * np.conj(tap))
    yft = -ys / np.conj(tap)
    ytf = -ys / tap
    z = lambda a: np.where(s, a, 0.0)
    return z(yff), z(yft), z(ytf), z(ytt)

def build_ybus(grid, status=None) -> np.ndarray:
    yff, yft, ytf, ytt = branch_admittances(grid, status)
    n, f, t = grid.n_bus, grid.br_from, grid.br_to
    Y = np.zeros((n, n), dtype=complex)
    np.add.at(Y, (f, f), yff); np.add.at(Y, (f, t), yft)
    np.add.at(Y, (t, f), ytf); np.add.at(Y, (t, t), ytt)
    Y[np.arange(n), np.arange(n)] += (grid.Gs + 1j * grid.Bs) / grid.base_mva
    return Y

def scheduled(grid):
    """Scheduled complex injection (p.u.) and voltage setpoints. Q is scheduled only on PQ buses;
    P at the slack bus is free."""
    base = grid.base_mva
    inserv = grid.gen_status > 0
    pg = np.zeros(grid.n_bus); qg = np.zeros(grid.n_bus)
    np.add.at(pg, grid.gen_bus[inserv], grid.gen_Pg[inserv])
    np.add.at(qg, grid.gen_bus[inserv], grid.gen_Qg[inserv])
    S = (pg - grid.Pd + 1j * (qg - grid.Qd)) / base
    vset = np.ones(grid.n_bus)
    seen = np.zeros(grid.n_bus, bool)
    for i in np.flatnonzero(inserv):
        bi = grid.gen_bus[i]
        if grid.bus_type[bi] in (PV, SLACK) and not seen[bi]:
            vset[bi] = grid.gen_Vset[i]; seen[bi] = True
    return S, vset

def ac_jacobian(Y, V, pv, pq) -> np.ndarray:
    """Analytic NR Jacobian for unknowns [Va(pv,pq); Vm(pq)] and mismatches [P(pv,pq); Q(pq)]."""
    pvpq = np.concatenate([pv, pq]).astype(int)
    I = Y @ V
    Vn = V / np.abs(V)
    dS_dVa = 1j * np.diag(V) @ np.conj(np.diag(I) - Y @ np.diag(V))
    dS_dVm = np.diag(V) @ np.conj(Y @ np.diag(Vn)) + np.conj(np.diag(I)) @ np.diag(Vn)
    J11 = dS_dVa[np.ix_(pvpq, pvpq)].real
    J12 = dS_dVm[np.ix_(pvpq, pq)].real
    J21 = dS_dVa[np.ix_(pq, pvpq)].imag
    J22 = dS_dVm[np.ix_(pq, pq)].imag
    return np.block([[J11, J12], [J21, J22]])

def solve_ac(grid, status=None, tol: float = 1e-8, max_iter: int = 30, V0=None) -> ACResult:
    s = grid.br_status if status is None else np.asarray(status)
    ncomp, _ = grid_components(grid, s)
    if ncomp != 1:
        raise ValueError(f"AC power flow needs a connected network (found {ncomp} islands)")
    Y = build_ybus(grid, s)
    Sbus, vset = scheduled(grid)
    pv = np.flatnonzero(grid.bus_type == PV); pq = np.flatnonzero(grid.bus_type == PQ)
    pvpq = np.concatenate([pv, pq]).astype(int)
    if V0 is None:
        V = vset.astype(complex)                       # flat start
    else:
        V = np.array(V0, dtype=complex)
        fix = np.concatenate([pv, [grid.slack_bus]]).astype(int)
        V[fix] = vset[fix] * V[fix] / np.abs(V[fix])
    def mismatch(V):
        d = Sbus - V * np.conj(Y @ V)
        return np.concatenate([d[pvpq].real, d[pq].imag])
    F = mismatch(V); norm = float(np.max(np.abs(F))) if len(F) else 0.0
    it, ok = 0, norm < tol
    while not ok and it < max_iter:
        J = ac_jacobian(Y, V, pv, pq)
        try:
            dx = np.linalg.solve(J, F)
        except np.linalg.LinAlgError:
            break
        Va, Vm = np.angle(V), np.abs(V)
        Va[pvpq] += dx[:len(pvpq)]
        Vm[pq] += dx[len(pvpq):]
        V = Vm * np.exp(1j * Va)
        it += 1
        F = mismatch(V); norm = float(np.max(np.abs(F)))
        if not np.isfinite(norm):
            break
        ok = norm < tol
    base = grid.base_mva
    Scalc = V * np.conj(Y @ V) * base          # MVA injection
    yff, yft, ytf, ytt = branch_admittances(grid, s)
    f, t = grid.br_from, grid.br_to
    Sf = V[f] * np.conj(yff * V[f] + yft * V[t]) * base
    St = V[t] * np.conj(ytf * V[f] + ytt * V[t]) * base
    gen_p = Scalc.real + grid.Pd
    gen_q = Scalc.imag + grid.Qd
    return ACResult(ok, it, norm, V, Scalc.real.copy(), Scalc.imag.copy(), gen_p, gen_q, Sf, St,
                    float(Scalc.real.sum()))
