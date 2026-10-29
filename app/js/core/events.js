// Cascade result → ordered event list. Only facts present in the engine's frames are turned into events; nothing is interpolated.
// Order inside a round follows the engine (gridtwin/cascade.py): connectivity → island balancing / load curtailment → power flow →
// overload detection → trips. Each event names the frame that shows the state it describes.

const EPS = 1e-9;

export function buildEvents(res, model) {
  const fr = res.frames || [], ev = [], key = (l) => `branch:${l}`, busKey = (id) => `bus:${id}`;
  const allBusIds = model.buses.map((b) => b.id);
  ev.push({ type: "initial_outage", round: 0, frame: 0, entities: res.outage.map(key),
    title: `Initial outage of ${res.outage.length} branch${res.outage.length > 1 ? "es" : ""}`,
    detail: res.outage.map((l) => `${l} (bus ${model.branches[l].fromId}–${model.branches[l].toId})`).join(", ") });
  const liveIslands = (f) => { if (!f.component) return null; const en = new Set(f.energized_buses), c = new Set(); model.buses.forEach((b) => { if (en.has(b.id)) c.add(f.component[b.i]); }); return c.size; };
  for (let r = 0; r < fr.length; r++) {
    const f = fr[r], prev = r > 0 ? fr[r - 1] : null, R = r + 1, live = liveIslands(f), dead = model.nBus - f.energized_buses.length;
    const comp = live == null ? `${f.islands} connected component${f.islands > 1 ? "s" : ""}` : `${live} energised island${live > 1 ? "s" : ""}${dead ? ` + ${dead} de-energised bus${dead > 1 ? "es" : ""}` : ""}`;
    ev.push({ type: "round", round: R, frame: r, entities: [], values: { components: f.islands, energisedIslands: live, deadBuses: dead },
      title: `Round ${R}: DC power flow on ${live ?? f.islands} ${live == null ? "component" : "energised island"}${(live ?? f.islands) > 1 ? "s" : ""}`, detail: `${comp}; ${(100 * f.load_served).toFixed(1)}% of demand served` });
    const prevEnergized = new Set(prev ? prev.energized_buses : allBusIds), nowEnergized = new Set(f.energized_buses);
    const lost = [...prevEnergized].filter((id) => !nowEnergized.has(id));
    if ((r === 0 && f.islands > 1) || (prev && f.islands !== prev.islands) || lost.length) {
      ev.push({ type: "islanding", round: R, frame: r, entities: lost.map(busKey), values: { islands: f.islands, energisedIslands: live, deenergized: lost },
        title: live == null ? `Network now has ${f.islands} connected components` : `${live} energised island${live > 1 ? "s" : ""}, ${dead} bus${dead === 1 ? "" : "es"} without generation`, detail: lost.length ? `${lost.length} bus${lost.length > 1 ? "es" : ""} lose all generation and are de-energised: ${lost.slice(0, 12).join(", ")}${lost.length > 12 ? "…" : ""}` : "no bus de-energised" });
    }
    const before = prev ? prev.load_served : 1;
    if (f.load_served < before - EPS) {
      let shedBuses = [];
      if (f.factor && (!prev || prev.factor)) shedBuses = model.buses.filter((b) => b.load_mw > 0 && f.factor[b.i] < (prev ? prev.factor[b.i] : 1) - EPS).map((b) => busKey(b.id));
      else shedBuses = lost.map(busKey);
      ev.push({ type: "load_shed", round: R, frame: r, entities: shedBuses, values: { served: f.load_served, drop: before - f.load_served },
        title: `Demand served falls to ${(100 * f.load_served).toFixed(1)}%`, detail: `−${(100 * (before - f.load_served)).toFixed(1)} percentage points of base demand (islands without generation, or curtailment where generation is short)` });
    }
    if (f.overloaded.length) {
      const peak = Math.max(...f.overloaded.map((l) => f.loading[l]));
      ev.push({ type: "overload", round: R, frame: r, entities: f.overloaded.map(key), values: { loading: Object.fromEntries(f.overloaded.map((l) => [l, f.loading[l]])) },
        title: `${f.overloaded.length} branch${f.overloaded.length > 1 ? "es" : ""} above rating (peak ${(100 * peak).toFixed(0)}%)`, detail: f.overloaded.map((l) => `${l}: ${(100 * f.loading[l]).toFixed(0)}%`).join(", ") });
    }
    if (f.tripped.length) {
      ev.push({ type: "trip", round: R, frame: r + 1 < fr.length ? r + 1 : r, applied: r + 1 < fr.length, entities: f.tripped.map(key),
        title: `${f.tripped.length} branch${f.tripped.length > 1 ? "es" : ""} tripped (${res.policy === "most_overloaded_first" ? "most overloaded first" : "all overloaded"})`, detail: f.tripped.join(", ") });
    }
  }
  const m = res.metrics;
  ev.push({ type: "termination", round: fr.length, frame: Math.max(fr.length - 1, 0), entities: [], values: { S: m.S, S0: m.S0, C: m.C, status: m.status },
    title: `${m.status}: ${(100 * m.S).toFixed(1)}% of base demand unserved`, detail: `S₀ = ${(100 * m.S0).toFixed(1)}% from the initial islanding, C = S − S₀ = ${(100 * m.C).toFixed(1)}% from cascade trips; ${m.rounds} round${m.rounds > 1 ? "s" : ""}` });
  return ev.map((e, i) => ({ ...e, i }));
}

export const tripRounds = (res) => { const m = new Map(); (res.trips_per_round || res.frames?.map((f) => f.tripped) || []).forEach((t, r) => t.forEach((l) => m.set(l, r + 1))); return m; };
