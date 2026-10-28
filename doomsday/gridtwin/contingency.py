"""Exactly-k outage sets: lexicographic enumeration / ranking / unranking, validation, and order-independent identity.

PUBLIC ORDER = lexicographic order of sorted branch-index tuples, as V2 5.4 states in words.
V2 5.4 also prints r = sum_i C(c_i, i); that formula is the *colexicographic* combinatorial number system and does NOT
give lexicographic order. This module implements lex as the public ordering and keeps colex_rank/colex_unrank only as a
documented reference (tested to be a different bijection). See docs/CONTINGENCY_ORDERING.md.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import comb
import numpy as np

class ContingencyError(ValueError):
    pass

def n_sets(L: int, k: int) -> int:
    return comb(L, k) if 0 <= k <= L else 0

def validate_outage(outage, L: int, k: int | None = None) -> tuple:
    """Exactly-k validation. Returns the canonical sorted tuple of python ints."""
    try:
        items = list(outage)
    except TypeError:
        raise ContingencyError("outage must be an iterable of branch indices") from None
    out = []
    for v in items:
        if isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)):
            raise ContingencyError(f"branch index must be an integer, got {v!r}")
        out.append(int(v))
    if k is not None and len(out) != k:
        raise ContingencyError(f"expected exactly k={k} outages, got {len(out)}")
    if len(set(out)) != len(out):
        raise ContingencyError(f"duplicate branch in outage set {out}")
    if any(v < 0 or v >= L for v in out):
        raise ContingencyError(f"branch index out of range [0,{L}) in {out}")
    return tuple(sorted(out))

def rank(outage, L: int, k: int | None = None) -> int:
    """Lexicographic rank in [0, C(L,k)). Hockey-stick closed form per slot."""
    c = validate_outage(outage, L, k)
    kk, r, prev = len(c), 0, -1
    for i, ci in enumerate(c, start=1):
        m = kk - i
        r += comb(L - prev - 1, m + 1) - comb(L - ci, m + 1)
        prev = ci
    return r

def rank_batch(outages, L: int, k: int) -> np.ndarray:
    """Vectorised lexicographic rank of rows of an (n,k) array of SORTED, distinct, in-range indices (validated)."""
    X = np.asarray(outages)
    if X.ndim != 2 or X.shape[1] != k or (X.size and X.dtype.kind not in "iu"):
        raise ContingencyError(f"outages must be an integer array of shape (n,{k})")
    if X.size and (X.min() < 0 or X.max() >= L or (k > 1 and np.any(X[:, 1:] <= X[:, :-1]))):
        raise ContingencyError("rows must be strictly increasing indices in [0,L)")
    if max(comb(L, j) for j in range(k + 2)) >= 2 ** 62:
        raise ContingencyError("search space too large for int64 batch ranking")
    X = X.astype(np.int64); r = np.zeros(len(X), dtype=np.int64); prev = np.full(len(X), -1, dtype=np.int64)
    for i in range(1, k + 1):
        m = k - i
        tab = np.array([comb(n, m + 1) for n in range(L + 1)], dtype=np.int64)     # tab[n] = C(n, m+1)
        r += tab[L - prev - 1] - tab[L - X[:, i - 1]]
        prev = X[:, i - 1]
    return r

def unrank(r: int, L: int, k: int) -> tuple:
    N = comb(L, k)
    if isinstance(r, bool) or not isinstance(r, (int, np.integer)) or not 0 <= int(r) < N:
        raise ContingencyError(f"rank {r!r} out of range [0,{N})")
    r, out, prev = int(r), [], -1
    for i in range(1, k + 1):
        m, j = k - i, prev + 1
        while True:
            cnt = comb(L - 1 - j, m)
            if r < cnt:
                break
            r -= cnt; j += 1
        out.append(j); prev = j
    return tuple(out)

def unrank_batch(ranks, L: int, k: int) -> np.ndarray:
    """Vectorised lexicographic unranking -> int64 array (n, k) of sorted branch indices."""
    r = np.asarray(ranks)
    if r.ndim != 1 or (r.size and r.dtype.kind not in "iu"):
        raise ContingencyError("ranks must be a 1-D integer array")
    N = comb(L, k)
    if max(comb(L, j) for j in range(k + 2)) >= 2 ** 62:
        raise ContingencyError("search space too large for int64 batch unranking")
    r = r.astype(np.int64)
    if r.size and (r.min() < 0 or r.max() >= N):
        raise ContingencyError(f"rank out of range [0,{N})")
    out = np.empty((len(r), k), dtype=np.int64)
    prev = np.full(len(r), -1, dtype=np.int64)
    for i in range(1, k + 1):
        m = k - i
        T = np.array([comb(L - 1 - j, m) for j in range(L)], dtype=np.int64)
        cum = np.concatenate([[0], np.cumsum(T)])          # cum[j] = number of sets whose slot value is < j
        t = r + cum[prev + 1]
        j = np.searchsorted(cum, t, side="right") - 1
        r = t - cum[j]
        out[:, i - 1] = j; prev = j
    return out

def iter_chunks(L: int, k: int, chunk: int = 100_000):
    """Yield (start_rank, array (n,k)) covering all of Omega_k in lexicographic order (random-access, chunked)."""
    N = comb(L, k)
    for s in range(0, N, chunk):
        yield s, unrank_batch(np.arange(s, min(s + chunk, N), dtype=np.int64), L, k)

def enumerate_all(L: int, k: int, max_sets: int = 50_000_000) -> np.ndarray:
    N = comb(L, k)
    if N > max_sets:
        raise ContingencyError(f"C({L},{k})={N} exceeds max_sets={max_sets}; use iter_chunks")
    return unrank_batch(np.arange(N, dtype=np.int64), L, k)

# ---- colexicographic combinatorial number system: the formula as PRINTED in V2 5.4 (reference only) ----------------------
def colex_rank(outage) -> int:
    c = sorted(int(v) for v in outage)
    return sum(comb(ci, i) for i, ci in enumerate(c, start=1))

def colex_unrank(r: int, k: int) -> tuple:
    out = []
    for i in range(k, 0, -1):
        c = i - 1
        while comb(c + 1, i) <= r:
            c += 1
        out.append(c); r -= comb(c, i)
    return tuple(sorted(out))

# ---- order-independent branch identity ----------------------------------------------------------------------------
def branch_keys(grid) -> list:
    """Stable, file-order-independent branch identity: (lo_bus_id, hi_bus_id, ordinal). Parallel branches between the
    same buses are ordered by their electrical parameters (r,x,b,tap,shift,status), then by file order; branches that
    are electrically identical are interchangeable, so their relative labelling cannot change any severity."""
    ids = grid.bus_id
    a = np.minimum(ids[grid.br_from], ids[grid.br_to]); b = np.maximum(ids[grid.br_from], ids[grid.br_to])
    groups: dict = {}
    for l in range(grid.n_branch):
        groups.setdefault((int(a[l]), int(b[l])), []).append(l)
    keys = [None] * grid.n_branch
    for (lo, hi), members in groups.items():
        members.sort(key=lambda l: (float(grid.r[l]), float(grid.x[l]), float(grid.b[l]), float(grid.tap[l]),
                                    float(grid.shift[l]), int(grid.br_status[l]), l))
        for o, l in enumerate(members):
            keys[l] = (lo, hi, o)
    return keys

def key_str(key) -> str:
    return f"{key[0]}-{key[1]}#{key[2]}"

@dataclass(frozen=True)
class ContingencySpace:
    """Omega_k over L branches. `branch_keys` (optional) ties indices to order-independent identities."""
    L: int
    k: int
    keys: tuple = ()

    def __post_init__(self):
        for name, v in (('L', self.L), ('k', self.k)):
            if isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)):
                raise ContingencyError(f'{name} must be an integer, got {v!r}')
        if self.L < 0 or not 0 <= self.k <= self.L:
            raise ContingencyError(f'need 0 <= k <= L, got k={self.k}, L={self.L}')
        if self.keys and len(self.keys) != self.L:
            raise ContingencyError('branch keys must have length L')

    @property
    def N(self) -> int: return comb(self.L, self.k)
    def validate(self, outage) -> tuple: return validate_outage(outage, self.L, self.k)
    def rank(self, outage) -> int: return rank(outage, self.L, self.k)
    def unrank(self, r) -> tuple: return unrank(r, self.L, self.k)
    def unrank_batch(self, ranks) -> np.ndarray: return unrank_batch(ranks, self.L, self.k)
    def rank_batch(self, outages) -> np.ndarray: return rank_batch(outages, self.L, self.k)
    def with_k(self, k: int) -> "ContingencySpace": return ContingencySpace(self.L, k, self.keys)

    def identity(self, outage) -> tuple:
        """Order-independent identity: sorted tuple of branch keys (needs branch keys)."""
        if not self.keys:
            raise ContingencyError("this space has no branch keys")
        return tuple(sorted(self.keys[i] for i in self.validate(outage)))

    def from_identity(self, ident) -> tuple:
        pos = {kk: i for i, kk in enumerate(self.keys)}
        try:
            return validate_outage([pos[tuple(kk)] for kk in ident], self.L, self.k)
        except KeyError as e:
            raise ContingencyError(f"unknown branch key {e}") from None

def translate_outage(outage, src: ContingencySpace, dst: ContingencySpace) -> tuple:
    """Re-express an outage given in `src` branch order in `dst` branch order (via branch keys)."""
    return dst.from_identity(src.identity(outage))

def space_for_grid(grid, k: int) -> ContingencySpace:
    return ContingencySpace(grid.n_branch, k, tuple(branch_keys(grid)))
