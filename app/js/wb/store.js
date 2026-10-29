// Minimal state container with independent slices. set() merges a partial update and notifies subscribers with the set of changed slice
// names, so panels re-render only for the slices they show.
export function createStore(initial) {
  let s = { ...initial }; const subs = new Set();
  return {
    get: () => s,
    set(patch) {
      const p = typeof patch === "function" ? patch(s) : patch, changed = new Set();
      for (const k of Object.keys(p)) if (s[k] !== p[k]) changed.add(k);
      if (!changed.size) return; s = { ...s, ...p }; subs.forEach((f) => f(s, changed));
    },
    sub(f) { subs.add(f); return () => subs.delete(f); },
  };
}

export const DEFAULT_LAYERS = Object.freeze({ equipment: true, context: true, loads: true, flow: true, utilization: true, outages: true, islands: true, reference: true, labels: "key", reduced: false, isolate: null, neighbourhood: null });
