// Phase 13b: JavaScript port of the DC cascade engine (doomsday/gridtwin/cascade.py, mode = "dc", float64, no fixed-point emulation).
// Python is the reference implementation. Parity is enforced by app/test/cascade.test.mjs against engine runs exported by
// scripts/make_js_fixtures.py (S, S0, rounds, status, trips per round, final out-of-service set). Input: data/cascade_model_<grid>.json.
// EVIDENCE: recomputation of the measured DC model in the browser; it is the same deterministic model, not new evidence.

const TOL_BAL = 1e-9;

export function components(nBus, from, to, status) {            // labels numbered by lowest bus index (matches scipy ordering)
  const parent = Int32Array.from({ length: nBus }, (_, i) => i);
  const find = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  for (let l = 0; l < from.length; l++) if (status[l] > 0) { const a = find(from[l]), b = find(to[l]); if (a !== b) parent[Math.max(a, b)] = Math.min(a, b); }
  const label = new Int32Array(nBus).fill(-1), rootLab = new Map(); let n = 0;
  for (let i = 0; i < nBus; i++) { const r = find(i); if (!rootLab.has(r)) rootLab.set(r, n++); label[i] = rootLab.get(r); }
  return { n, label };
}

function solveDense(A, b) {                                     // LU with partial pivoting, in place (A: array of Float64Array rows)
  const n = b.length;
  for (let c = 0; c < n; c++) {
    let p = c, mx = Math.abs(A[c][c]);
    for (let r = c + 1; r < n; r++) { const v = Math.abs(A[r][c]); if (v > mx) { mx = v; p = r; } }
    if (mx === 0) throw new Error("singular B' matrix");
    if (p !== c) { const t = A[p]; A[p] = A[c]; A[c] = t; const tb = b[p]; b[p] = b[c]; b[c] = tb; }
    const piv = A[c][c], rowc = A[c];
    for (let r = c + 1; r < n; r++) {
      const f = A[r][c] / piv; if (f === 0) continue; const row = A[r];
      for (let j = c; j < n; j++) row[j] -= f * rowc[j];
      b[r] -= f * b[c];
    }
  }
  const x = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) { let s = b[r]; const row = A[r]; for (let j = r + 1; j < n; j++) s -= row[j] * x[j]; x[r] = s / row[r]; }
  return x;
}

export class DCCascade {
  constructor(model) {
    this.m = model; const g = model;
    this.nBus = g.n_bus; this.nBr = g.n_branch; this.nGen = g.gen_bus.length;
    this.pg0 = Float64Array.from(g.pg0); this.Pd = Float64Array.from(g.Pd);
    this.cc = g.cascade;
    if (g.cascade.fixed_point_bits != null) throw new Error("fixed-point emulation is not ported");
  }

  _balance(buses, gens, pg, factor, flags) {
    const g = this.m; let load = 0, gen = 0;
    for (const b of buses) load += this.Pd[b] * factor[b];
    for (const i of gens) gen += pg[i];
    const delta = gen - load;
    if (Math.abs(delta) <= TOL_BAL) return;
    if (delta > 0) {
      if (gen > 0) for (const i of gens) pg[i] = pg[i] * (load / gen);
      if (gens.some((i) => pg[i] < g.gen_Pmin[i] - 1e-9)) flags.pmin_violation = true;
      return;
    }
    let deficit = -delta;
    if (this.cc.redispatch === "up_and_down") {
      const head = gens.map((i) => Math.max(g.gen_Pmax[i] - pg[i], 0)); const H = head.reduce((a, v) => a + v, 0);
      if (H > 0) { const add = Math.min(deficit, H); gens.forEach((i, j) => (pg[i] = pg[i] + add * head[j] / H)); deficit -= add; }
    }
    if (deficit > TOL_BAL) { const s = (load - deficit) / load; for (const b of buses) factor[b] = factor[b] * s; }
  }

  _islandSlack(gens) {                                            // max Pmax; ties -> lowest bus id, then lowest generator index
    const g = this.m; let best = gens[0];
    for (const i of gens.slice(1)) {
      const a = g.gen_Pmax[i], b = g.gen_Pmax[best];
      if (a > b || (a === b && (g.bus_id[g.gen_bus[i]] < g.bus_id[g.gen_bus[best]] || (g.bus_id[g.gen_bus[i]] === g.bus_id[g.gen_bus[best]] && i < best)))) best = i;
    }
    return g.gen_bus[best];
  }

  _islandFlows(buses, gens, status, pg, factor) {                 // returns [branch indices, |flow|/rating, signed flow MW (from -> to)]
    const g = this.m, slack = this._islandSlack(gens), inIsland = new Uint8Array(this.nBus); buses.forEach((b) => (inIsland[b] = 1));
    const br = []; for (let l = 0; l < this.nBr; l++) if (status[l] > 0 && inIsland[g.br_from[l]] && inIsland[g.br_to[l]]) br.push(l);
    if (!br.length) return [br, [], []];
    const loc = new Map(); buses.forEach((b, j) => loc.set(b, j)); const n = buses.length;
    const p = new Float64Array(n);
    for (let i = 0; i < this.nGen; i++) if (g.gen_status[i] > 0 && inIsland[g.gen_bus[i]]) p[loc.get(g.gen_bus[i])] += pg[i];
    buses.forEach((b, j) => (p[j] = (p[j] - this.Pd[b] * factor[b]) / g.base_mva));
    const keep = [], kpos = new Int32Array(n).fill(-1); for (let j = 0; j < n; j++) if (buses[j] !== slack) { kpos[j] = keep.length; keep.push(j); }
    const A = keep.map(() => new Float64Array(keep.length)), rhs = Float64Array.from(keep.map((j) => p[j]));
    for (const l of br) {
      const bsus = 1 / g.x[l], f = kpos[loc.get(g.br_from[l])], t = kpos[loc.get(g.br_to[l])];
      if (f >= 0) A[f][f] += bsus; if (t >= 0) A[t][t] += bsus; if (f >= 0 && t >= 0) { A[f][t] -= bsus; A[t][f] -= bsus; }
    }
    const th = new Float64Array(n); const sol = keep.length ? solveDense(A, rhs) : new Float64Array(0); keep.forEach((j, q) => (th[j] = sol[q]));
    const f = br.map((l) => (1 / g.x[l]) * (th[loc.get(g.br_from[l])] - th[loc.get(g.br_to[l])]) * g.base_mva);
    return [br, f.map((v, j) => Math.abs(v) / g.rating_dc[br[j]]), f];
  }

  run(outage, { policy = null, maxRounds = null } = {}) {
    const g = this.m, cc = this.cc; policy = policy || cc.trip_policy; maxRounds = maxRounds ?? cc.max_rounds;
    outage = outage.map((v) => +v);
    if (new Set(outage).size !== outage.length || outage.some((i) => !Number.isInteger(i) || i < 0 || i >= this.nBr || g.br_status[i] === 0)) throw new Error(`invalid outage set ${outage}`);
    const status = Int32Array.from(g.br_status); outage.forEach((l) => (status[l] = 0));
    const pg = Float64Array.from(this.pg0), factor = new Float64Array(this.nBus).fill(1);
    const flags = { pmin_violation: false, nonconv_flag: false, ladder_step: null, exhausted: false };
    const frames = [], tripsPr = [], islPr = [], servedPr = []; let served = 0, served0 = 0, outStatus = null;
    for (let r = 0; r < maxRounds; r++) {
      const { n: ncomp, label } = components(this.nBus, g.br_from, g.br_to, status);
      const u = new Float64Array(this.nBr), fl = new Float64Array(this.nBr); served = 0; const energized = [];
      for (let c = 0; c < ncomp; c++) {
        const buses = []; for (let b = 0; b < this.nBus; b++) if (label[b] === c) buses.push(b);
        const gens = []; for (let i = 0; i < this.nGen; i++) if (g.gen_status[i] > 0 && g.gen_Pmax[i] > 0 && label[g.gen_bus[i]] === c) gens.push(i);
        if (!gens.length) { buses.forEach((b) => (factor[b] = 0)); continue; }
        this._balance(buses, gens, pg, factor, flags);
        const [br, uu, ff] = this._islandFlows(buses, gens, status, pg, factor); br.forEach((l, j) => { u[l] = uu[j]; fl[l] = ff[j]; });
        let s = 0; for (const b of buses) s += this.Pd[b] * factor[b]; served += s; energized.push(...buses);
      }
      const over = []; for (let l = 0; l < this.nBr; l++) if (status[l] > 0 && u[l] > cc.trip_factor + cc.overload_tol) over.push(l);
      if (r === 0) served0 = served;
      servedPr.push(served / g.initial_load_mw); islPr.push(ncomp);
      let tripped = [];
      if (over.length && served > 0) {
        if (policy === "all_overloaded") tripped = over.slice();
        else { const mx = Math.max(...over.map((l) => u[l])); const best = over.filter((l) => u[l] === mx); tripped = [best.reduce((a, l) => (g.key_rank[l] < g.key_rank[a] ? l : a))]; }
      }
      const loading = {}, flow = {}; for (let l = 0; l < this.nBr; l++) if (status[l] > 0) { loading[l] = u[l]; flow[l] = fl[l]; }
      frames.push({ round: r, out_of_service: [...status.keys()].filter((l) => status[l] === 0), tripped, overloaded: over, load_served: served / g.initial_load_mw,
        islands: ncomp, loading, flow, energized_buses: energized.sort((a, b) => a - b).map((b) => g.bus_id[b]),
        // browser-only extras (not in the Python frames): component label per bus index, served fraction per bus, generator dispatch (MW)
        component: Array.from(label), factor: Array.from(factor), pg: Array.from(pg) });
      tripsPr.push(tripped);
      if (served <= 0) { outStatus = "TOTAL_LOSS"; break; }
      if (!over.length) { outStatus = "STABLE"; break; }
      tripped.forEach((l) => (status[l] = 0));
    }
    if (outStatus === null) { outStatus = "EXHAUSTED"; flags.exhausted = true; }
    const clip = (v) => Math.min(Math.max(v, 0), 1);
    const S = clip(1 - served / g.initial_load_mw), S0 = clip(1 - served0 / g.initial_load_mw), C = S - S0;
    const { tau, delta } = g.severity;
    return { outage: [...outage].sort((a, b) => a - b), mode: "dc", policy, metrics: { S, S0, C, A: S / Math.max(S0, 0.01), rounds: frames.length, status: outStatus,
      ladder_step: null, S_total: null, cascade_driven: S >= tau - 1e-9 && C >= delta - 1e-9 }, trips_per_round: tripsPr, islands_per_round: islPr,
      served_fraction_by_round: servedPr, flags, final_out_of_service: [...status.keys()].filter((l) => status[l] === 0), frames,
      grid: g.grid, evidence: "computed in the browser by the JavaScript port of the DC cascade engine (parity-tested against Python)" };
  }
}
