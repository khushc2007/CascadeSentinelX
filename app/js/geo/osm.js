// Bengaluru Grid Explorer — data model. Pure functions (tested in app/test/geo.test.mjs): build the Overpass query, turn an Overpass
// response (or a GeoJSON file the user loads) into records that keep their source, and compute coverage, filters and search.
// Rules: every record comes from a source element; nothing is inferred that the source does not state. In particular a mapped power line is
// never connected to a substation by proximity, voltages are only those tagged, and no record is labelled official or verified.

export const AREA = { name: "Bengaluru query extent", south: 12.80, west: 77.40, north: 13.20, east: 77.85,
  note: "A rectangular bounding box around Bengaluru used for the query. It is not an administrative boundary." };
export const CENTER = [77.5946, 12.9716];               // lon, lat (central Bengaluru), overview camera only
export const ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"];
// display names follow the OpenStreetMap tag (power=line is a major power line as judged by the mapper, not a verified transmission asset)
export const KINDS = { substation: "Substation", plant: "Power plant", line: "Power line (power=line)", minor_line: "Minor power line (power=minor_line)", cable: "Power cable (power=cable)" };
export const VCLASSES = [["v400", "≥ 400 kV", 400], ["v220", "220–399 kV", 220], ["v110", "110–219 kV", 110], ["v66", "66–109 kV", 66], ["v33", "< 66 kV", 0], ["vna", "voltage not tagged", null]];
export const LICENSE = { name: "Open Database License (ODbL) 1.0", url: "https://www.openstreetmap.org/copyright" };

export function overpassQuery(a = AREA) {
  const bb = `${a.south},${a.west},${a.north},${a.east}`;
  return `[out:json][timeout:120];\n(\n  nwr["power"~"^(substation|plant)$"](${bb});\n  way["power"~"^(line|minor_line|cable)$"](${bb});\n);\nout body geom qt;`;
}

// "220000;66000" → [220, 66]; "33 kV" → [33]; unparseable parts are dropped (and the raw tag is kept on the record)
export function parseVoltages(tag) {
  if (tag == null || tag === "") return [];
  return String(tag).split(/[;,/]/).map((p) => { const m = /([0-9]+(?:\.[0-9]+)?)\s*(k?v)?/i.exec(p.trim()); if (!m) return null; const v = +m[1]; return /kv/i.test(m[2] || "") ? v : v >= 1000 ? v / 1000 : v; })
    .filter((v) => v != null && v > 0).map((v) => Math.round(v * 10) / 10).sort((a, b) => b - a);
}
export function voltageClass(kv) {
  if (!kv.length) return "vna"; const v = kv[0];
  return v >= 400 ? "v400" : v >= 220 ? "v220" : v >= 110 ? "v110" : v >= 66 ? "v66" : "v33";
}

const centroid = (pts) => { let x = 0, y = 0; for (const [lon, lat] of pts) { x += lon; y += lat; } return [x / pts.length, y / pts.length]; };
const closed = (pts) => pts.length > 3 && pts[0][0] === pts[pts.length - 1][0] && pts[0][1] === pts[pts.length - 1][1];

function baseRecord(kind, tags, prov) {
  const kv = parseVoltages(tags.voltage), name = tags.name || tags["name:en"] || null;
  return { kind, name, nameKn: tags["name:kn"] || null, ref: tags.ref || null, operator: tags.operator || null, voltageTag: tags.voltage ?? null, kv, vclass: voltageClass(kv),
    tags: { ...tags }, prov };
}

// Overpass JSON → records. prov: { via, retrievedAt, osmBase, file }
export function fromOverpass(json, prov = {}) {
  const out = [], els = (json && json.elements) || [];
  for (const el of els) {
    const tags = el.tags || {}, p = tags.power; if (!p || !KINDS[p]) continue;
    const url = `https://www.openstreetmap.org/${el.type}/${el.id}`;
    const P = { source: "OpenStreetMap", sourceId: `${el.type}/${el.id}`, url, license: LICENSE.name, via: prov.via || null, retrievedAt: prov.retrievedAt || null, osmBase: prov.osmBase || null, file: prov.file || null };
    const r = baseRecord(p, tags, P); r.id = `osm:${el.type}/${el.id}`;
    if (el.type === "node") { if (el.lat == null) continue; r.point = [el.lon, el.lat]; r.precision = "point as mapped"; }
    else if (el.type === "way") {
      const pts = (el.geometry || []).filter(Boolean).map((g) => [g.lon, g.lat]); if (pts.length < 2) continue;
      if (p === "line" || p === "minor_line" || p === "cable") { r.line = pts; r.precision = "line geometry as mapped"; }
      else { if (closed(pts)) r.polygon = pts; r.point = centroid(closed(pts) ? pts.slice(0, -1) : pts); r.precision = closed(pts) ? "mapped outline; marker at the vertex mean" : "open way; marker at the vertex mean"; }
    } else if (el.type === "relation") {
      if (p === "line" || p === "minor_line" || p === "cable") continue;            // line relations are not drawn (members are fetched as ways)
      const pts = []; for (const m of el.members || []) for (const g of m.geometry || []) if (g) pts.push([g.lon, g.lat]);
      if (el.center) r.point = [el.center.lon, el.center.lat]; else if (el.bounds) r.point = [(el.bounds.minlon + el.bounds.maxlon) / 2, (el.bounds.minlat + el.bounds.maxlat) / 2];
      else if (pts.length) { const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]); r.point = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]; }
      else continue;
      r.precision = "relation; marker at the centre of its members' extent";
    } else continue;
    r.status = statusLabels(r); out.push(r);
  }
  return out;
}

// GeoJSON FeatureCollection (e.g. an export the user made) → records; only features with a power=* property the explorer knows
export function fromGeoJSON(gj, prov = {}) {
  const out = []; let n = 0;
  for (const f of (gj && gj.features) || []) {
    const props = f.properties || {}, tags = props.tags && typeof props.tags === "object" ? props.tags : props, p = tags.power; n++;
    if (!p || !KINDS[p] || !f.geometry) continue;
    const sid = props["@id"] || props.id || f.id || `feature/${n}`;
    const osmLike = /^(node|way|relation)\/\d+$/.test(String(sid));
    const P = { source: osmLike ? "OpenStreetMap (via the loaded file)" : "Loaded file", sourceId: String(sid), url: osmLike ? `https://www.openstreetmap.org/${sid}` : null,
      license: osmLike ? LICENSE.name : "as stated by the file's publisher", via: null, retrievedAt: prov.retrievedAt || null, osmBase: null, file: prov.file || null };
    const r = baseRecord(p, tags, P); r.id = `file:${sid}`; const g = f.geometry;
    if (g.type === "Point") { r.point = g.coordinates.slice(0, 2); r.precision = "point as given in the file"; }
    else if (g.type === "LineString" && ["line", "minor_line", "cable"].includes(p)) { r.line = g.coordinates.map((c) => c.slice(0, 2)); r.precision = "line geometry as given in the file"; }
    else if (g.type === "Polygon") { r.polygon = g.coordinates[0].map((c) => c.slice(0, 2)); r.point = centroid(r.polygon.slice(0, -1)); r.precision = "outline from the file; marker at the vertex mean"; }
    else if (g.type === "LineString") { r.point = centroid(g.coordinates); r.precision = "marker at the vertex mean"; }
    else continue;
    r.status = statusLabels(r); out.push(r);
  }
  return out;
}

// Status labels are derived only from what the record carries. "Official source" and "independently verified" are never assigned here:
// no loaded source establishes them.
export function statusLabels(r) {
  const s = [r.prov.source.startsWith("OpenStreetMap") ? "Public mapped data (OpenStreetMap)" : "User-supplied file"];
  s.push(r.kv.length ? "Voltage tagged by the mapper" : "Voltage not tagged");
  if (r.line) s.push("Unverified connectivity: line ends are not matched to substations");
  if (r.kind === "substation" || r.kind === "plant") s.push("Not cross-checked against KPTCL/BESCOM records");
  if (!r.name) s.push("Incomplete record: no name");
  if (/vertex mean|extent/.test(r.precision || "")) s.push("Approximate marker position");
  return s;
}

export function coverage(recs) {
  const by = Object.fromEntries(Object.keys(KINDS).map((k) => [k, 0])), vc = Object.fromEntries(VCLASSES.map(([k]) => [k, 0])), ops = new Map(); let named = 0, volt = 0;
  for (const r of recs) { by[r.kind]++; vc[r.vclass]++; if (r.name) named++; if (r.kv.length) volt++; const o = r.operator || "(not tagged)"; ops.set(o, (ops.get(o) || 0) + 1); }
  let lineKm = 0; for (const r of recs) if (r.line) for (let i = 1; i < r.line.length; i++) lineKm += haversineKm(r.line[i - 1], r.line[i]);
  return { total: recs.length, byKind: by, byVoltage: vc, named, withVoltage: volt, operators: [...ops.entries()].sort((a, b) => b[1] - a[1]), lineKm };
}
export function haversineKm([lo1, la1], [lo2, la2]) { const R = 6371.0088, r = Math.PI / 180, dla = (la2 - la1) * r, dlo = (lo2 - lo1) * r; const a = Math.sin(dla / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dlo / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(a)); }

// filters: { kinds:Set, vclasses:Set, operator: string|null ("(not tagged)" for missing), namedOnly: bool }
export function applyFilters(recs, f) {
  return recs.filter((r) => f.kinds.has(r.kind) && f.vclasses.has(r.vclass) && (!f.operator || (r.operator || "(not tagged)") === f.operator) && (!f.namedOnly || !!r.name));
}
export function search(recs, q, limit = 30) {
  const t = String(q || "").trim().toLowerCase(); if (!t) return [];
  const score = (r) => { const fields = [r.name, r.nameKn, r.ref, r.operator, r.prov.sourceId, r.id].filter(Boolean).map((x) => String(x).toLowerCase());
    if (fields.some((x) => x === t)) return 3; if (fields.some((x) => x.startsWith(t))) return 2; if (fields.some((x) => x.includes(t))) return 1; return 0; };
  return recs.map((r) => [score(r), r]).filter(([s]) => s > 0).sort((a, b) => b[0] - a[0] || (b[1].kv[0] || 0) - (a[1].kv[0] || 0)).slice(0, limit).map(([, r]) => r);
}

// GeoJSON for the map layers (properties carry only what the layers style on; the full record stays in memory)
export function toLayers(recs) {
  const pts = [], lines = [], polys = [];
  for (const r of recs) {
    const props = { id: r.id, kind: r.kind, vclass: r.vclass, named: r.name ? 1 : 0 };
    if (r.line) lines.push({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: r.line } });
    if (r.polygon) polys.push({ type: "Feature", properties: props, geometry: { type: "Polygon", coordinates: [r.polygon] } });
    if (r.point) pts.push({ type: "Feature", properties: props, geometry: { type: "Point", coordinates: r.point } });
  }
  const fc = (features) => ({ type: "FeatureCollection", features });
  return { points: fc(pts), lines: fc(lines), polygons: fc(polys) };
}
