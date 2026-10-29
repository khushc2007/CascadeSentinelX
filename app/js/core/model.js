// Electrical graph for the workbench: immutable, built from grid_<id>.json (topology, ratings, layout) and cascade_model_<id>.json
// (engine inputs). Stable ids: branch:<index>, bus:<case bus number>, gen:<index>, load:<case bus number>. Units are explicit in field names.

export function buildModel(grid, cm) {
  if (grid.n_bus !== cm.n_bus || grid.n_branch !== cm.n_branch) throw new Error("grid and cascade model disagree on size");
  const buses = grid.buses.map((b) => ({ kind: "bus", key: `bus:${b.id}`, i: b.i, id: b.id, load_mw: cm.Pd[b.i], base_kv: b.base_kv > 0 ? b.base_kv : null,
    gens: [], branches: [], is_slack: b.id === grid.slack_bus }));
  const pairCount = new Map(), pairSeen = new Map(), pairKey = (a, c) => (a < c ? `${a}-${c}` : `${c}-${a}`);
  grid.branches.forEach((br) => pairCount.set(pairKey(br.from, br.to), (pairCount.get(pairKey(br.from, br.to)) || 0) + 1));
  const branches = grid.branches.map((br) => {
    const pk = pairKey(br.from, br.to), k = pairSeen.get(pk) || 0; pairSeen.set(pk, k + 1);
    buses[br.from].branches.push(br.l); buses[br.to].branches.push(br.l);
    return { kind: "branch", key: `branch:${br.l}`, l: br.l, from: br.from, to: br.to, fromId: buses[br.from].id, toId: buses[br.to].id,
      transformer: !!br.transformer, rating_dc_mw: br.rating_dc_mw, rating_ac_mva: br.rating_ac_mva, x_pu: cm.x[br.l], in_service: cm.br_status[br.l] > 0,
      base_loading_dc: br.base_loading_dc, parallel_index: k, parallel_count: pairCount.get(pk) };
  });
  const gens = cm.gen_bus.map((bi, g) => ({ kind: "gen", key: `gen:${g}`, g, bus: bi, busId: buses[bi].id, pmax_mw: cm.gen_Pmax[g], pmin_mw: cm.gen_Pmin[g],
    pg0_mw: cm.pg0[g], in_service: cm.gen_status[g] > 0 }));
  gens.forEach((gn) => buses[gn.bus].gens.push(gn.g));
  const loads = buses.filter((b) => b.load_mw > 0).map((b) => ({ kind: "load", key: `load:${b.id}`, bus: b.i, busId: b.id, demand_mw: b.load_mw }));
  const byKey = new Map(); [...buses, ...branches, ...gens, ...loads].forEach((e) => byKey.set(e.key, e));
  const busById = new Map(buses.map((b) => [b.id, b]));
  const kvs = [...new Set(buses.map((b) => b.base_kv).filter((v) => v != null))].sort((a, b) => a - b);
  return { id: grid.id, nBus: grid.n_bus, nBranch: grid.n_branch, buses, branches, gens, loads, byKey, busById, kvs,
    totalLoadMw: cm.initial_load_mw, slackBusId: grid.slack_bus, layout: grid.layout, ratingFamily: grid.rating_family,
    provenance: { source: grid.provenance, matpower_commit: grid.matpower_commit, file_sha256: grid.file_sha256 }, config: cm.cascade, severity: cm.severity };
}

export function parseKey(key) { const [kind, v] = String(key).split(":"); return { kind, v: Number(v) }; }
export function entityLabel(m, key) {
  const e = m.byKey.get(key); if (!e) return key;
  if (e.kind === "branch") return `${e.transformer ? "Transformer" : "Line"} ${e.l} · bus ${e.fromId}–${e.toId}`;
  if (e.kind === "bus") return `Bus ${e.id}`;
  if (e.kind === "gen") return `Generator ${e.g} · bus ${e.busId}`;
  return `Load · bus ${e.busId}`;
}
