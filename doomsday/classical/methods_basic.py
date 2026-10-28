"""Brute force, random search, hill climb, beam search, simulated annealing, genetic algorithm.
All depend only on oracle.interface (via the CountedEvaluator) and numpy. Hyper-parameter defaults are a-priori choices:
they were NOT tuned (V2 15.2 asks for tuning on a held-out grid/k pair; no second verified grid is available yet)."""
from __future__ import annotations
import math
import numpy as np
from ..oracle.interface import BAND
from .structural import Struct

_SHARED: dict = {}                     # (Phase 7) one Struct per GridFeatures object, reused across runs (pure functions of the set)

def _struct(ev) -> Struct:
    if not hasattr(ev, "_struct"):
        f = ev.oracle.structure(); hit = _SHARED.get(id(f))
        if hit is None or hit[0] is not f:
            if len(_SHARED) >= 4: _SHARED.pop(next(iter(_SHARED)))
            hit = _SHARED[id(f)] = (f, Struct(f))
        ev._struct = hit[1]
    return ev._struct

def _rand_set(rng, L, k): return tuple(sorted(rng.choice(L, k, replace=False).tolist()))

def brute_force(ev, rng, chunk: int = 50_000):
    """Enumerate all N sets in lexicographic order. The only method (with Durr-Hoyer) with a certified stopping rule."""
    N = ev.space.N
    for s in range(0, N, chunk):
        ev.batch(ev.space.unrank_batch(np.arange(s, min(s + chunk, N), dtype=np.int64)))
    return {"completed": True, "certified": True, "exact": True, "aux": {}}

def random_search(ev, rng, block: int = 64):
    """Uniform sampling WITHOUT replacement (unique evaluations until Smax seen ~ N/(M+1))."""
    N = ev.space.N
    if N <= 5_000_000:
        order = rng.permutation(N)
        for s in range(0, N, block):
            ev.batch(ev.space.unrank_batch(order[s:s + block].astype(np.int64)))
        return {"completed": True, "aux": {}}
    seen = set()
    while len(seen) < N:
        r = [int(v) for v in rng.integers(0, N, block) if int(v) not in seen]
        seen.update(r)
        if r: ev.batch(ev.space.unrank_batch(np.array(r, dtype=np.int64)))
    return {"completed": True, "aux": {}}

def hill_climb(ev, rng, n_starts: int = 5, start: str = "stress"):
    """Steepest ascent over the swap neighbourhood (k*(L-k) neighbours), strict improvement only (no sideways moves),
    multi-start. Start 0 = the k branches with the highest structural stress score (V2: 'top-k N-1 outages'; the N-1
    severity itself is identically 0 under N-1-secure ratings, so the structural N-1/pair stress is used instead)."""
    L, k = ev.space.L, ev.k; st = _struct(ev); optima = []; steps = 0
    for s in range(n_starts):
        cur = tuple(st.top_branches(k)) if (s == 0 and start == "stress") else _rand_set(rng, L, k)
        Sc = ev(cur)
        while True:
            nb = sorted({tuple(sorted(cur[:i] + cur[i + 1:] + (c,))) for i in range(k) for c in range(L) if c not in cur})
            vals = ev.batch(np.array(nb, dtype=np.int64))
            i = int(np.argmax(vals))                                         # first max in lexicographic neighbour order
            if vals[i] > Sc + BAND: cur, Sc = nb[i], float(vals[i]); steps += 1
            else: break
        optima.append((cur, Sc))
    return {"completed": True, "aux": {"n_starts": n_starts, "steps": steps, "local_optima": [[list(c), s] for c, s in optima]}}

def beam_search(ev, rng, width: int = 20):
    """Level-j beam: candidates = beam members + one more branch, scored by the TRUE oracle at cardinality j (oracle.with_k(j)).
    Ties (all of level 1 is S=0 under N-1-secure ratings) are broken by structural set stress, then lexicographically."""
    L, k = ev.space.L, ev.k; st = _struct(ev); sc, _ = st.branch_scores()
    cand = [(c,) for c in range(L)]
    key = lambda c, v: (-round(v / BAND), -round(st.stress(c), 12), c)
    beam = []
    for j in range(1, k + 1):
        if j > 1:
            cand = sorted({tuple(sorted(P + (c,))) for P in beam for c in range(L) if c not in P})
        vals = ev.batch(np.array(cand, dtype=np.int64), j=j)
        order = sorted(range(len(cand)), key=lambda i: key(cand[i], vals[i]))
        beam = [cand[i] for i in order[:width]]
    return {"completed": True, "aux": {"width": width}}

def simulated_annealing(ev, rng, T0: float = 0.05, T1: float = 0.001, n_iter: int = 4000, init: str = "random"):
    """Swap moves preserving |x|=k; geometric cooling T0 -> T1; Metropolis acceptance on S (S in [0,1])."""
    L, k = ev.space.L, ev.k
    cur = tuple(_struct(ev).top_branches(k)) if init == "stress" else _rand_set(rng, L, k)
    Sc = ev(cur); acc = 0
    for i in range(n_iter):
        T = T0 * (T1 / T0) ** (i / max(1, n_iter - 1))
        pos = int(rng.integers(k)); new = int(rng.integers(L))
        if new in cur: continue
        cand = tuple(sorted(cur[:pos] + cur[pos + 1:] + (new,)))
        Sn = ev(cand)
        if Sn >= Sc or rng.random() < math.exp((Sn - Sc) / T): cur, Sc = cand, Sn; acc += 1
    return {"completed": True, "aux": {"T0": T0, "T1": T1, "n_iter": n_iter, "accepted": acc}}

def genetic_algorithm(ev, rng, pop: int = 40, n_gen: int = 100, p_mut: float = 0.3, tournament: int = 3, elite: int = 2):
    """Generational GA on k-subsets: tournament selection, union-sampling crossover and swap mutation (both preserve |x|=k), elitism."""
    L, k, N = ev.space.L, ev.k, ev.space.N
    pop = min(pop, N); P = []
    while len(P) < pop:
        c = _rand_set(rng, L, k)
        if c not in P: P.append(c)
    fit = dict(zip(P, ev.batch(np.array(P, dtype=np.int64))))
    gen_best, pop_sizes = [], []
    for g in range(n_gen):
        ranked = sorted(P, key=lambda c: (-fit[c], c)); kids = []
        while len(kids) < pop - elite:
            ps = []
            for _ in range(2):
                t = [P[int(i)] for i in rng.integers(len(P), size=tournament)]; ps.append(max(t, key=lambda c: (fit[c], c)))
            union = sorted(set(ps[0]) | set(ps[1]))
            child = sorted(rng.choice(union, k, replace=False).tolist()) if len(union) > k else list(union)
            if rng.random() < p_mut:
                child[int(rng.integers(k))] = -1
                pool = [c for c in range(L) if c not in child]; child[child.index(-1)] = int(rng.choice(pool))
            kids.append(tuple(sorted(child)))
        vals = ev.batch(np.array(kids, dtype=np.int64))
        for c, v in zip(kids, vals): fit[c] = float(v)
        P = ranked[:elite] + kids
        gen_best.append(max(fit[c] for c in P)); pop_sizes.append(len(P))
    return {"completed": True, "aux": {"gen_best": gen_best, "pop_sizes": pop_sizes, "pop": pop, "n_gen": n_gen, "p_mut": p_mut, "tournament": tournament, "elite": elite}}
