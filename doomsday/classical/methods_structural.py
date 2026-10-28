"""PTDF/LODF candidate pool, ML screen, DC interdiction MILP, and the (heuristic) branch-and-bound. Oracle access only via the
CountedEvaluator / GridFeatures."""
from __future__ import annotations
import heapq, itertools, time
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.stats import spearmanr
from .methods_basic import _struct
from .structural import Struct

def lodf_pool(ev, rng, m: int = 12):
    """Rank branches by pairwise-LODF stress (structure only, zero oracle calls), then exhaustively evaluate all C(m,k)
    sets inside the top-m pool. Ranking cost = L(L-1)/2 Woodbury pair solves, reported in aux (NOT in oracle_calls)."""
    st = _struct(ev); k = ev.k
    if m < k: raise ValueError(f"pool size m={m} < k={k}")
    t0 = time.perf_counter(); pool = st.top_branches(min(m, ev.space.L)); _, ops = st.branch_scores(); rank_t = time.perf_counter() - t0
    X = np.array(list(itertools.combinations(pool, k)), dtype=np.int64)
    ev.batch(X)
    return {"completed": True, "aux": {"m": len(pool), "pool": pool, "pool_sets": int(len(X)), "structural_ops_ranking": ops, "ranking_time_s": rank_t}}

def _unique_ranks(rng, N, n, exclude=frozenset()):
    n = min(n, N - len(exclude))
    if N <= 5_000_000:
        pool = np.setdiff1d(np.arange(N), np.fromiter(exclude, dtype=np.int64, count=len(exclude))) if exclude else np.arange(N)
        return rng.choice(pool, n, replace=False).astype(np.int64)
    out = set()
    while len(out) < n:
        out.update(int(v) for v in rng.integers(0, N, 2 * n) if int(v) not in exclude)
    return np.array(sorted(out)[:n], dtype=np.int64)

def ml_screen(ev, rng, n_train: int | None = None, T: int | None = None, pool_size: int = 200_000, n_estimators: int = 100, max_depth: int = 3):
    """Gradient-boosted trees on structural (Woodbury/LODF + loading) set features. Cost = n_train + T true evaluations
    (V2 15.1). Predicts over all N sets (or a random pool of `pool_size` if N is larger) and evaluates the top-T predicted."""
    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except ImportError as e:
        raise ImportError("ml_screen needs scikit-learn (pip install '.[analysis]')") from e
    sp, N = ev.space, ev.space.N; st = _struct(ev)
    n_train = n_train or max(30, int(np.ceil(0.08 * N))); T = T or max(10, int(np.ceil(0.04 * N)))
    tr = _unique_ranks(rng, N, n_train)
    Xtr = sp.unrank_batch(tr); ytr = ev.batch(Xtr)
    if N <= pool_size: cand = np.setdiff1d(np.arange(N, dtype=np.int64), tr)
    else: cand = _unique_ranks(rng, N, pool_size, exclude=frozenset(tr.tolist()))
    Xc = sp.unrank_batch(cand)
    model = GradientBoostingRegressor(n_estimators=n_estimators, max_depth=max_depth, random_state=int(rng.integers(2**31 - 1)))
    model.fit(st.features(Xtr), ytr)
    pred = model.predict(st.features(Xc))
    top = np.lexsort((cand, -pred))[:T]                                   # best predicted, ties -> lowest rank
    ytop = ev.batch(Xc[top])
    rho = float(spearmanr(pred[top], ytop)[0]) if len(top) > 2 and np.ptp(ytop) > 0 and np.ptp(pred[top]) > 0 else None
    return {"completed": True, "aux": {"n_train": int(n_train), "T": int(T), "cost_train_plus_T": int(n_train + T), "candidates_scored": int(len(cand)),
                                       "in_sample_R2": float(model.score(st.features(Xtr), ytr)), "spearman_pred_vs_true_on_topT": rho,
                                       "n_features": len(st.FEATURES)}}

# ---------------------------------------------------------------------------------------------------------------------
# DC interdiction MILP (attacker-defender, static, no cascade). Different severity definition: minimum load shed under DC
# redispatch (g in [0, Pmax] per bus). Single-level MILP via LP duality of the defender's LP + big-M linearisation of z*w.
# ---------------------------------------------------------------------------------------------------------------------
def _model_data(f):
    if f.branch_x_pu is None:
        raise ValueError("GridFeatures.branch_x_pu is missing (table/features produced before Phase 4); regenerate the table to use the MILP baseline")
    pos = {int(b): i for i, b in enumerate(f.bus_id)}
    fr = np.array([pos[int(b)] for b in f.branch_from_bus]); to = np.array([pos[int(b)] for b in f.branch_to_bus])
    A = np.zeros((f.L, f.B)); A[np.arange(f.L), fr] = 1.0; A[np.arange(f.L), to] = -1.0
    G = np.zeros(f.B)
    for b, p in zip(f.gen_bus_id, f.gen_pmax_mw): G[pos[int(b)]] += p
    return A, G, f.load_mw.astype(float), f.rating_dc_mw.astype(float), 1.0 / f.branch_x_pu

def static_dc_shed(f, outage) -> float:
    """Defender LP for a FIXED outage: min load shed (fraction of load) with DC flows, flow limits = DC ratings, redispatch in [0,Pmax].
    Used to verify the MILP; solved with HiGHS (scipy.optimize.linprog)."""
    A, G, d, F, b = _model_data(f); L, B = A.shape; base = f.base_mva
    z = np.ones(L); z[list(outage)] = 0.0
    bz = z * b * base                                                    # MW per rad
    Bz = A.T @ (bz[:, None] * A)
    # variables [theta(B), g(B), s(B)]; min sum s
    c = np.concatenate([np.zeros(2 * B), np.ones(B)])
    Aeq = np.hstack([Bz, -np.eye(B), -np.eye(B)]); beq = -d
    Fl = bz[:, None] * A
    Aub = np.vstack([np.hstack([Fl, np.zeros((L, 2 * B))]), np.hstack([-Fl, np.zeros((L, 2 * B))])]); bub = np.concatenate([F, F])
    bounds = [(None, None)] * B + [(0, G[i]) for i in range(B)] + [(0, d[i]) for i in range(B)]
    r = linprog(c, A_ub=Aub, b_ub=bub, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
    if r.status != 0: raise RuntimeError(f"defender LP failed: {r.message}")
    return float(r.fun / d.sum())

def solve_interdiction_milp(f, k: int, lam_bound: float = 5.0, time_limit: float = 120.0, mip_rel_gap: float = 0.0, forbidden=()):
    """max over |x|=k of the defender's min shed, via the dual. Returns dict(status, x (outage tuple), obj_shed_fraction).
    The dual box [-lam_bound, lam_bound] can only make the MILP value LOWER than the true bilevel value; the true value of the returned
    set is recomputed with static_dc_shed so any gap is visible (never hidden)."""
    A, G, d, F, b = _model_data(f); L, B = A.shape; Lb = lam_bound; M = 3 * Lb
    ix = {n: o for n, o in zip(("x", "lam", "ap", "am", "gam", "sig", "u"), np.cumsum([0, L, B, L, L, B, B, L])[:-1])}
    n = L + B + L + L + B + B + L
    c = np.zeros(n); c[ix["lam"]:ix["lam"] + B] = d; c[ix["ap"]:ix["ap"] + L] = F; c[ix["am"]:ix["am"] + L] = F
    c[ix["gam"]:ix["gam"] + B] = G; c[ix["sig"]:ix["sig"] + B] = d
    rows, lo, hi = [], [], []
    def add(row, l, h): rows.append(row); lo.append(l); hi.append(h)
    for i in range(B):
        r = np.zeros(n); r[ix["lam"] + i] = 1; r[ix["gam"] + i] = 1; add(r, 0, np.inf)               # lam + gam >= 0
        r = np.zeros(n); r[ix["lam"] + i] = 1; r[ix["sig"] + i] = 1; add(r, -1, np.inf)              # 1 + lam + sig >= 0
        r = np.zeros(n); r[ix["u"]:ix["u"] + L] = A[:, i] * b; add(r, 0, 0)                          # stationarity in theta_i
    for l in range(L):
        fi, ti = int(np.flatnonzero(A[l] == 1)[0]), int(np.flatnonzero(A[l] == -1)[0])
        r = np.zeros(n); r[ix["u"] + l] = 1; r[ix["x"] + l] = M; add(r, -np.inf, M)                  # u <= M(1-x)
        r = np.zeros(n); r[ix["u"] + l] = 1; r[ix["x"] + l] = -M; add(r, -M, np.inf)                 # u >= -M(1-x)
        def w_row(sgn_x):
            r = np.zeros(n); r[ix["u"] + l] = 1; r[ix["lam"] + fi] += 1; r[ix["lam"] + ti] -= 1
            r[ix["ap"] + l] = -1; r[ix["am"] + l] = 1; r[ix["x"] + l] = sgn_x * M; return r          # u - w (+/-) M x
        add(w_row(-1), -np.inf, 0); add(w_row(+1), 0, np.inf)                                         # u = w when x = 0
    r = np.zeros(n); r[ix["x"]:ix["x"] + L] = 1; add(r, k, k)
    for S in forbidden:
        r = np.zeros(n); r[list(S)] = 1; add(r, -np.inf, k - 1)                                       # no-good cut
    lb = np.concatenate([np.zeros(L), -Lb * np.ones(B), np.zeros(L), np.zeros(L), np.zeros(B), np.zeros(B), -M * np.ones(L)])
    ub = np.concatenate([np.ones(L), Lb * np.ones(B), Lb * np.ones(L), Lb * np.ones(L), Lb * np.ones(B), Lb * np.ones(B), M * np.ones(L)])
    integ = np.zeros(n); integ[:L] = 1
    t0 = time.perf_counter()
    res = milp(c, constraints=LinearConstraint(np.array(rows), lo, hi), integrality=integ, bounds=Bounds(lb, ub),
               options={"time_limit": time_limit, "mip_rel_gap": mip_rel_gap})
    out = {"status": int(res.status), "message": str(res.message), "solve_time_s": time.perf_counter() - t0, "lam_bound": lam_bound}
    if res.x is None: out.update(x=None, obj=None); return out
    x = tuple(int(i) for i in np.flatnonzero(res.x[:L] > 0.5)); out.update(x=x, obj=float(-res.fun / d.sum()))
    return out

def milp_interdiction(ev, rng, n_solutions: int = 1, lam_bound: float = 5.0, time_limit: float = 120.0):
    """Strongest classical DC N-k technique (static, no cascade). The returned sets are RE-EVALUATED under the cascade oracle
    (these re-evaluations are the only oracle calls). Compare by cascade-evaluated severity and ranking agreement, not by call counts."""
    f = ev.oracle.structure(); k = ev.k; sols = []; forb = []
    for _ in range(n_solutions):
        r = solve_interdiction_milp(f, k, lam_bound, time_limit, forbidden=forb)
        if r["x"] is None: break
        r["static_lp_check"] = static_dc_shed(f, r["x"]); r["cascade_S"] = ev(r["x"]); sols.append(r); forb.append(r["x"])
    return {"completed": all(s["status"] == 0 for s in sols) and len(sols) == n_solutions, "exact": None,
            "aux": {"solutions": sols, "note": "different severity definition (static DC load shed); budget irrelevant", "lam_bound": lam_bound}}

def branch_and_bound(ev, rng, theta: float = 0.5):
    """[PROPOSED/stretch -- HEURISTIC, NOT EXACT]. Best-first search over partial sets (branches added in decreasing structural-stress
    order). A partial set is expanded only if its LODF/Woodbury stress >= theta. V2 asks for 'LODF-bounded pruning on DC S', but S is
    not monotone in the outage set (V2 4.4) and no valid LODF upper bound on cascade severity exists, so this bound is a heuristic proxy:
    it can prune the true optimum. Reported with nodes expanded/pruned; recall is measured against brute force, never assumed."""
    L, k = ev.space.L, ev.k; st = _struct(ev)
    order = st.top_branches(L); sc, _ = st.branch_scores(); order = sorted(range(L), key=lambda i: (-round(sc[i], 12), i))
    heap, cnt, expanded, pruned, leaves = [], itertools.count(), 0, 0, 0
    for p in range(L): heapq.heappush(heap, (-st.stress((order[p],)), next(cnt), (p,)))
    while heap:
        negs, _, P = heapq.heappop(heap); K = tuple(sorted(order[p] for p in P))
        if len(P) == k:
            ev(K); leaves += 1; continue
        if -negs < theta: pruned += 1; continue
        expanded += 1
        for p in range(P[-1] + 1, L):
            Q = P + (p,); heapq.heappush(heap, (-st.stress(tuple(sorted(order[q] for q in Q))), next(cnt), Q))
    return {"completed": True, "exact": False, "aux": {"theta": theta, "nodes_expanded": expanded, "nodes_pruned": pruned, "leaves_evaluated": leaves,
                                                     "heuristic_bound_not_rigorous": True}}
