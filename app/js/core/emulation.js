// Phase 9: JavaScript port of doomsday/qsearch Tier B (V2 13.2): EXACT CLASSICAL EMULATION of ideal Grover dynamics in the weight-k subspace,
// BBHT and Durr-Hoyer control logic, and both top-T schemes. Not a quantum runtime. Deterministic functions are parity-tested to 1e-12 against
// Python; stochastic ones use their own seeded PRNG (not numpy's), so they are parity-tested statistically (means within stated bounds).
export const BAND = 1e-9;

export function rng(seed) {                         // mulberry32: small, seedable, uniform in [0,1)
  let a = seed >>> 0;
  const next = () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  return { random: next, integers: (lo, hi) => lo + Math.floor(next() * (hi - lo)) };   // [lo, hi)
}

export function thetaOf(N, M) { if (!(0 <= M && M <= N) || N < 1) throw new Error("need 0 <= M <= N, N >= 1"); return Math.asin(Math.sqrt(M / N)); }
export const pClosed = (r, N, M) => Math.sin((2 * r + 1) * thetaOf(N, M)) ** 2;
export const optimalR = (N, M) => (M === 0 ? 0 : Math.floor(Math.PI / (4 * thetaOf(N, M))));
export function collapsedTrajectory(N, M, rMax) {
  const a = [N ** -0.5], b = [N ** -0.5], p = [];
  for (let r = 0; r < rMax; r++) { const ap = -a[r], bp = b[r], mu = (M * ap + (N - M) * bp) / N; a.push(2 * mu - ap); b.push(2 * mu - bp); }
  for (let r = 0; r <= rMax; r++) p.push(M * a[r] ** 2);
  return { alpha: a, beta: b, p_marked: p };
}
export function fullVectorTrajectory(marked, rMax) {             // marked: boolean array; returns per-r amplitudes and P(marked)
  const N = marked.length; let psi = new Float64Array(N).fill(N ** -0.5); const rows = [Float64Array.from(psi)], pm = [];
  const pmk = (v) => v.reduce((s, x, i) => s + (marked[i] ? x * x : 0), 0); pm.push(pmk(psi));
  for (let r = 0; r < rMax; r++) {
    for (let i = 0; i < N; i++) if (marked[i]) psi[i] = -psi[i];
    let mean = 0; for (let i = 0; i < N; i++) mean += psi[i]; mean /= N;
    for (let i = 0; i < N; i++) psi[i] = 2 * mean - psi[i];
    rows.push(Float64Array.from(psi)); pm.push(pmk(psi));
  }
  return { amplitudes: rows, p_marked: pm };
}

export class MarkedSet {                                           // marked ranks (sorted unique) inside [0, N)
  constructor(N, ranks) {
    this.N = N; this.ranks = Int32Array.from([...new Set(ranks)].sort((x, y) => x - y)); this.M = this.ranks.length;
    this.adj = this.ranks.map((r, i) => r - i);
  }
  pSuccess(j) { if (this.M === 0) return 0; if (this.M === this.N) return 1; return Math.sin((2 * j + 1) * thetaOf(this.N, this.M)) ** 2; }
  unmarkedRank(u) { let lo = 0, hi = this.M; while (lo < hi) { const m = (lo + hi) >> 1; if (this.adj[m] <= u) lo = m + 1; else hi = m; } return u + lo; }
  sample(j, g) { return g.random() < this.pSuccess(j) ? this.ranks[g.integers(0, this.M)] : this.unmarkedRank(g.integers(0, this.N - this.M)); }
}
const counter = () => ({ quantum_oracle_calls: 0, grover_iterations: 0, attempts: 0, verifications: 0 });
const attempt = (c, j) => { c.attempts++; c.grover_iterations += j; c.quantum_oracle_calls += j + 1; c.verifications++; };

export function bbhtSearch(marked, verify, g, lam = 6 / 5, mCap = null, patience = 3) {
  const N = marked.N; mCap = mCap ?? Math.sqrt(N); const c = counter(); let fails = 0, found = false, x = null;
  while (fails < patience && !found) {
    let m = 1.0;
    while (m <= mCap && !found) { const j = g.integers(0, Math.ceil(m)); const s = marked.sample(j, g); attempt(c, j); if (verify(s)) { found = true; x = s; break; } m *= lam; }
    if (!found) fails++;
  }
  return { found, x, counter: c };
}

export function dhMax(S, g, y0 = 0.0, lam = 6 / 5, patience = 3, band = BAND) {
  const N = S.length, mCap = Math.sqrt(N), c = counter(); let Smax = -Infinity; for (const v of S) if (v > Smax) Smax = v;
  let y = y0, best = null, fails = 0, disc = null; const trace = [];
  while (fails < patience) {
    const idx = []; for (let i = 0; i < N; i++) if (S[i] > y + band) idx.push(i);
    const ms = new MarkedSet(N, idx); let m = 1.0, found = false;
    while (m <= mCap) {
      const j = g.integers(0, Math.ceil(m)); const x = ms.sample(j, g); attempt(c, j);
      if (S[x] > y + band) { y = S[x]; best = x; found = true; trace.push([c.quantum_oracle_calls, y]); if (disc === null && y >= Smax - band) disc = c.quantum_oracle_calls; break; }
      m *= lam;
    }
    fails = found ? 0 : fails + 1;
  }
  return { best, y, counter: c, discovery_quantum_calls: disc, found_Smax: disc !== null, trace };
}

export function topTThreshold(S, T, g, patience = 3, band = BAND) {
  const N = S.length; const pool = Array.from({ length: N }, (_, i) => i); const lst = [];
  for (let i = 0; i < T; i++) { const r = i + g.integers(0, N - i); [pool[i], pool[r]] = [pool[r], pool[i]]; lst.push(pool[i]); }
  const inl = new Uint8Array(N); lst.forEach((i) => (inl[i] = 1)); let q = 0;
  for (;;) {
    let iMin = 0; for (let i = 1; i < T; i++) if (S[lst[i]] < S[lst[iMin]]) iMin = i;
    const y = S[lst[iMin]], idx = []; for (let i = 0; i < N; i++) if (S[i] > y + band && !inl[i]) idx.push(i);
    const r = bbhtSearch(new MarkedSet(N, idx), (x) => S[x] > y + band && !inl[x], g, 6 / 5, null, patience); q += r.counter.quantum_oracle_calls;
    if (!r.found) break;
    inl[lst[iMin]] = 0; lst[iMin] = r.x; inl[r.x] = 1;
  }
  const got = lst.map((i) => S[i]).sort((a, b) => b - a), tru = Array.from(S).sort((a, b) => b - a).slice(0, T);
  return { found: lst, quantum_oracle_calls: q, correct: got.every((v, i) => Math.abs(v - tru[i]) <= band) };
}
