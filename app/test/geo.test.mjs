// Bengaluru Grid Explorer data rules, on a SYNTHETIC test fixture (tests/fixtures/overpass_synthetic_fixture.json; names start with TEST,
// not real assets): provenance kept on every record, only power features read, voltages parsed only from tags, no connectivity inferred,
// no record labelled official or verified, filters and search over real fields only.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as O from "../js/geo/osm.js";

const FX = JSON.parse(readFileSync(new URL("../../tests/fixtures/overpass_synthetic_fixture.json", import.meta.url)));
const prov = { via: "https://overpass-api.de/api/interpreter", retrievedAt: "2026-10-27T00:00:00Z", osmBase: FX.osm3s.timestamp_osm_base };

test("overpass parsing: power features only, provenance on every record, geometry kinds preserved", () => {
  const recs = O.fromOverpass(FX, prov);
  assert.equal(recs.length, 8, "towers and non-power elements are ignored");
  for (const r of recs) {
    const el = FX.elements.find((e) => `osm:${e.type}/${e.id}` === r.id); assert.ok(el, `record ${r.id} has a source element`);
    assert.equal(r.prov.url, `https://www.openstreetmap.org/${el.type}/${el.id}`); assert.equal(r.prov.license, O.LICENSE.name); assert.equal(r.prov.osmBase, prov.osmBase);
    assert.deepEqual(r.tags, el.tags, "all source tags kept unchanged");
    assert.ok(!r.status.some((s) => /official|independently verified/i.test(s)), "no record may claim official or verified status");
  }
  const by = Object.fromEntries(recs.map((r) => [r.id, r]));
  assert.ok(by["osm:way/900000002"].polygon && by["osm:way/900000002"].point, "closed substation way keeps its outline and a marker");
  assert.ok(by["osm:way/900000005"].line && !by["osm:way/900000005"].point, "lines are lines, not points");
  assert.ok(by["osm:way/900000005"].status.some((s) => /Unverified connectivity/.test(s)));
  const rp = by["osm:relation/900000003"].point; assert.ok(Math.abs(rp[0] - 77.505) < 1e-9 && Math.abs(rp[1] - 12.905) < 1e-9, "relation marker at the centre of its bounds");
});

test("no connectivity is invented: records carry no links between lines and substations, even when coordinates coincide", () => {
  const recs = O.fromOverpass(FX, prov), line = recs.find((r) => r.id === "osm:way/900000005"), sub = recs.find((r) => r.id === "osm:node/900000001");
  assert.deepEqual(line.line[0], sub.point, "fixture: line starts exactly at the substation marker");
  for (const r of recs) for (const k of Object.keys(r)) assert.ok(!/connect|from_sub|to_sub|endpoint/i.test(k), `field ${k} would assert connectivity`);
});

test("voltages: parsed only from the voltage tag; missing stays unknown", () => {
  assert.deepEqual(O.parseVoltages("220000;66000"), [220, 66]); assert.deepEqual(O.parseVoltages("33 kV"), [33]); assert.deepEqual(O.parseVoltages(""), []); assert.deepEqual(O.parseVoltages("unknown"), []);
  assert.equal(O.voltageClass([400]), "v400"); assert.equal(O.voltageClass([220, 66]), "v220"); assert.equal(O.voltageClass([]), "vna");
  const recs = O.fromOverpass(FX, prov); assert.equal(recs.find((r) => r.id === "osm:way/900000006").vclass, "vna");
});

test("coverage, filters, search work on source fields only", () => {
  const recs = O.fromOverpass(FX, prov), c = O.coverage(recs);
  assert.equal(c.byKind.substation, 3); assert.equal(c.byKind.line, 2); assert.equal(c.byKind.plant, 1); assert.equal(c.withVoltage, 6); assert.equal(c.named, 4);
  assert.ok(c.lineKm > 0);
  const all = { kinds: new Set(Object.keys(O.KINDS)), vclasses: new Set(O.VCLASSES.map(([k]) => k)), operator: null, namedOnly: false };
  assert.equal(O.applyFilters(recs, all).length, 8);
  assert.equal(O.applyFilters(recs, { ...all, namedOnly: true }).length, 4);
  assert.equal(O.applyFilters(recs, { ...all, operator: "TEST-OP-2" }).length, 2);
  assert.equal(O.applyFilters(recs, { ...all, vclasses: new Set(["vna"]) }).length, 2);
  assert.equal(O.search(recs, "alpha")[0].id, "osm:node/900000001"); assert.equal(O.search(recs, "T-1")[0].id, "osm:way/900000005");
  assert.equal(O.search(recs, "way/900000008")[0].kind, "cable"); assert.deepEqual(O.search(recs, "zzz"), []);
});

test("GeoJSON import: OSM-style ids become OSM provenance; other files are labelled as user-supplied", () => {
  const gj = { type: "FeatureCollection", features: [
    { type: "Feature", properties: { "@id": "node/900000101", power: "substation", name: "TEST GJ" }, geometry: { type: "Point", coordinates: [77.6, 12.95] } },
    { type: "Feature", properties: { power: "line", voltage: "110000" }, geometry: { type: "LineString", coordinates: [[77.6, 12.95], [77.61, 12.96]] } },
    { type: "Feature", properties: { highway: "primary" }, geometry: { type: "LineString", coordinates: [[77.6, 12.95], [77.61, 12.96]] } }] };
  const recs = O.fromGeoJSON(gj, { file: "test.geojson", retrievedAt: "2026-10-27T00:00:00Z" });
  assert.equal(recs.length, 2); assert.match(recs[0].prov.source, /OpenStreetMap/); assert.equal(recs[1].prov.source, "Loaded file"); assert.equal(recs[1].prov.file, "test.geojson");
  assert.ok(recs[1].status.includes("User-supplied file"));
});

test("query: covers the stated extent and asks only for the feature kinds the explorer shows", () => {
  const q = O.overpassQuery(); assert.match(q, /12\.8,77\.4,13\.2,77\.85/); assert.match(q, /substation\|plant/); assert.match(q, /line\|minor_line\|cable/); assert.doesNotMatch(q, /meta/);
});
