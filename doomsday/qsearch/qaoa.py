"""QAOA on the exactly-k subspace (V2 14.2): Dicke initial state, p layers of exp(-i gamma H_C) (H_C = surrogate, diagonal) followed by a
ring XY mixer applied as even-pair then odd-pair hopping exp(-i beta (XX+YY)/2) on each ring edge (Hamming weight preserved exactly).
Simulated EXACTLY in the N = C(L,k)-dimensional weight-k subspace ([SIMULATED] NumPy statevector; not Aer, not hardware). Cross-checked
against a Qiskit circuit for L <= 12 by tests/E10. The objective is the SURROGATE expectation (maximised)."""
from __future__ import annotations
from itertools import combinations
import numpy as np
from scipy.optimize import minimize

class SubspaceQAOA:
    def __init__(self, L: int, k: int, cost: np.ndarray, states=None):
        """cost[i] = surrogate value of the i-th weight-k state; states = list of k-tuples (lexicographic by default, matching rank order)."""
        self.L, self.k = int(L), int(k)
        self.states = list(states) if states is not None else list(combinations(range(L), k))
        self.N = len(self.states); self.cost = np.asarray(cost, float)
        if self.cost.shape != (self.N,): raise ValueError("cost must have one entry per weight-k state")
        masks = np.array([sum(1 << q for q in s) for s in self.states], dtype=np.int64); pos = {int(m): i for i, m in enumerate(masks)}
        edges = [(i, (i + 1) % L) for i in range(L)] if L > 2 else [(0, 1)]
        self.layers = [[e for e in edges if e[0] % 2 == 0 and e[0] != L - 1], [e for e in edges if e[0] % 2 == 1], [e for e in edges if e[0] == L - 1 and L % 2 == 1]]
        self.layers = [l for l in self.layers if l]
        self.hops = []                                                            # per layer: list of (idx_a, idx_b) state pairs swapped by each edge
        for layer in self.layers:
            hl = []
            for (a, b) in layer:
                ba, bb = (masks >> a) & 1, (masks >> b) & 1; sel = np.flatnonzero((ba == 1) & (bb == 0))
                partner = np.array([pos[int(m ^ ((1 << a) | (1 << b)))] for m in masks[sel]], dtype=np.int64); hl.append((sel, partner))
            self.hops.append(hl)
    def dicke(self) -> np.ndarray: return np.full(self.N, self.N ** -0.5, dtype=complex)
    def mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        c, s = np.cos(beta), -1j * np.sin(beta)
        for hl in self.hops:                                                      # edges within a layer are disjoint -> commuting
            for sel, partner in hl:
                a, b = psi[sel].copy(), psi[partner].copy(); psi[sel] = c * a + s * b; psi[partner] = s * a + c * b
        return psi
    def state(self, gammas, betas) -> np.ndarray:
        psi = self.dicke()
        for g, b in zip(gammas, betas):
            psi = psi * np.exp(-1j * g * self.cost); psi = self.mixer(psi, b)
        return psi
    def expectation(self, params) -> float:
        p = len(params) // 2; psi = self.state(params[:p], params[p:]); return float(np.real(np.vdot(psi, self.cost * psi)))
    def optimize(self, p_max: int = 4, starts: int = 10, seed: int = 0, maxiter: int = 400) -> dict:
        """COBYLA from `starts` random starts at p=1, then INTERP warm start (Zhou et al.) for p = 2..p_max plus fresh random starts.
        Costs are rescaled to unit spread for conditioning (the optimum is unchanged)."""
        rng = np.random.default_rng(seed); spread = float(np.ptp(self.cost)) or 1.0; scale = 1.0 / spread
        f = lambda x: -self.expectation(np.concatenate([x[: len(x) // 2] * scale, x[len(x) // 2:]]))
        out, prev = {}, None
        for p in range(1, p_max + 1):
            cands = []
            if prev is not None:
                g0, b0 = prev[:p - 1], prev[p - 1:]
                interp = lambda v: np.array([((i) / (p - 1)) * (v[i - 1] if i > 0 else 0) + ((p - 1 - i) / (p - 1)) * (v[i] if i < p - 1 else 0) for i in range(p)]) if p > 1 else v
                cands.append(np.concatenate([interp(g0), interp(b0)]))
            cands += [np.concatenate([rng.uniform(0, 2 * np.pi, p), rng.uniform(0, np.pi, p)]) for _ in range(starts)]
            best = None
            for x0 in cands:
                r = minimize(f, x0, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.5})
                if best is None or r.fun < best.fun: best = r
            prev = best.x; g = best.x[:p] * scale; b = best.x[p:]; psi = self.state(g, b); prob = np.abs(psi) ** 2
            out[p] = {"gammas": g.tolist(), "betas": b.tolist(), "expected_surrogate": -best.fun, "prob": prob, "nfev_best": int(best.nfev), "n_starts": len(cands)}
        return out

def sample(prob: np.ndarray, shots: int, rng) -> np.ndarray:
    return rng.choice(len(prob), size=shots, p=prob / prob.sum())

def qiskit_circuit(L: int, k: int, ising: dict, gammas, betas):
    """Qiskit circuit for the same QAOA (for the L <= 12 Aer cross-check and depth/2q-gate counts). Cost layer from x = (1 - Z)/2:
    exp(-i g S_hat) up to global phase = prod RZ / RZZ with angles from h and J. Dicke prep = Baertschi-Eidenbenz (Phase 8, verified)."""
    from qiskit import QuantumCircuit
    from qiskit.circuit.library import XXPlusYYGate
    from .dicke import be_dicke_circuit
    from .qiskit_export import to_qiskit
    qc = QuantumCircuit(L); qc.compose(to_qiskit(be_dicke_circuit(L, k)), inplace=True)
    h, J = np.asarray(ising["h"], float), ising["J"]
    zc = -h / 2.0                                                            # coefficient of Z_i:   x_i = (1 - Z_i)/2
    for (i, j), v in J.items():                                             # x_i x_j = (1 - Z_i - Z_j + Z_i Z_j)/4
        zc[i] -= v / 4; zc[j] -= v / 4
    edges = [(i, (i + 1) % L) for i in range(L)]
    layers = [[e for e in edges if e[0] % 2 == 0 and e[0] != L - 1], [e for e in edges if e[0] % 2 == 1], [e for e in edges if e[0] == L - 1 and L % 2 == 1]]
    for g, b in zip(gammas, betas):
        for i in range(L):
            if abs(zc[i]) > 0: qc.rz(2 * g * zc[i], i)                     # exp(-i g c Z) = RZ(2 g c)
        for (i, j), v in J.items():
            if abs(v) > 0: qc.rzz(2 * g * v / 4, i, j)
        for layer in layers:
            for (a, c) in layer: qc.append(XXPlusYYGate(2 * b, 0.0), [a, c])   # exp(-i b (XX+YY)/2)
    return qc
