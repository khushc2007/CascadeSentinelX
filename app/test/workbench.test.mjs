// Workbench logic on real data: model ids, event extraction from engine frames, view-state mapping, scenario validation, rank lookup,
// explorer search and the 3-D layout. No mock responses: every case runs the parity-tested engine on the official case data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DCCascade } from "../js/core/cascade.js";
import { buildModel, entityLabel } from "../js/core/model.js";
import { buildEvents, tripRounds } from "../js/core/events.js";
import { viewState, utilBand } from "../js/core/encoding.js";
import { validateScenario, rankOf, compareRows, findingsMarkdown } from "../js/core/scenario.js";
import { sceneLayout, SEG } from "../js/three/layout.js";
import { parseQuery } from "../js/wb/explorer.js";

const here = new URL(".", import.meta.url);
const J = (p) => JSON.parse(readFileSync(new URL(p, here)));
const bundle = (g) => { const grid = J(`../data/grid_${g}.json`), cm = J(`../data/cascade_model_${g}.json`); return { grid, cm, model: buildModel(grid, cm), eng: new DCCascade(cm) }; };
const GRIDS = ["ieee14", "ieee30", "ieee118"];
const fx = J("fixtures/cascade.json");
const ORDER = ["round", "islanding", "load_shed", "overload", "trip"];

test("model: stable ids and counts match the case data", () => {
  for (const g of GRIDS) {
    const { grid, cm, model } = bundle(g);
    assert.equal(model.buses.length, grid.n_bus); assert.equal(model.branches.length, grid.n_branch); assert.equal(model.gens.length, cm.gen_bus.length);
    assert.equal(model.loads.length, cm.Pd.filter((p) => p > 0).length);
    model.branches.forEach((b, l) => { assert.equal(b.key, `branch:${l}`); assert.equal(model.byKey.get(b.key), b); assert.equal(b.fromId, grid.buses[grid.branches[l].from].id); });
    model.buses.forEach((b) => assert.equal(model.busById.get(b.id).key, `bus:${b.id}`));
    const deg = model.buses.reduce((a, b) => a + b.branches.length, 0); assert.equal(deg, 2 * grid.n_branch);
    assert.ok(Math.abs(model.totalLoadMw - cm.Pd.reduce((a, v) => a + v, 0)) < 1e-6);
  }
  const { model } = bundle("ieee118"); assert.match(entityLabel(model, "branch:6"), /bus 8–9/);
});

test("events: faithful to the engine frames, ordered as the engine computes them (all parity sets)", () => {
  for (const g of GRIDS) {
    const { model, eng } = bundle(g);
    for (const c of fx[g].slice(0, 60)) {
      const res = eng.run(c.outage, { policy: c.policy || "all_overloaded" }), ev = buildEvents(res, model);
      assert.equal(ev[0].type, "initial_outage"); assert.deepEqual(ev[0].entities, res.outage.map((l) => `branch:${l}`));
      const last = ev[ev.length - 1]; assert.equal(last.type, "termination"); assert.equal(last.values.S, res.metrics.S); assert.equal(last.frame, res.frames.length - 1);
      let prevRound = 0, prevRank = -1;
      for (const e of ev.slice(1, -1)) {
        assert.ok(e.round >= prevRound, "rounds non-decreasing"); if (e.round !== prevRound) prevRank = -1; prevRound = e.round;
        const rk = ORDER.indexOf(e.type); assert.ok(rk >= 0, `unexpected type ${e.type}`); assert.ok(rk > prevRank, `order inside round ${e.round}`); prevRank = rk;
        const f = res.frames[e.round - 1];
        if (e.type === "overload") assert.deepEqual(e.entities, f.overloaded.map((l) => `branch:${l}`));
        if (e.type === "trip") { assert.deepEqual(e.entities, f.tripped.map((l) => `branch:${l}`)); assert.equal(e.frame, e.round < res.frames.length ? e.round : e.round - 1); }
        if (e.type === "load_shed") assert.ok(f.load_served < (e.round > 1 ? res.frames[e.round - 2].load_served : 1));
      }
      const nTrips = ev.filter((e) => e.type === "trip").reduce((a, e) => a + e.entities.length, 0); assert.equal(nTrips, res.trips_per_round.flat().length);
    }
  }
});

test("view state: outage/trip/energised states match the frame at every event", () => {
  const { model, eng } = bundle("ieee118"), d = J("../data/dist_ieee118_k3.json");
  const res = eng.run(d.top[0][1]), ev = buildEvents(res, model), trips = tripRounds(res);
  for (const e of ev) {
    const v = viewState(model, res, e.frame, trips), f = res.frames[e.frame];
    res.outage.forEach((l) => assert.equal(v.branches[l].state, "initial_outage"));
    f.out_of_service.filter((l) => !res.outage.includes(l)).forEach((l) => { assert.equal(v.branches[l].state, "tripped"); assert.ok(v.branches[l].tripRound >= 1); assert.equal(v.branches[l].u, null); });
    const en = new Set(f.energized_buses); model.buses.forEach((b, i) => assert.equal(v.buses[i].energized, en.has(b.id)));
    model.buses.forEach((b, i) => assert.equal(v.buses[i].served_fraction, f.factor[b.i]));
    assert.equal(v.loadServed, f.load_served);
  }
  const base = viewState(model, null, 0); assert.ok(base.branches.every((b) => !["initial_outage", "tripped"].includes(b.state))); assert.equal(base.loadServed, 1);
  assert.equal(utilBand(0.5), "normal"); assert.equal(utilBand(0.85), "warning"); assert.equal(utilBand(1.0), "warning"); assert.equal(utilBand(1.0 + 2e-9), "overload");
});

test("scenario validation: exact rules and honest availability", () => {
  const { model } = bundle("ieee118"), ks = [2, 3];
  assert.equal(validateScenario({ model, outage: [], engine: "browser-dc", tableKs: ks }).ok, false);
  assert.equal(validateScenario({ model, outage: [1, 1], engine: "browser-dc", tableKs: ks }).ok, false);
  assert.equal(validateScenario({ model, outage: [0, 1, 2, 3, 4, 5, 6, 7, 8], engine: "browser-dc", tableKs: ks }).ok, false);
  assert.equal(validateScenario({ model, outage: [999], engine: "browser-dc", tableKs: ks }).ok, false);
  const api = validateScenario({ model, outage: [1, 2], engine: "api-ac", apiAvailable: false, tableKs: ks }); assert.equal(api.ok, false); assert.match(api.errors[0], /API is not reachable/);
  const w = validateScenario({ model, outage: [1, 2], engine: "api-dc", apiAvailable: true, tableKs: ks }); assert.equal(w.ok, true); assert.match(w.warnings[0], /IEEE-14\/30/);
  const k4 = validateScenario({ model, outage: [1, 2, 3, 4], engine: "browser-dc", tableKs: ks }); assert.equal(k4.ok, true); assert.match(k4.info[0], /cannot be ranked/);
  assert.match(validateScenario({ model, outage: [1, 2, 3], engine: "browser-dc", tableKs: ks }).info[0], /ranked against all C\(186, 3\)/);
  const pre = validateScenario({ model, outage: [1, 2], engine: "pre-ac", tableKs: ks, acPrecomputed: false, nPrecomputedAc: 2 }); assert.equal(pre.ok, false); assert.match(pre.errors[0], /No precomputed AC run/);
  assert.equal(validateScenario({ model, outage: [1, 2], engine: "pre-ac", tableKs: ks, acPrecomputed: true }).ok, true);
});

test("rank lookup against the exhaustive table", () => {
  const d = J("../data/dist_ieee118_k3.json");
  assert.deepEqual(rankOf(d, d.top[0][0]), { rank: 1, exact: true, N: d.N });
  const z = rankOf(d, 0); assert.equal(z.zero, true); assert.equal(z.tiedZero, d.n_zero);
  const mid = rankOf(d, 0.05), lower = rankOf(d, 0.02); assert.ok(mid.rank < lower.rank); assert.ok(mid.rank > d.top.length);
  const { model, eng } = bundle("ieee118"); const res = eng.run(d.top[0][1]); assert.equal(rankOf(d, res.metrics.S).rank, 1);
  const a = { grid: "ieee118", outage: res.outage, engineLabel: "x", result: res, rank: rankOf(d, res.metrics.S) }, rows = compareRows(a, a);
  assert.ok(rows.every(([, x, y]) => x === y)); assert.match(findingsMarkdown({ model, scenario: { result: res, engineLabel: "x", source: "y" }, events: buildEvents(res, model), rank: a.rank }), /#1 of 1,055,240/);
});

test("explorer search parses ids, bus pairs and branch numbers", () => {
  const { model } = bundle("ieee118");
  assert.deepEqual(parseQuery("bus 59", model), ["bus:59"]); assert.deepEqual(parseQuery("line 37", model), ["branch:37"]); assert.deepEqual(parseQuery("G4", model), ["gen:4"]);
  assert.deepEqual(parseQuery("8-9", model), ["branch:6"]); assert.deepEqual(parseQuery("9-8", model), ["branch:6"]);
  assert.deepEqual(parseQuery("bus 999", model), []); assert.ok(parseQuery("59", model).includes("bus:59") && parseQuery("59", model).includes("branch:59"));
});

test("layout: deterministic, finite, routes end at their buses; schematic is flat", () => {
  for (const g of GRIDS) {
    const { model } = bundle(g), L = sceneLayout(model), L2 = sceneLayout(model), S = sceneLayout(model, { schematic: true });
    assert.deepEqual(L.bus, L2.bus);
    model.branches.forEach((b, l) => { const r = L.branch[l]; assert.equal(r.pts.length, SEG + 1); r.pts.flat().forEach((v) => assert.ok(Number.isFinite(v)));
      assert.deepEqual(r.pts[0], [L.bus[b.from].x, L.bus[b.from].top, L.bus[b.from].z]); assert.deepEqual(r.pts[SEG], [L.bus[b.to].x, L.bus[b.to].top, L.bus[b.to].z]); });
    assert.ok(S.bus.every((b) => b.y === 0)); assert.ok(S.branch.every((r) => r.pts.every((p) => p[1] < 1)));
    if (model.kvs.length > 1) assert.ok(new Set(L.bus.map((b) => b.y)).size === model.kvs.length);
  }
});
