// Benchmark scene logic on the real networks: layout determinism and inventory, the contextual city's clearance from every piece of
// equipment and every branch route, and the branch-state encoding (including the round distinction) over real cascade results.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DCCascade } from "../js/core/cascade.js";
import { buildModel } from "../js/core/model.js";
import { tripRounds } from "../js/core/events.js";
import { viewState } from "../js/core/encoding.js";
import { sceneLayout, SEG } from "../js/three/layout.js";
import { cityBlocks, clearanceOK, CLEAR } from "../js/three/context.js";
import { branchVisual, KINDS } from "../js/three/branchviz.js";

const J = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const bundle = (g) => { const grid = J(`../data/grid_${g}.json`), cm = J(`../data/cascade_model_${g}.json`); return { grid, cm, model: buildModel(grid, cm), eng: new DCCascade(cm) }; };
const GRIDS = ["ieee14", "ieee30", "ieee118"];

test("layout: deterministic, one rendered position per bus/generator/load/branch of the source data", () => {
  for (const g of GRIDS) {
    const { grid, cm, model } = bundle(g), a = sceneLayout(model), b = sceneLayout(model);
    assert.deepEqual(a, b, `${g} layout changes between calls`);
    assert.equal(a.bus.length, grid.n_bus); assert.equal(a.branch.length, grid.n_branch); assert.equal(a.gen.length, cm.gen_bus.length); assert.equal(a.load.length, model.loads.length);
    // every branch route starts and ends at its own buses (topology preserved, orientation as in the case file)
    model.branches.forEach((br, l) => { const r = a.branch[l].pts, f = a.bus[br.from], t = a.bus[br.to];
      assert.ok(Math.hypot(r[0][0] - f.x, r[0][2] - f.z) < 1e-9 && Math.hypot(r[SEG][0] - t.x, r[SEG][2] - t.z) < 1e-9, `${g} branch ${l}`); });
  }
});

test("context city: deterministic, non-empty, and every block keeps its clearance from equipment and branch routes", () => {
  for (const g of GRIDS) {
    const { model } = bundle(g), L = sceneLayout(model), c1 = cityBlocks(L), c2 = cityBlocks(L);
    assert.deepEqual(c1, c2); assert.ok(c1.length > 20, `${g}: ${c1.length} blocks`);
    for (const blk of c1) assert.ok(clearanceOK(L, blk.x, blk.z, Math.max(blk.w, blk.d) / 2), `${g} block at ${blk.x},${blk.z}`);
    // independent check of the strongest rule: no block centre within the branch clearance of any branch segment midpoint
    for (const blk of c1) for (const rt of L.branch) for (let i = 0; i < SEG; i++) { const m = [(rt.pts[i][0] + rt.pts[i + 1][0]) / 2, (rt.pts[i][2] + rt.pts[i + 1][2]) / 2];
      assert.ok(Math.hypot(blk.x - m[0], blk.z - m[1]) >= CLEAR.branch, `${g}: block overlaps a branch`); }
    assert.equal(cityBlocks(sceneLayout(model, { schematic: true })).length > 0, true);   // the scene itself skips the city in schematic view
  }
});

test("branch encoding: every state of every frame of real cascades maps to one kind; trips are 'now' only at the step that applies them", () => {
  const { model, eng } = bundle("ieee118"), top = J("../data/dist_ieee118_k3.json").top[0][1];
  const res = eng.run(top), trips = tripRounds(res); const seen = new Set();
  for (let f = 0; f < res.frames.length; f++) {
    const v = viewState(model, res, f, trips);
    v.branches.forEach((st, l) => {
      const bv = branchVisual(st, f); assert.ok(KINDS.includes(bv.kind)); seen.add(bv.kind);
      if (bv.kind === "tripped_now") assert.equal(trips.get(l), f, "tripped_now must be the frame that applies the trip");
      if (bv.kind === "tripped_earlier") assert.ok(trips.get(l) < f);
      if (bv.kind === "initial_outage") assert.ok(top.includes(l));
      if (st.state === "tripped" || st.state === "initial_outage") assert.equal(bv.width, 0, "removed branches are not drawn as conductors");
      if (bv.kind === "normal" || bv.kind === "warning" || bv.kind === "overload") assert.ok(bv.width > 0);
    });
    // no branch changes to a removed state unless the result says it is out of service in this frame
    v.branches.forEach((st, l) => { if (st.state === "tripped") assert.ok(res.frames[f].out_of_service.includes(l)); });
  }
  for (const k of ["initial_outage", "tripped_now", "tripped_earlier", "overload", "warning", "normal"]) assert.ok(seen.has(k), `kind ${k} never seen`);
  // base case: no result → never "unknown"; a frame without loading data → "unknown"
  const base = viewState(model, null, 0); base.branches.forEach((st) => assert.notEqual(branchVisual(st, null).kind, "unknown"));
  assert.equal(branchVisual({ state: "normal", u: null }, 2).kind, "unknown");
});
