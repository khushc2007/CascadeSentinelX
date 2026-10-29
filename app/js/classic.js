// Grid Doomsday Finder web demonstration (V2 21). Reads the precomputed bundle in ./data (built by scripts/build_demo_data.py); optional live
// cascades through the FastAPI layer when it serves this page. Every number shown comes from those files or from the parity-tested JS ports.
import * as R from "./core/resource.js";
import { pClosed } from "./core/emulation.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const cache = new Map();
async function load(name) {
  if (!cache.has(name)) cache.set(name, fetch(`data/${name}`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  return cache.get(name);
}
const pct = (x) => (x == null ? "–" : `${(100 * x).toFixed(1)}%`);
const fmtInt = (n) => Number(n).toLocaleString("en-US");
const sci = (x) => { if (x === Infinity || x === "inf") return "∞"; if (x == null) return "–"; const e = Math.floor(Math.log10(x)); const m = x / 10 ** e; return Math.abs(e) < 4 ? Number(x.toPrecision(3)).toLocaleString("en-US") : `${m.toFixed(1)}×10^${e}`; };
const dur = (s) => { const u = [[3.156e7, "years"], [86400, "days"], [3600, "hours"], [60, "minutes"], [1, "seconds"], [1e-3, "ms"]]; for (const [v, n] of u) if (s >= v) return `${(s / v).toPrecision(3)} ${n}`; return `${(s * 1e6).toPrecision(3)} µs`; };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const GRIDNAME = { ieee14: "IEEE-14", ieee30: "IEEE-30", ieee118: "IEEE-118" };

function el(tag, attrs = {}, parent = null) { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (parent) parent.appendChild(e); return e; }
function svgBox(host, w, h, label) { host.innerHTML = ""; const s = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": label }); host.appendChild(s); return s; }
function txt(s, x, y, t, a = {}) { const e = el("text", { x, y, ...a }, s); e.textContent = t; return e; }
const loadColor = (u) => (u > 1 + 1e-9 ? "var(--bad)" : u > 0.8 ? "var(--warn)" : "var(--ok)");

const state = { grid: "ieee14", k: 3, fid: "dc", cascade: null, round: 0, live: false, gridData: null, ranking: null, search: null, gr: 0, timers: {} };

// ------------------------------------------------------------------------------------------------ network drawing
function drawNetwork(host, g, frame, outage = []) {
  const W = 640, H = 420, P = 26, s = svgBox(host, W, H, `${GRIDNAME[g.id]} network`), X = (i) => P + g.layout.x[i] * (W - 2 * P), Y = (i) => P + g.layout.y[i] * (H - 2 * P);
  const big = g.n_bus > 60, out = new Set(frame ? frame.out_of_service : []), trip = new Set(frame ? frame.tripped : []), init = new Set(outage);
  const idToIdx = new Map(g.buses.map((b) => [b.id, b.i])); const live = frame ? new Set(frame.energized_buses.map((id) => idToIdx.get(id))) : null;
  for (const br of g.branches) {
    const u = frame ? frame.loading[String(br.l)] : br[state.fid === "ac" ? "base_loading_ac" : "base_loading_dc"];
    const isOut = out.has(br.l) || init.has(br.l), isTrip = trip.has(br.l);
    const ln = el("line", { x1: X(br.from), y1: Y(br.from), x2: X(br.to), y2: Y(br.to), stroke: isOut ? "var(--dead)" : loadColor(u ?? 0), "stroke-width": isTrip ? (big ? 3.5 : 5) : big ? 1.6 : 2.6,
      "stroke-dasharray": isOut && !isTrip ? "4 4" : "none", "stroke-linecap": "round" }, s);
    const t = el("title", {}, ln); t.textContent = `branch ${br.l}: bus ${g.buses[br.from].id} – ${g.buses[br.to].id}` + (u != null ? `, loading ${u.toFixed(2)}` : "") + (isOut ? " (out of service)" : "");
    if (init.has(br.l)) { const mx = (X(br.from) + X(br.to)) / 2, my = (Y(br.from) + Y(br.to)) / 2, r = big ? 4 : 6; el("path", { d: `M${mx - r},${my - r}L${mx + r},${my + r}M${mx - r},${my + r}L${mx + r},${my - r}`, stroke: "var(--ink)", "stroke-width": 2 }, s); }
  }
  for (const b of g.buses) {
    const on = live ? live.has(b.i) : true, c = el("circle", { cx: X(b.i), cy: Y(b.i), r: big ? 3.2 : b.has_gen ? 6.5 : 5, fill: on ? "var(--energised)" : "var(--deenergised)", stroke: "var(--panel)", "stroke-width": 1.5 }, s);
    if (b.has_gen && !big) el("circle", { cx: X(b.i), cy: Y(b.i), r: 9, fill: "none", stroke: on ? "var(--energised)" : "var(--deenergised)", "stroke-width": 1.2 }, s);
    const t = el("title", {}, c); t.textContent = `bus ${b.id}${b.has_gen ? " (generator)" : ""}, load ${b.load_mw.toFixed(1)} MW${on ? "" : ", de-energised"}`;
    if (!big) txt(s, X(b.i) + 8, Y(b.i) - 7, String(b.id), { "font-size": 10 });
  }
}

// ------------------------------------------------------------------------------------------------ steps 1-2
async function renderGrid() {
  const g = await load(`grid_${state.grid}.json`); state.gridData = g; if (!g) { $("net").innerHTML = `<div class="empty">Grid data not built.</div>`; return; }
  $("net-title").textContent = `${GRIDNAME[g.id]} · ${g.n_bus} buses, ${g.n_branch} branches · ${g.provenance === "official_matpower" ? "official MATPOWER 8.1" : g.provenance}`;
  drawNetwork($("net"), g, null);
  const N = R.comb(g.n_branch, state.k); $("k-val").textContent = state.k;
  $("counter").innerHTML = `C(${g.n_branch}, ${state.k}) = ${fmtInt(N)}<small>possible sets of exactly ${state.k} simultaneous branch outages</small>`;
  const wall = await load("wall.json"), idx = await load("index.json"); if (!wall) return;
  const W = 460, H = 230, P = { l: 46, r: 10, t: 10, b: 30 }, s = svgBox($("wall"), W, H, "Combinatorial wall"), grids = ["ieee14", "ieee30", "ieee118"], ks = [1, 2, 3, 4, 5, 6];
  const yMax = 12, y = (v) => H - P.b - (Math.log10(Math.max(v, 1)) / yMax) * (H - P.t - P.b), bw = (W - P.l - P.r) / ks.length, cols = ["var(--s1)", "var(--s2)", "var(--s3)"];
  for (let e = 0; e <= yMax; e += 3) { el("line", { x1: P.l, x2: W - P.r, y1: y(10 ** e), y2: y(10 ** e), stroke: "var(--rule)", "stroke-width": 1 }, s); txt(s, P.l - 6, y(10 ** e) + 4, `10^${e}`, { "text-anchor": "end" }); }
  ks.forEach((k, i) => {
    grids.forEach((gr, j) => {
      const v = wall[gr][String(k)], x = P.l + i * bw + 6 + j * ((bw - 12) / 3), w = (bw - 12) / 3 - 2, avail = idx?.grids.find((q) => q.id === gr)?.k?.[k]?.available;
      const sel = gr === state.grid && k === state.k;
      const r = el("rect", { x, y: y(v), width: w, height: H - P.b - y(v), rx: 2, fill: cols[j], opacity: sel ? 1 : avail ? 0.75 : 0.28, stroke: sel ? "var(--ink)" : "none", "stroke-width": 1.5 }, s);
      el("title", {}, r).textContent = `${GRIDNAME[gr]}, k=${k}: ${fmtInt(v)} sets${avail ? " (exhaustive DC table built)" : ""}`;
    });
    txt(s, P.l + i * bw + bw / 2, H - 10, `k=${k}`, { "text-anchor": "middle" });
  });
  [["IEEE-14", 0], ["IEEE-30", 1], ["IEEE-118", 2]].forEach(([n, j]) => { el("rect", { x: P.l + 8 + j * 92, y: P.t + 2, width: 10, height: 10, rx: 2, fill: cols[j] }, s); txt(s, P.l + 22 + j * 92, P.t + 11, n); });
}

// ------------------------------------------------------------------------------------------------ steps 3-7
async function renderCascadeBay() {
  const ex = await load(`examples_${state.grid}_k${state.k}.json`), rk = await load(`ranking_${state.grid}_k${state.k}.json`); state.ranking = rk;
  const cards = $("cards"); cards.innerHTML = "";
  const meta = { benign: ["Benign", "No load lost"], isolation_only: ["Isolation only", "Load cut off by islanding; no further trips"], cascade_driven: ["Cascade-driven", "Overload trips cause most of the loss"] };
  if (!ex) cards.innerHTML = `<div class="empty" style="grid-column:1/-1">No exhaustive table for ${GRIDNAME[state.grid]} at k=${state.k}. Tables exist for IEEE-14 and IEEE-30 up to k=4 and IEEE-118 up to k=${(await load("index.json"))?.grids.find((q) => q.id === "ieee118")?.k?.[3]?.available ? 3 : 2}.</div>`;
  else for (const [key, [title, sub]] of Object.entries(meta)) {
    const c = ex[key], b = document.createElement("button"); b.className = "card"; b.setAttribute("aria-pressed", "false");
    b.innerHTML = c ? `<span class="k">${title}</span><span class="v">branches ${c.outage.join(", ")}</span><span class="muted" style="font-size:.8rem">${sub} · S = ${pct(c.dc.metrics.S)}</span>` : `<span class="k">${title}</span><span class="muted" style="font-size:.8rem">No such set exists in this table.</span>`;
    if (c) b.onclick = () => { [...cards.children].forEach((x) => x.setAttribute("aria-pressed", "false")); b.setAttribute("aria-pressed", "true"); selectCascade(c, `${title}: branches ${c.outage.join(", ")}`); };
    else b.disabled = true;
    cards.appendChild(b);
  }
  const body = $("rank-body"); body.innerHTML = "";
  if (!rk) { $("rank-meta").textContent = "table not built for this (grid, k)"; }
  else {
    $("rank-meta").textContent = `N = ${fmtInt(rk.N)} · ${fmtInt(rk.n_high_dc)} sets with S ≥ 20% · ${rk.ac_available ? "AC verified from the exhaustive AC table" : "AC table not built"}`;
    const tops = await load(`top_cascades_${state.grid}_k${state.k}.json`);
    rk.rows.slice(0, 10).forEach((r, i) => {
      const tr = document.createElement("tr"); tr.tabIndex = 0;
      tr.innerHTML = `<td class="num">${i + 1}</td><td class="mono">${r.outage.join(", ")}</td><td class="num">${pct(r.S_dc)}</td><td class="num">${pct(r.S0_dc)}</td><td class="num">${pct(r.C_dc)}</td><td class="num">${r.rounds_dc}</td><td class="num">${pct(r.S_ac)}</td><td>${r.cascade_driven ? '<span class="badge casc">cascade</span>' : r.S_dc > 0 ? '<span class="badge iso">isolation</span>' : ""}</td>`;
      const go = async () => { [...body.children].forEach((x) => x.removeAttribute("aria-selected")); tr.setAttribute("aria-selected", "true"); const c = tops?.[i]; selectCascade(c ? { outage: r.outage, dc: c.dc, ac: c.ac } : await liveCascade(r.outage), `Rank ${i + 1}: branches ${r.outage.join(", ")}`); };
      tr.onclick = go; tr.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }; body.appendChild(tr);
    });
    if (tops?.[0]) { body.firstChild.setAttribute("aria-selected", "true"); selectCascade({ outage: rk.rows[0].outage, dc: tops[0].dc, ac: tops[0].ac }, `Rank 1: branches ${rk.rows[0].outage.join(", ")}`); }
  }
  layText();
}
async function liveCascade(outage) {
  if (!state.live) return null;
  const req = (mode) => fetch("cascade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ grid: state.grid, outage, mode }) }).then((r) => (r.ok ? r.json() : null));
  return { outage, dc: await req("dc"), ac: await req("ac") };
}
function selectCascade(c, title) {
  if (!c || !c.dc) { $("cas-title").textContent = "Cascade not precomputed for this set (start the API for live runs)"; return; }
  state.cascade = c; $("cas-title").textContent = title; $("fid-ac").disabled = !c.ac; if (!c.ac && state.fid === "ac") setFid("dc", false);
  state.round = 0; showCascade();
}
function showCascade() {
  const c = state.cascade?.[state.fid]; if (!c) return; const fr = c.frames, r = Math.min(state.round, fr.length - 1); const g = state.gridData;
  $("round").max = String(fr.length - 1); $("round").value = String(r); $("round-lab").textContent = `round ${r} of ${fr.length - 1} · ${fr[r].tripped.length} tripped · ${fr[r].islands} island${fr[r].islands > 1 ? "s" : ""}`;
  drawNetwork($("net2"), g, fr[r], c.outage);
  const m = c.metrics; $("sv-S").textContent = pct(m.S); $("sv-S0").textContent = pct(m.S0); $("sv-C").textContent = pct(m.C);
  const bd = []; if (m.cascade_driven) bd.push('<span class="badge casc">cascade-driven</span>'); bd.push(`<span class="badge ${m.status === "STABLE" ? "ok" : "flag"}">${m.status}</span>`);
  if (state.fid === "ac" && m.ladder_step != null) bd.push(`<span class="badge flag">AC load-shed ladder used (step ${m.ladder_step})</span>`);
  $("sv-badges").innerHTML = bd.join(" ");
  $("sv-note").textContent = state.fid === "ac" ? (m.S_total != null && Math.abs(m.S_total - m.S) > 1e-9 ? `AC interval: S between ${pct(m.S)} (ladder) and ${pct(m.S_total)} (failed islands fully lost).` : "AC solved without the load-shedding ladder: no interval.") : "DC screening model (the predicate the search uses).";
  const W = 380, H = 120, P = { l: 40, r: 8, t: 8, b: 22 }, s = svgBox($("served"), W, H, "Load served per round"), n = fr.length, x = (i) => P.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - P.l - P.r), y = (v) => P.t + (1 - v) * (H - P.t - P.b);
  [0, 0.5, 1].forEach((v) => { el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), stroke: "var(--rule)" }, s); txt(s, P.l - 6, y(v) + 4, `${v * 100}%`, { "text-anchor": "end" }); });
  el("path", { d: fr.map((f, i) => `${i ? "L" : "M"}${x(i)},${y(f.load_served)}`).join(""), fill: "none", stroke: "var(--s1)", "stroke-width": 2 }, s);
  fr.forEach((f, i) => el("circle", { cx: x(i), cy: y(f.load_served), r: i === r ? 5 : 3.5, fill: i === r ? "var(--ink)" : "var(--s1)", stroke: "var(--panel)", "stroke-width": 1.5 }, s));
  txt(s, P.l, H - 6, "load served by round");
}
function setFid(f, redraw = true) { state.fid = f; $("fid-dc").setAttribute("aria-pressed", String(f === "dc")); $("fid-ac").setAttribute("aria-pressed", String(f === "ac")); if (redraw) showCascade(); }
function play(timerKey, input, onStep, btn) {
  if (state.timers[timerKey]) { clearInterval(state.timers[timerKey]); state.timers[timerKey] = null; btn.textContent = "Play"; return; }
  if (+input.value >= +input.max) input.value = "0"; btn.textContent = "Pause";
  state.timers[timerKey] = setInterval(() => { if (+input.value >= +input.max) { clearInterval(state.timers[timerKey]); state.timers[timerKey] = null; btn.textContent = "Play"; return; } input.value = String(+input.value + 1); onStep(+input.value); }, timerKey === "c" ? 900 : 120);
}

// ------------------------------------------------------------------------------------------------ steps 8-10
async function renderSearch() {
  const s = await load(`search_${state.grid}_k${state.k}.json`); state.search = s;
  if (!s) { ["bars", "pcurve", "race"].forEach((h) => ($(h).innerHTML = `<div class="empty">No search log for ${GRIDNAME[state.grid]} at k=${state.k} (built for k = 2 and 3 where a table exists).</div>`)); $("search-foot").textContent = "–"; return; }
  $("gr").max = String(s.bars.r.length - 1); $("gr").value = String(Math.min(s.bars.r.length - 1, s.bars.r.findIndex((r) => r >= s.r_star))); drawBars();
  // P(success) curve
  const W = 460, H = 150, P = { l: 40, r: 10, t: 10, b: 24 }, sv = svgBox($("pcurve"), W, H, "Success probability"), rm = s.p_success.length - 1, x = (r) => P.l + (r / rm) * (W - P.l - P.r), y = (p) => P.t + (1 - p) * (H - P.t - P.b);
  [0, 0.5, 1].forEach((v) => { el("line", { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), stroke: "var(--rule)" }, sv); txt(sv, P.l - 6, y(v) + 4, v.toFixed(1), { "text-anchor": "end" }); });
  const pts = []; for (let r = 0; r <= rm; r++) pts.push(`${r ? "L" : "M"}${x(r)},${y(pClosed(r, s.N, s.M_maximisers))}`);
  el("path", { d: pts.join(""), fill: "none", stroke: "var(--c-emulated)", "stroke-width": 2 }, sv);
  const step = Math.max(1, Math.floor(rm / 40)); for (let r = 0; r <= rm; r += step) el("circle", { cx: x(r), cy: y(s.p_success[r]), r: 2.6, fill: "var(--panel)", stroke: "var(--c-emulated)", "stroke-width": 1.4 }, sv);
  el("line", { x1: x(s.r_star), x2: x(s.r_star), y1: P.t, y2: H - P.b, stroke: "var(--ink-3)", "stroke-dasharray": "3 3" }, sv); txt(sv, x(s.r_star) + 4, P.t + 10, `r* = ${s.r_star}`);
  txt(sv, P.l, H - 6, `P(worst set) vs r · line sin²((2r+1)θ) · dots emulation`);
  // race
  const W2 = 460, H2 = 260, Q = { l: 44, r: 12, t: 12, b: 34 }, rs = svgBox($("race"), W2, H2, "Race to the worst set"), series = [["durr_hoyer_tierB_quantum_calls", "Dürr–Høyer (emulated)", "var(--c-emulated)"], ["random_unique_evaluations", "random", "var(--s1)"], ["hillclimb_unique_evaluations", "hill climb", "var(--s2)"], ["sa_unique_evaluations", "simulated annealing", "var(--s3)"], ["brute_unique_evaluations", "brute force", "var(--ink-3)"]];
  let xm = 10; series.forEach(([k]) => (s.race[k] || []).forEach(([c]) => (xm = Math.max(xm, c)))); xm = Math.max(xm, s.N);
  const lx = (c) => Q.l + (Math.log10(Math.max(c, 1)) / Math.log10(xm)) * (W2 - Q.l - Q.r), ly = (v) => Q.t + (1 - v / (s.Smax * 1.05)) * (H2 - Q.t - Q.b);
  for (let e = 0; e <= Math.ceil(Math.log10(xm)); e++) if (10 ** e <= xm) { el("line", { x1: lx(10 ** e), x2: lx(10 ** e), y1: Q.t, y2: H2 - Q.b, stroke: "var(--rule)" }, rs); txt(rs, lx(10 ** e), H2 - Q.b + 14, e === 0 ? "1" : `10^${e}`, { "text-anchor": "middle" }); }
  [0, s.Smax].forEach((v) => { el("line", { x1: Q.l, x2: W2 - Q.r, y1: ly(v), y2: ly(v), stroke: "var(--rule)" }, rs); txt(rs, Q.l - 6, ly(v) + 4, pct(v), { "text-anchor": "end" }); });
  el("line", { x1: lx(Math.sqrt(s.N)), x2: lx(Math.sqrt(s.N)), y1: Q.t, y2: H2 - Q.b, stroke: "var(--ink-3)", "stroke-dasharray": "3 3" }, rs); txt(rs, lx(Math.sqrt(s.N)) + 4, H2 - Q.b - 6, "√N");
  series.forEach(([k, name, col], j) => {
    const tr = s.race[k]; if (!tr || !tr.length) return; let d = `M${lx(Math.max(tr[0][0], 1))},${ly(tr[0][1])}`;
    for (let i = 1; i < tr.length; i++) d += `H${lx(tr[i][0])}V${ly(tr[i][1])}`;
    el("path", { d, fill: "none", stroke: col, "stroke-width": 2 }, rs); const last = tr[tr.length - 1]; el("circle", { cx: lx(last[0]), cy: ly(last[1]), r: 3.5, fill: col }, rs);
  });
  const leg = series.map(([, n, c]) => `<span><i style="background:${c}"></i>${n}</span>`).join("");
  $("race").insertAdjacentHTML("beforeend", `<div class="legend">${leg}</div>`);
  $("search-foot").textContent = `table size N = ${fmtInt(s.N)} · maximisers M = ${s.M_maximisers} · Dürr–Høyer discovered S_max after ${s.dh_discovery_quantum_calls ?? "–"} emulated quantum oracle calls (seed 0) · building the table cost ${fmtInt(s.table_construction_evals)} classical evaluations · fidelity: DC`;
}
function drawBars() {
  const s = state.search; if (!s) return; const ri = +$("gr").value, r = s.bars.r[ri], amps = s.bars.amplitude[ri];
  $("gr-lab").textContent = `r = ${r} (r* = ${s.r_star})`;
  const W = 460, H = 190, P = { l: 40, r: 8, t: 10, b: 26 }, sv = svgBox($("bars"), W, H, "Grover amplitudes"), n = amps.length, bw = (W - P.l - P.r) / n;
  let am = 0; s.bars.amplitude.forEach((row) => row.forEach((a) => (am = Math.max(am, Math.abs(a))))); am = am || 1;
  const y0 = P.t + (H - P.t - P.b) / 2, y = (a) => y0 - (a / am) * ((H - P.t - P.b) / 2);
  el("line", { x1: P.l, x2: W - P.r, y1: y0, y2: y0, stroke: "var(--rule)" }, sv); txt(sv, P.l - 6, y(am) + 4, `+${am.toFixed(2)}`, { "text-anchor": "end" }); txt(sv, P.l - 6, y(-am) + 4, `−${am.toFixed(2)}`, { "text-anchor": "end" });
  amps.forEach((a, i) => {
    const st = s.bars.states[i], top = Math.min(y(a), y0), h = Math.abs(y(a) - y0);
    const b = el("rect", { x: P.l + i * bw + 1, y: top, width: Math.max(bw - 2, 1), height: Math.max(h, 0.5), rx: 2, fill: st.marked ? "var(--c-emulated)" : "var(--dead)" }, sv);
    el("title", {}, b).textContent = `${st.marked ? "marked (a worst set)" : "unmarked"}, S = ${pct(st.S)}, amplitude ${a.toFixed(4)}`;
  });
  txt(sv, P.l, H - 6, "20 most severe sets, worst first · purple = marked (S = S_max)");
}

// ------------------------------------------------------------------------------------------------ step 11
let XC = null;
async function renderCrossover() {
  XC = XC || (await load("crossover.json")); const sc = $("x-sc").value, cal = $("x-cal").value === "1";
  const base = XC?.scenario_params_measured?.[sc] ? Object.fromEntries(Object.entries(XC.scenario_params_measured[sc]).filter(([k]) => k !== "provenance")) : {};
  const tt = 10 ** +$("x-tt").value, P = 10 ** +$("x-p").value, a = +$("x-a").value;
  $("x-tt-v").textContent = `${(tt * 1e6).toPrecision(2)} µs`; $("x-p-v").textContent = fmtInt(P); $("x-a-v").textContent = a.toFixed(2) + (a === 1 ? " (exhaustive)" : "");
  const p = R.params({ ...base, t_toffoli_s: tt, P, alpha: a }), kap = cal ? XC?.kappa_cal ?? null : null, ks = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const rows = ks.map((k) => R.evaluate(186, 118, k, sc, "be_counted", p, 1, kap));
  const W = 520, H = 280, Q = { l: 56, r: 14, t: 12, b: 32 }, s = svgBox($("xplot"), W, H, "Quantum vs classical time");
  const vals = rows.flatMap((r) => [r.Tq_s, r.Tc_s]).filter((v) => v > 0), lo = Math.floor(Math.log10(Math.min(...vals))), hi = Math.ceil(Math.log10(Math.max(...vals)));
  const x = (k) => Q.l + ((k - 1) / 9) * (W - Q.l - Q.r), y = (v) => Q.t + (1 - (Math.log10(v) - lo) / (hi - lo)) * (H - Q.t - Q.b);
  const stepE = Math.max(1, Math.ceil((hi - lo) / 6)); for (let e = lo; e <= hi; e += stepE) { el("line", { x1: Q.l, x2: W - Q.r, y1: y(10 ** e), y2: y(10 ** e), stroke: "var(--rule)" }, s); txt(s, Q.l - 6, y(10 ** e) + 4, `10^${e} s`, { "text-anchor": "end" }); }
  [[3.156e7, "1 yr"], [86400, "1 day"]].forEach(([v, n]) => { if (Math.log10(v) > lo && Math.log10(v) < hi) txt(s, W - Q.r, y(v) - 3, n, { "text-anchor": "end", fill: "var(--ink-3)" }); });
  ks.forEach((k) => txt(s, x(k), H - 12, String(k), { "text-anchor": "middle" })); txt(s, (Q.l + W) / 2, H - 1, "k (outage-set size)", { "text-anchor": "middle" });
  [["Tc_s", "var(--s1)"], ["Tq_s", "var(--s2)"]].forEach(([f, c]) => { el("path", { d: rows.map((r, i) => `${i ? "L" : "M"}${x(ks[i])},${y(r[f])}`).join(""), fill: "none", stroke: c, "stroke-width": 2 }, s); rows.forEach((r, i) => { const d = el("circle", { cx: x(ks[i]), cy: y(r[f]), r: 3.5, fill: c, stroke: "var(--panel)", "stroke-width": 1.5 }, s); el("title", {}, d).textContent = `k=${ks[i]}: ${f === "Tc_s" ? "classical" : "quantum"} ${dur(r[f])}`; }); });
  const k0 = state.grid === "ieee118" ? state.k : 3; el("line", { x1: x(k0), x2: x(k0), y1: Q.t, y2: H - Q.b, stroke: "var(--ink)", "stroke-dasharray": "2 3" }, s); txt(s, x(k0) + 4, Q.t + 10, `k = ${k0}`);
  const r3 = rows[k0 - 1], ns = r3.N_star, kb = Number.isFinite(ns) ? R.kBracket(186, ns) : null;
  $("x-nstar").innerHTML = `N* = ${sci(ns)}<small>${Number.isFinite(ns) ? `crossover set count at G(k=${k0}); C(186,k) passes it between k = ${kb[0]} and ${kb[1]}` : "no crossover: the classical method scales at or below √N"}</small>`;
  const ieeeLeft = [1, 2, 3, 4].every((k) => !rows[k - 1].quantum_faster);
  $("x-call").textContent = `${ieeeLeft ? "IEEE grids sit left of every crossover in this model: at k ≤ 4 on IEEE-118 the classical search is faster." : "With these assumptions the model puts quantum ahead somewhere at k ≤ 4 on IEEE-118; check which assumption drives it."} At k = ${k0}: quantum ${dur(r3.Tq_s)} vs classical ${dur(r3.Tc_s)} (${r3.calibrated ? "κ-calibrated" : "uncalibrated"}). Estimate only; nothing here is measured on quantum hardware.`;
}

// ------------------------------------------------------------------------------------------------ step 12
async function renderLedger() {
  const ev = await load("evidence.json"); if (!ev) return; const box = $("led"); box.innerHTML = "";
  for (const [id, e] of Object.entries(ev)) {
    const d = document.createElement("div"); d.className = "led"; const nr = (e.parts || []).filter((p) => p.status !== "EXECUTED").map((p) => `${p.name}: ${p.status}`).slice(0, 3);
    d.innerHTML = `<div class="panel-head"><span class="id">${id} · ${e.name ?? ""}</span><span class="st ${e.status}">${e.status.replace("_", " ")}</span></div><p>${(e.label || "").replace(/^\[[A-Z_]+\]\s*/, "")}</p>${nr.length ? `<p class="faint">${nr.join(" · ")}</p>` : ""}`;
    box.appendChild(d);
  }
  const st = (id) => ev[id]?.status;
  const col = (cls, title, items) => `<div class="panel"><span class="chip ${cls}">${title}</span><ul>${items.map((t) => `<li>${t}</li>`).join("")}</ul></div>`;
  $("claims").innerHTML = col("m", "MEASURED", ["Cascade tables, rankings and DC–AC agreement on official IEEE-14/30/118 cases" + (st("E3") ? "" : " (pending)"), "Simulator checked against PYPOWER and hand-solved cases (E0)", "Classical baselines: unique evaluations to the worst set (E7)", "A2 micro-oracle gate counts, verified on every input (E14)"])
    + col("e", "EMULATED", ["Grover, BBHT and Dürr–Høyer dynamics (Tier B, exact classical emulation)", "Top-T search cost (E9)", "Toy circuits on Qiskit Aer, ideal and with a device noise model (E4, E5): a classical simulator, not hardware"])
    + col("d", "MODELLED", ["Fault-tolerant resource and crossover estimates (E15)", "Logical and physical qubit counts (bounds)", "QAOA on a fitted quadratic surrogate (E10)"])
    + col("p", "PROPOSED / NOT RUN", ["IBM hardware run (E13): no credentials, not run", "IEEE-118 exhaustive AC at k = 3 and DC at k = 4: compute-limited, not run", "A coherent IEEE-scale oracle: designed and estimated, never synthesized"]);
}

// ------------------------------------------------------------------------------------------------ layperson / technical sentence
let LAY = true;
function layText() {
  const rk = state.ranking, s = state.search, g = GRIDNAME[state.grid];
  if (!rk) { $("lay-sentence").textContent = `No exhaustive table for ${g} at k = ${state.k}.`; return; }
  const top = rk.rows[0];
  $("lay-sentence").innerHTML = LAY
    ? `Of <strong>${fmtInt(rk.N)}</strong> ways to lose ${state.k} lines on the ${g} test grid, losing lines <strong>${top.outage.join(", ")}</strong> cuts off the most load in our model: <strong>${pct(top.S_dc)}</strong> of customers' demand.`
    : `Exhaustive DC table, N = ${fmtInt(rk.N)}: S_max = ${pct(rk.Smax_dc)} at {${top.outage.join(", ")}} (S₀ = ${pct(top.S0_dc)}, C = ${pct(top.C_dc)}${top.S_ac != null ? `, AC S = ${pct(top.S_ac)}` : ""}); ${fmtInt(rk.n_high_dc)} sets reach S ≥ 20%.${s ? ` Tier B Dürr–Høyer (seed 0) needed ${s.dh_discovery_quantum_calls} emulated quantum calls against √N ≈ ${Math.round(Math.sqrt(rk.N))}.` : ""}`;
}

// ------------------------------------------------------------------------------------------------ wiring
async function refreshAll() { await renderGrid(); await renderSearch(); await renderCascadeBay(); renderCrossover(); }
$("sel-grid").onchange = (e) => { state.grid = e.target.value; refreshAll(); };
$("sel-k").oninput = (e) => { state.k = +e.target.value; refreshAll(); };
$("fid-dc").onclick = () => setFid("dc"); $("fid-ac").onclick = () => { if (!$("fid-ac").disabled) setFid("ac"); };
$("round").oninput = (e) => { state.round = +e.target.value; showCascade(); };
$("play").onclick = () => play("c", $("round"), (v) => { state.round = v; showCascade(); }, $("play"));
$("gr").oninput = drawBars; $("gplay").onclick = () => play("g", $("gr"), drawBars, $("gplay"));
["x-sc", "x-cal", "x-tt", "x-p", "x-a"].forEach((id) => ($(id).oninput = renderCrossover));
$("lay-on").onclick = () => { LAY = true; $("lay-on").setAttribute("aria-pressed", "true"); $("lay-off").setAttribute("aria-pressed", "false"); layText(); };
$("lay-off").onclick = () => { LAY = false; $("lay-off").setAttribute("aria-pressed", "true"); $("lay-on").setAttribute("aria-pressed", "false"); layText(); };
fetch("health").then((r) => (r.ok ? r.json() : null)).then((h) => { if (h && h.status === "ok") { state.live = true; $("mode").textContent = "live API · IEEE-14/30"; } }).catch(() => {});
refreshAll(); renderLedger();
