// Layout model: the stored 2-D Kamada-Kawai coordinates (synthetic, not geographic) mapped to scene units, plus voltage-tier elevation when the
// case has several kV classes. Pure; the electrical graph is only read. Branch routes are quadratic arcs; parallel circuits get stacked arcs.

export const SEG = 12;                                   // conductor segments per branch

export function sceneLayout(model, { schematic = false } = {}) {
  const n = model.nBus, size = 7 * Math.sqrt(n) + 8, kvs = model.kvs, tiered = !schematic && kvs.length > 1, tierH = Math.max(1.2, size * 0.035);
  const tierOf = (kv) => (kv == null || !tiered ? 0 : kvs.indexOf(kv));
  const deg = model.buses.map((b) => b.branches.length);
  const bus = model.buses.map((b) => {
    const x = (model.layout.x[b.i] - 0.5) * size, z = (model.layout.y[b.i] - 0.5) * size, y = tierOf(b.base_kv) * tierH;
    const r = 0.32 + 0.07 * Math.sqrt(deg[b.i]), h = schematic ? 0.06 : 0.28;
    return { x, y, z, r, h, top: y + h };
  });
  // generator and load placement: offset from the bus, away from the bus's mean neighbour direction
  const away = model.buses.map((b) => {
    let dx = 0, dz = 0; for (const l of b.branches) { const br = model.branches[l], o = br.from === b.i ? br.to : br.from; dx += bus[o].x - bus[b.i].x; dz += bus[o].z - bus[b.i].z; }
    const L = Math.hypot(dx, dz) || 1; return [-dx / L, -dz / L];
  });
  const gen = model.gens.map((g) => {
    const s = 0.22 + 0.035 * Math.sqrt(Math.max(g.pmax_mw, 1)), [ax, az] = away[g.bus], k = model.buses[g.bus].gens.indexOf(g.g), side = [-az, ax];
    const d = bus[g.bus].r + s + 0.25, sp = (k - (model.buses[g.bus].gens.length - 1) / 2) * (2 * s + 0.12);
    return { x: bus[g.bus].x + ax * d + side[0] * sp, y: bus[g.bus].y, z: bus[g.bus].z + az * d + side[1] * sp, s, h: schematic ? 0.08 : 0.55 + s * 0.9 };
  });
  const maxLoad = Math.max(...model.loads.map((l) => l.demand_mw), 1);
  const load = model.loads.map((ld) => {
    const [ax, az] = away[ld.bus], side = [-az, ax], d = bus[ld.bus].r + 0.32, w = 0.34;
    return { x: bus[ld.bus].x - side[0] * d, y: bus[ld.bus].y, z: bus[ld.bus].z - side[1] * d, w, H: schematic ? 0.08 : 0.25 + 3.2 * (ld.demand_mw / maxLoad) };
  });
  const branch = model.branches.map((br) => {
    const a = bus[br.from], c = bus[br.to], span = Math.hypot(c.x - a.x, c.z - a.z, c.y - a.y);
    const lift = schematic ? 0.02 + br.parallel_index * 0.25 : Math.min(Math.max(0.16 * span, 0.35), size * 0.08) + br.parallel_index * 0.55;
    const p0 = [a.x, a.top, a.z], p2 = [c.x, c.top, c.z];
    // parallel circuits: offset sideways as well as up so they do not overlap in the schematic view
    const nx = -(c.z - a.z) / (span || 1), nz = (c.x - a.x) / (span || 1), off = br.parallel_index * (schematic ? 0.35 : 0.2);
    const p1 = [(a.x + c.x) / 2 + nx * off, (a.top + c.top) / 2 + lift * 2, (a.z + c.z) / 2 + nz * off];
    const pts = []; for (let i = 0; i <= SEG; i++) { const t = i / SEG, u = 1 - t; pts.push([0, 1, 2].map((j) => u * u * p0[j] + 2 * u * t * p1[j] + t * t * p2[j])); }
    return { pts, span, mid: pts[SEG / 2] };
  });
  const xs = bus.map((b) => b.x), zs = bus.map((b) => b.z), ys = bus.map((b) => b.y);
  const bounds = { minX: Math.min(...xs), maxX: Math.max(...xs), minZ: Math.min(...zs), maxZ: Math.max(...zs), maxY: Math.max(...ys) + 4 };
  return { size, tiered, tierH, bus, gen, load, branch, bounds, maxLoad };
}

export function pointAt(route, t) {                      // position along a branch route, t in [0,1]
  const f = t * SEG, i = Math.min(Math.floor(f), SEG - 1), k = f - i, a = route.pts[i], b = route.pts[i + 1];
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}
