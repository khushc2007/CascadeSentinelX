// Grid bundles: layout + JS DC cascade engine + base-case frame, cached per grid.
import { load } from "./util.js";
import { DCCascade } from "../core/cascade.js";

const G = new Map();
export function gridBundle(id) {
  if (!G.has(id)) G.set(id, (async () => {
    const [grid, model, params] = await Promise.all([load(`grid_${id}.json`), load(`cascade_model_${id}.json`), load(`params_${id}.json`)]);
    if (!grid || !model) throw new Error(`missing data for ${id}`);
    const engine = new DCCascade(model); const base = engine.run([]).frames[0];
    return { id, grid, model, engine, base, params: params || null };      // params: MATPOWER source values for the Inspector (optional)
  })());
  return G.get(id);
}
export const dist = (id, k) => load(`dist_${id}_k${k}.json`);

// Rank of a severity among all N sets of a table: exact inside the stored top list, histogram-based (approximate) below it.
export function rankOf(d, S, band = 1e-9) {
  if (!d) return null;
  const top = d.top, minTop = top[top.length - 1][0];
  if (S >= minTop - band) { let above = 0; for (const [v] of top) if (v > S + band) above++; return { rank: above + 1, exact: true, N: d.N }; }
  const b = Math.min(d.bins - 1, Math.floor(S * d.bins)); let above = 0; for (let i = b + 1; i < d.bins; i++) above += d.hist[i];
  const inBin = d.hist[b], frac = d.bins * S - b; above += Math.round(inBin * (1 - frac));
  if (S <= band) return { rank: d.N - d.n_zero + 1, exact: false, zero: true, N: d.N };
  return { rank: above + 1, exact: false, N: d.N };
}
