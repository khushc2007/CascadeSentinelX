// Phase 9: JavaScript port of doomsday/experiments/ranking_metrics.py (tie-aware top-T, Jaccard, Spearman with average ranks).
export const BAND = 1e-9;
export function sT(S, T) { if (!(1 <= T && T <= S.length)) throw new Error("T must be in [1, N]"); return Array.from(S).sort((a, b) => b - a)[T - 1]; }
export function tieExpandedTopT(S, T, band = BAND) { const s = sT(S, T); const out = []; S.forEach((v, i) => { if (v >= s - band) out.push(i); }); return out; }
export function jaccard(a, b) { const A = new Set(a), B = new Set(b); const u = new Set([...A, ...B]); if (!u.size) return 1.0; let i = 0; for (const x of A) if (B.has(x)) i++; return i / u.size; }
export function averageRanks(x) {
  const idx = Array.from(x.keys()).sort((i, j) => x[i] - x[j]); const r = new Float64Array(x.length); let i = 0;
  while (i < idx.length) { let j = i; while (j + 1 < idx.length && x[idx[j + 1]] === x[idx[i]]) j++; const avg = (i + j) / 2 + 1; for (let t = i; t <= j; t++) r[idx[t]] = avg; i = j + 1; }
  return r;
}
export function spearman(a, b) {
  const ra = averageRanks(a), rb = averageRanks(b), n = a.length; const ma = ra.reduce((s, v) => s + v, 0) / n, mb = rb.reduce((s, v) => s + v, 0) / n;
  let sab = 0, saa = 0, sbb = 0; for (let i = 0; i < n; i++) { const da = ra[i] - ma, db = rb[i] - mb; sab += da * db; saa += da * da; sbb += db * db; }
  return saa === 0 || sbb === 0 ? NaN : sab / Math.sqrt(saa * sbb);
}
export function distinctLevels(values, band = BAND) { const v = Array.from(values).sort((a, b) => b - a); if (!v.length) return 0; let n = 1; for (let i = 1; i < v.length; i++) if (v[i - 1] - v[i] > band) n++; return n; }
