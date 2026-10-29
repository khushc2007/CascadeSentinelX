// Contextual city: low, dark, deterministic blocks that give the synthetic layout a sense of ground and scale. They are decoration, not
// data: no block corresponds to a load, customer or place, none is selectable, and none is placed within a clearance of any bus,
// generator, demand column or branch route, so the city never hides or imitates electrical equipment. Pure and deterministic for a given
// layout (tested in app/test/scene.test.mjs). Context modes: "spatial" (city shown, subdued), "focus" (city lowered and darkened,
// reference grid dimmed), "grid" (grid only: no city, no reference grid).
import { SEG } from "./layout.js";

export const CONTEXT_MODES = ["spatial", "focus", "grid"];
export const CLEAR = { bus: 1.15, equip: 0.75, branch: 0.85 };   // clearance from equipment and branch routes (scene units, plan view)

function hash(i, j, s) { let h = (i * 374761393 + j * 668265263 + s * 2147483647) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; }

// shortest plan-view (x, z) distance from p to segment a-b
function segDist(px, pz, ax, az, bx, bz) { const vx = bx - ax, vz = bz - az, ll = vx * vx + vz * vz || 1; const t = Math.max(0, Math.min(1, ((px - ax) * vx + (pz - az) * vz) / ll)); return Math.hypot(px - ax - vx * t, pz - az - vz * t); }

export function clearanceOK(L, x, z, half) {
  for (const b of L.bus) if (Math.hypot(x - b.x, z - b.z) < b.r + CLEAR.bus + half) return false;
  for (const g of L.gen) if (Math.hypot(x - g.x, z - g.z) < g.s + CLEAR.equip + half) return false;
  for (const d of L.load) if (Math.hypot(x - d.x, z - d.z) < d.w + CLEAR.equip + half) return false;
  for (const rt of L.branch) for (let i = 0; i < SEG; i++) { const a = rt.pts[i], b = rt.pts[i + 1]; if (segDist(x, z, a[0], a[2], b[0], b[2]) < CLEAR.branch + half) return false; }
  return true;
}

// spatial index of everything a block must stay clear of (buckets of size B in plan view), so each candidate checks only nearby items
function obstacleIndex(L, B) {
  const grid = new Map(), key = (i, j) => `${i},${j}`, put = (x0, z0, x1, z1, item) => {
    for (let i = Math.floor(Math.min(x0, x1) / B); i <= Math.floor(Math.max(x0, x1) / B); i++) for (let j = Math.floor(Math.min(z0, z1) / B); j <= Math.floor(Math.max(z0, z1) / B); j++) {
      const k = key(i, j); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(item); } };
  L.bus.forEach((b) => put(b.x - b.r, b.z - b.r, b.x + b.r, b.z + b.r, { t: "c", x: b.x, z: b.z, r: b.r + CLEAR.bus }));
  L.gen.forEach((g) => put(g.x - g.s, g.z - g.s, g.x + g.s, g.z + g.s, { t: "c", x: g.x, z: g.z, r: g.s + CLEAR.equip }));
  L.load.forEach((d) => put(d.x - d.w, d.z - d.w, d.x + d.w, d.z + d.w, { t: "c", x: d.x, z: d.z, r: d.w + CLEAR.equip }));
  L.branch.forEach((rt) => { for (let i = 0; i < SEG; i++) { const a = rt.pts[i], c = rt.pts[i + 1]; put(a[0], a[2], c[0], c[2], { t: "s", ax: a[0], az: a[2], bx: c[0], bz: c[2], r: CLEAR.branch }); } });
  return { near(x, z, reach) { const out = new Set(); for (let i = Math.floor((x - reach) / B); i <= Math.floor((x + reach) / B); i++) for (let j = Math.floor((z - reach) / B); j <= Math.floor((z + reach) / B); j++) { const g = grid.get(key(i, j)); if (g) g.forEach((o) => out.add(o)); } return out; } };
}

export function cityBlocks(L, { cell = 1.7, fill = 0.58, seed = 7 } = {}) {
  const b = L.bounds, m = 6, x0 = b.minX - m, x1 = b.maxX + m, z0 = b.minZ - m, z1 = b.maxZ + m, out = [];
  const maxR = Math.max(...L.bus.map((q) => q.r + CLEAR.bus), ...L.gen.map((g) => g.s + CLEAR.equip), ...L.load.map((d) => d.w + CLEAR.equip), CLEAR.branch);
  const idx = obstacleIndex(L, 4), clear = (x, z, half) => { for (const o of idx.near(x, z, maxR + half + 0.01)) {
    if (o.t === "c" ? Math.hypot(x - o.x, z - o.z) < o.r + half : segDist(x, z, o.ax, o.az, o.bx, o.bz) < o.r + half) return false; } return true; };
  for (let i = 0, x = x0; x < x1; i++, x += cell) for (let j = 0, z = z0; z < z1; j++, z += cell) {
    const r = hash(i, j, seed); if (r > fill) continue;
    const w = cell * (0.48 + 0.3 * hash(i, j, seed + 1)), d = cell * (0.48 + 0.3 * hash(i, j, seed + 2)), cx = x + cell / 2, cz = z + cell / 2;
    if (!clear(cx, cz, Math.max(w, d) / 2)) continue;                            // same rule as clearanceOK(), via the index
    const t = hash(i, j, seed + 3), h = t > 0.97 ? 1.1 + 0.6 * hash(i, j, seed + 4) : 0.12 + 0.55 * t * t;   // mostly low; a few taller blocks
    out.push({ x: cx, z: cz, w, d, h });
  }
  return out;
}
