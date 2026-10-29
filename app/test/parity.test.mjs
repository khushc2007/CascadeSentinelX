// Phase 9 parity tests: JavaScript port vs Python reference (fixtures from scripts/make_js_fixtures.py). Run: node --test app/test
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as R from "../js/core/resource.js";
import * as E from "../js/core/emulation.js";
import * as K from "../js/core/ranking.js";

const fx = JSON.parse(readFileSync(new URL("./fixtures/parity.json", import.meta.url)));
const close = (a, b, rel = 1e-9, msg = "") => {
  if (b === "inf" || b === null) return assert.equal(a === Infinity ? "inf" : a, b, msg);
  assert.ok(Math.abs(a - b) <= rel * Math.max(1, Math.abs(b)), `${msg}: js=${a} py=${b}`);
};

test("resource.evaluate matches Python for every scenario x prep x params x calibration (312 cases)", () => {
  for (const c of fx.resource) {
    const { L, B, k, scenario, prep, params, kappa } = c.in, r = R.evaluate(L, B, k, scenario, prep, R.params(params), 1, kappa), o = c.out, tag = JSON.stringify(c.in);
    assert.equal(r.N, o.N, tag); assert.equal(r.k_eff, o.k_eff, tag); assert.equal(r.calibrated, o.calibrated, tag);
    for (const f of ["G", "E_f", "C_D", "Q", "Tq_s", "Tc_s", "ratio_Tq_over_Tc", "N_star", "logical_qubits", "physical_qubits"]) close(r[f], o[f], 1e-9, `${f} ${tag}`);
    assert.deepEqual(r.k_bracket, o.k_bracket, tag);
  }
});
test("sweepK and kStar match Python", () => {
  for (const c of fx.sweep) {
    const rows = R.sweepK(c.in.L, c.in.B, c.in.ks, c.in.scenario, c.in.prep, R.DEFAULT_PARAMS, c.in.kappa);
    rows.forEach((r, i) => { const o = c.out[i]; for (const f of ["G", "Tq_s", "Tc_s", "ratio", "N_star"]) close(r[f], o[f], 1e-9, f); assert.equal(r.quantum_faster, o.quantum_faster); });
  }
  for (const c of fx.kstar) assert.equal(R.kStar(c.in.L, c.in.B, c.in.scenario, c.in.prep, R.DEFAULT_PARAMS, c.in.kmax, c.in.kappa), c.out, JSON.stringify(c.in));
});
test("kBracket uses exact integer comparison like Python", () => { for (const c of fx.kbracket) assert.deepEqual(R.kBracket(c.in.L, c.in.N), c.out, JSON.stringify(c.in)); });
test("pyRound reproduces Python ties-to-even", () => { assert.deepEqual([0.5, 1.5, 2.5, -0.5, 2.4999, 7.0].map(R.pyRound), [0, 2, 2, 0, 2, 7]); });
test("Tier B deterministic dynamics match Python to 1e-12", () => {
  for (const c of fx.emulation.p_closed) close(E.pClosed(c.r, c.N, c.M), c.p, 1e-12, "p_closed");
  for (const c of fx.emulation.optimal_r) assert.equal(E.optimalR(c.N, c.M), c.r);
  const col = fx.emulation.collapsed, t = E.collapsedTrajectory(col.N, col.M, col.rmax); t.p_marked.forEach((p, i) => close(p, col.p[i], 1e-12, "collapsed"));
  const fv = fx.emulation.full_vector, f = E.fullVectorTrajectory(fv.marked, fv.rmax); f.p_marked.forEach((p, i) => close(p, fv.p[i], 1e-12, "full"));
  Array.from(f.amplitudes.at(-1)).forEach((a, i) => close(a, fv.last[i], 1e-12, "amp"));
  t.p_marked.forEach((p, r) => close(p, E.pClosed(r, col.N, col.M), 1e-12, "collapsed vs closed"));
});
test("ranking metrics match Python", () => {
  for (const c of fx.ranking) {
    close(K.sT(c.Sa, 10), c.sT10); assert.deepEqual(K.tieExpandedTopT(c.Sa, 10), c.top10);
    close(K.jaccard(K.tieExpandedTopT(c.Sa, 10), K.tieExpandedTopT(c.Sb, 10)), c.jaccard10); close(K.spearman(c.Sa, c.Sb), c.spearman, 1e-12); assert.equal(K.distinctLevels(c.Sa), c.levels);
  }
});
test("stochastic Durr-Hoyer and top-T: JS means agree with Python means (different PRNGs, 2000 runs)", () => {
  for (const c of fx.stochastic) {
    const S = Float64Array.from(c.S); let tot = 0, disc = 0, nd = 0, ok = 0;
    for (let s = 0; s < c.n_runs; s++) { const r = E.dhMax(S, E.rng(s + 1)); tot += r.counter.quantum_oracle_calls; if (r.discovery_quantum_calls !== null) { disc += r.discovery_quantum_calls; nd++; } ok += r.found_Smax; }
    close(tot / c.n_runs, c.dh_mean_total_calls, 0.06, `${c.name} DH total`); close(disc / nd, c.dh_mean_discovery_calls, 0.08, `${c.name} DH discovery`);
    assert.ok(Math.abs(ok / c.n_runs - c.dh_success) < 0.03, `${c.name} success`);
    let tq = 0; for (let s = 0; s < 500; s++) { const r = E.topTThreshold(S, 10, E.rng(1000 + s)); tq += r.quantum_oracle_calls; assert.ok(r.correct); }
    close(tq / 500, c.topT10_threshold_mean_calls, 0.08, `${c.name} topT`);
  }
});
test("input validation mirrors Python", () => {
  assert.throws(() => R.evaluate(186, 118, 0)); assert.throws(() => R.evaluate(186, 118, 3, "nope")); assert.throws(() => R.evaluate(186, 118, 3.5)); assert.throws(() => E.thetaOf(10, 11));
});
