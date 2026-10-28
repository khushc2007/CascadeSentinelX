"""Structure-exploiting helpers built ONLY from oracle.interface.GridFeatures (plain numpy): Woodbury/LODF post-outage
loading, an islanding proxy, branch scores, and set features. Used by hill-climb starts, beam tie-breaks, the LODF pool,
the ML screen and the branch-and-bound heuristic. Nothing here evaluates the oracle: all of it is 'ranking cost'."""
from __future__ import annotations
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

SIGMA_CONNECTED = 1e-6

class Struct:
    def __init__(self, f):
        self.f = f; self.L, self.B = f.L, f.B
        pos = {int(b): i for i, b in enumerate(f.bus_id)}
        self.fr = np.array([pos[int(b)] for b in f.branch_from_bus]); self.to = np.array([pos[int(b)] for b in f.branch_to_bus])
        self.flow0 = f.base_flow_dc_mw; self.R = f.rating_dc_mw; self.phi = f.phi
        self.gen_buses = np.array([pos[int(b)] for b, p in zip(f.gen_bus_id, f.gen_pmax_mw) if p > 0], dtype=int)
        self.total_load = float(f.load_mw.sum()); self._scores = None; self._cache = {}; self._fcache = {}

    def _components(self, K):
        keep = np.ones(self.L, bool); keep[list(K)] = False
        a = coo_matrix((np.ones(keep.sum()), (self.fr[keep], self.to[keep])), shape=(self.B, self.B))
        return connected_components(a, directed=False)

    def isolated_load_fraction(self, K) -> float:
        n, lab = self._components(K)
        has_gen = np.zeros(n, bool); has_gen[lab[self.gen_buses]] = True
        lost = float(self.f.load_mw[~has_gen[lab]].sum())
        return lost / self.total_load if self.total_load > 0 else 0.0

    def analyse(self, K, cache: bool = True) -> dict:
        """post-outage DC loading of survivors via Woodbury (V2 6.2). Islanding is decided by EXACT connectivity (never by a
        threshold alone); islanding sets get stress = 1 + isolated-load fraction if load is stranded, else 0 (proxy, no flows)."""
        K = tuple(sorted(K))
        if K in self._cache: return self._cache[K]
        k = len(K); Phi = self.phi
        if k == 0:
            u = np.abs(self.flow0) / self.R; res = dict(islanding=False, iso=0.0, u=u, sigma=1.0)
        else:
            M = np.eye(k) - Phi[np.ix_(K, K)]; sigma = float(np.linalg.svd(M, compute_uv=False).min())
            islanding = False
            if sigma < SIGMA_CONNECTED:
                islanding = self._components(K)[0] > 1                        # exact graph test decides
            if islanding:
                res = dict(islanding=True, iso=self.isolated_load_fraction(K), u=None, sigma=sigma)
            else:
                z = np.linalg.lstsq(M, self.flow0[list(K)], rcond=None)[0] if sigma < SIGMA_CONNECTED else np.linalg.solve(M, self.flow0[list(K)])
                fp = self.flow0 + Phi[:, list(K)] @ z; fp[list(K)] = 0.0
                res = dict(islanding=False, iso=0.0, u=np.abs(fp) / self.R, sigma=sigma)
        if cache: self._cache[K] = res
        return res

    def stress(self, K) -> float:
        a = self.analyse(K)
        if a["islanding"]:
            return 1.0 + a["iso"] if a["iso"] > 0 else 0.0
        u = a["u"].copy(); u[list(K)] = 0.0
        return float(u.max())

    def branch_scores(self):
        """score_b = max over partners c of stress({b,c}). Returns (scores, structural_ops)."""
        if self._scores is None:
            s = np.zeros(self.L)
            for b in range(self.L):
                for c in range(b + 1, self.L):
                    v = self.stress((b, c)); s[b] = max(s[b], v); s[c] = max(s[c], v)
            self._scores = (s, self.L * (self.L - 1) // 2)
        return self._scores

    def top_branches(self, m: int) -> list:
        s, _ = self.branch_scores()
        return sorted(sorted(range(self.L), key=lambda i: (-round(s[i], 12), i))[:m])

    FEATURES = ["base_load_max", "base_load_mean", "score_max", "score_mean", "score_min", "n_bridge", "stress", "n_over", "n_over90",
                "iso_frac", "islanding", "coupling_max", "sigma_min", "top2_u"]

    def features(self, X) -> np.ndarray:
        s, _ = self.branch_scores(); out = np.zeros((len(X), len(self.FEATURES)))
        for i, row in enumerate(np.asarray(X)):
            K = tuple(sorted(int(v) for v in row))
            hit = self._fcache.get(K)                                    # (Phase 7) compact per-set feature cache shared across runs on one table
            if hit is not None: out[i] = hit; continue
            a = self.analyse(K, cache=False); ix = list(K)
            bl = self.f.base_loading_dc[ix]; sc = s[ix]
            coup = max([abs(self.phi[p, q]) for p in K for q in K if p != q] or [0.0])
            if a["islanding"]:
                st, nov, nov9, t2 = 1.0 + a["iso"] if a["iso"] > 0 else 0.0, 0, 0, 0.0
            else:
                u = a["u"].copy(); u[ix] = 0.0; srt = np.sort(u)[::-1]; st, nov, nov9, t2 = srt[0], int((u > 1).sum()), int((u > 0.9).sum()), srt[1] if len(srt) > 1 else 0.0
            out[i] = [bl.max(), bl.mean(), sc.max(), sc.mean(), sc.min(), int(self.f.is_bridge[ix].sum()), st, nov, nov9,
                      a["iso"], float(a["islanding"]), coup, min(a["sigma"], 1.0), t2]
            self._fcache[K] = out[i].copy()
        return out
