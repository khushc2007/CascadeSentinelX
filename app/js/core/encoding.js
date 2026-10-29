// Data → visual state. Pure functions shared by the 3-D scene, the explorer and the tests. The utilisation bands are the engine's own
// (trip when loading > trip_factor + tol); the scene never decides anything the engine did not.

export const WARN = 0.8;
export function utilBand(u, tripFactor = 1.0, tol = 1e-9) { if (u == null) return "unknown"; if (u > tripFactor + tol) return "overload"; if (u > WARN) return "warning"; return "normal"; }

// state of a branch in a given view: frame may be null (base case)
export function branchState(br, frame, outageSet, tripRound, deadBusIds) {
  if (outageSet.has(br.l)) return "initial_outage";
  if (tripRound.has(br.l) && frame && frame.out_of_service.includes(br.l)) return "tripped";
  if (!br.in_service) return "unavailable";
  if (frame && frame.out_of_service.includes(br.l)) return "tripped";
  if (deadBusIds && deadBusIds.has(br.fromId) && deadBusIds.has(br.toId)) return "deenergized";
  const u = frame ? frame.loading[br.l] : br.base_loading_dc;
  const b = utilBand(u); return b === "unknown" ? "normal" : b;
}

// view model for the scene and panels at one frame (or the base case when frame is null)
export function viewState(model, res, frameIndex, tripRoundMap) {
  const frame = res && res.frames ? res.frames[Math.min(frameIndex, res.frames.length - 1)] : null;
  const outageSet = new Set(res ? res.outage : []);
  const energized = frame ? new Set(frame.energized_buses) : null;
  const dead = energized ? new Set(model.buses.filter((b) => !energized.has(b.id)).map((b) => b.id)) : new Set();
  const trips = tripRoundMap || new Map();
  const branches = model.branches.map((br) => {
    const st = branchState(br, frame, outageSet, trips, dead);
    const u = frame ? frame.loading[br.l] ?? null : br.base_loading_dc;
    const flow = frame ? (frame.flow ? frame.flow[br.l] ?? null : null) : null;
    return { state: st, u: st === "initial_outage" || st === "tripped" ? null : u, flow_mw: flow, tripRound: trips.get(br.l) ?? null, overloaded: frame ? frame.overloaded.includes(br.l) : false };
  });
  const comp = frame && frame.component ? frame.component : null, sizes = new Map();
  if (comp) model.buses.forEach((b) => { if (!dead.has(b.id)) sizes.set(comp[b.i], (sizes.get(comp[b.i]) || 0) + 1); });
  let main = null, best = -1; sizes.forEach((n, c) => { if (n > best) { best = n; main = c; } });
  const buses = model.buses.map((b) => ({ energized: !dead.has(b.id), component: comp ? comp[b.i] : null, mainIsland: comp ? comp[b.i] === main : true,
    served_fraction: frame && frame.factor ? frame.factor[b.i] : (frame ? (dead.has(b.id) ? 0 : null) : 1) }));
  const gens = model.gens.map((g) => ({ pg_mw: frame ? (frame.pg ? frame.pg[g.g] : null) : g.pg0_mw, energized: !dead.has(g.busId) }));
  const islandIds = [...sizes.keys()].sort((a, c) => a - c);
  return { frame, frameIndex, branches, buses, gens, islandIds, mainIsland: main, loadServed: frame ? frame.load_served : 1 };
}

// muted ramp for the utilisation layer below the warning band (steel, darker = lightly loaded)
export function utilRamp(u) {
  const t = Math.min(Math.max((u ?? 0) / WARN, 0), 1), a = [0x6a, 0x74, 0x7e], b = [0xc3, 0xce, 0xd8];
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}
