// Phase 13b: parity of the JavaScript DC cascade port (app/js/core/cascade.js) with the Python engine (fixtures: scripts/make_js_fixtures.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DCCascade, components } from "../js/core/cascade.js";

const here = new URL(".", import.meta.url);
const fx = JSON.parse(readFileSync(new URL("fixtures/cascade.json", here)));
const model = (g) => JSON.parse(readFileSync(new URL(`../data/cascade_model_${g}.json`, here)));
const TOL = 1e-9;

for (const grid of Object.keys(fx)) {
  test(`DC cascade parity on ${grid} (${fx[grid].length} runs: worst-20 per table + seeded random, both trip policies)`, () => {
    const eng = new DCCascade(model(grid));
    for (const c of fx[grid]) {
      const r = eng.run(c.outage, { policy: c.policy || "all_overloaded" }), tag = `${grid} {${c.outage}} ${c.policy}`;
      assert.ok(Math.abs(r.metrics.S - c.S) <= TOL, `${tag}: S ${r.metrics.S} vs ${c.S}`);
      assert.ok(Math.abs(r.metrics.S0 - c.S0) <= TOL, `${tag}: S0`);
      assert.equal(r.metrics.rounds, c.rounds, `${tag}: rounds`);
      assert.equal(r.metrics.status, c.status, `${tag}: status`);
      assert.deepEqual(r.trips_per_round, c.trips_per_round, `${tag}: trips`);
      assert.deepEqual(r.islands_per_round, c.islands_per_round, `${tag}: islands`);
      assert.deepEqual(r.final_out_of_service, c.final_out_of_service, `${tag}: final out of service`);
      r.served_fraction_by_round.forEach((v, i) => assert.ok(Math.abs(v - c.served[i]) <= TOL, `${tag}: served round ${i}`));
    }
  });
}

test("components: labels by lowest bus, parallel branches, isolated bus", () => {
  const { n, label } = components(5, [0, 1, 0, 3], [1, 2, 1, 4], [1, 1, 1, 0]);
  assert.equal(n, 3); assert.deepEqual([...label], [0, 0, 0, 1, 2]);
});

test("invalid outage sets are rejected", () => {
  const eng = new DCCascade(model("ieee14"));
  assert.throws(() => eng.run([1, 1])); assert.throws(() => eng.run([99])); assert.throws(() => eng.run([-1]));
});
