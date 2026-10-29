// Quantum hunt: ideal Grover dynamics on a real severity table (exact Tier B emulation, closed form), and the race of measured classical
// traces against emulated Durr-Hoyer oracle calls. Every number here is read from search_<grid>_k<k>.json or headline.json.
import { $, svg, fmtInt, pct, sci, GRIDNAME, fitCanvas, clamp, ease, RM, rangeFill, once, sup } from "../ui/util.js";
import { load } from "../ui/util.js";
import { pClosed } from "../core/emulation.js";

const TABLES = [["ieee14", 2], ["ieee14", 3], ["ieee30", 2], ["ieee30", 3], ["ieee118", 2], ["ieee118", 3]];
const LANES = [["durr_hoyer_tierB_quantum_calls", "Dürr–Høyer · quantum", "#a594bf"], ["sa_unique_evaluations", "simulated annealing", "#e0a33a"],
  ["hillclimb_unique_evaluations", "hill climb", "#8fa8bf"], ["random_unique_evaluations", "random sampling", "#7f97ad"], ["brute_unique_evaluations", "brute force", "#8a877f"]];

export function initHunt(headline) {
  const st = { g: "ieee118", k: 3, s: null, r: 0, tex: null, anim: null, raceAnim: null, grid: null };
  const cv = $("field-canvas"), ctx = cv.getContext("2d"), rIn = $("hunt-r"), fill = rangeFill(rIn);
  const seg = $("hunt-pick");
  TABLES.forEach(([g, k]) => { const b = document.createElement("button"); b.textContent = `${GRIDNAME[g]} · k=${k}`; b.dataset.key = `${g}_k${k}`; b.onclick = () => pick(g, k); seg.appendChild(b); });
  rIn.addEventListener("input", () => { stopAnim(); st.r = +rIn.value; render(); });
  $("hunt-play").onclick = () => { playGrover(); playRace(); };
  new ResizeObserver(() => drawField()).observe(cv);

  async function pick(g, k) {
    stopAnim(); st.g = g; st.k = k; [...seg.children].forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.key === `${g}_k${k}`)));
    const [s, grid] = await Promise.all([load(`search_${g}_k${k}.json`), load(`grid_${g}.json`)]); st.s = s; st.grid = grid; if (!s) return;
    st.r = 0; rIn.max = String(Math.max(2 * s.r_star + 1, 4)); rIn.value = "0"; fill(); $("hunt-n").textContent = fmtInt(s.N);
    buildTexture(); render(); buildRace(); callout();
  }
  function buildTexture() {
    const N = st.s.N, side = Math.ceil(Math.sqrt(N)), img = new ImageData(side, side); let seed = 12345; const rnd = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296);
    for (let p = 0; p < side * side; p++) { const o = p * 4; if (p >= N) { img.data[o + 3] = 0; continue; } const v = 0.45 + 0.55 * rnd(); img.data[o] = 120 * v; img.data[o + 1] = 132 * v; img.data[o + 2] = 146 * v; img.data[o + 3] = 255; }
    const off = document.createElement("canvas"); off.width = side; off.height = side; off.getContext("2d").putImageData(img, 0, 0); st.tex = { off, side };
    st.marked = st.s.bars.states.filter((x) => x.marked).map((x) => ({ i: x.rank_index, S: x.S }));
  }
  const P = (r) => pClosed(r, st.s.N, st.s.M_maximisers);
  function drawField() {
    if (!st.tex) return; const { w, d } = fitCanvas(cv), H = w; ctx.setTransform(d, 0, 0, d, 0, 0); ctx.fillStyle = "#000"; ctx.fillRect(0, 0, w, H);
    const p = P(st.r), { off, side } = st.tex, cell = w / side;
    ctx.imageSmoothingEnabled = side < 200 ? false : true; ctx.globalAlpha = 0.06 + 0.9 * (1 - p); ctx.drawImage(off, 0, 0, w, w); ctx.globalAlpha = 1;
    if (side <= 40) { ctx.strokeStyle = "rgba(0,0,0,.6)"; ctx.lineWidth = 1; for (let i = 1; i < side; i++) { ctx.beginPath(); ctx.moveTo(i * cell, 0); ctx.lineTo(i * cell, w); ctx.moveTo(0, i * cell); ctx.lineTo(w, i * cell); ctx.stroke(); } }
    ctx.globalCompositeOperation = "lighter";
    for (const m of st.marked) {
      const x = ((m.i % side) + 0.5) * cell, y = (Math.floor(m.i / side) + 0.5) * cell, R = Math.max(cell * 0.8, 3) + p * w * 0.06;
      const g = ctx.createRadialGradient(x, y, 0, x, y, R); g.addColorStop(0, `rgba(255,255,255,${0.35 + 0.65 * p})`); g.addColorStop(0.18, `rgba(200,188,216,${0.25 + 0.6 * p})`); g.addColorStop(1, "rgba(165,148,191,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R, 0, 6.283); ctx.fill();
      ctx.fillStyle = `rgba(255,255,255,${0.5 + 0.5 * p})`; ctx.fillRect(x - Math.max(cell, 2) / 2, y - Math.max(cell, 2) / 2, Math.max(cell, 2), Math.max(cell, 2));
    }
    ctx.globalCompositeOperation = "source-over";
    if (p > 0.5 && st.marked.length) { const m = st.marked[0], x = ((m.i % side) + 0.5) * cell, y = (Math.floor(m.i / side) + 0.5) * cell;
      ctx.strokeStyle = `rgba(255,255,255,${(p - 0.5) * 1.2})`; ctx.setLineDash([3, 5]); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.moveTo(x, 0); ctx.lineTo(x, w); ctx.stroke(); ctx.setLineDash([]); }
  }
  function render() {
    const s = st.s; if (!s) return; const p = P(st.r);
    rIn.value = String(st.r); fill(); $("hunt-r-v").textContent = `${fmtInt(st.r)}${st.r === s.r_star ? " = r*" : ""}`;
    $("field-l").textContent = `${fmtInt(st.r)} Grover iteration${st.r === 1 ? "" : "s"} = ${fmtInt(st.r)} oracle calls`; $("field-r").textContent = `P(worst set) = ${p < 0.001 ? sci(p, 2) : pct(p, 2)}`;
    $("hunt-p").textContent = p < 0.0001 ? sci(p, 2) : pct(p, 2);
    $("hunt-p-sub").innerHTML = `${s.M_maximisers} worst set${s.M_maximisers > 1 ? "s" : ""} (S = ${pct(s.Smax)}) among ${fmtInt(s.N)}. Optimal stop r* = <b class="mono">${fmtInt(s.r_star)}</b>, about π/4·√(N/M).`;
    drawField(); drawDial(p); drawCurve();
  }
  function drawDial(p) {
    const sv = $("hunt-dial"); sv.innerHTML = ""; const cx = 30, cy = 190, R = 165, th = st.s.theta, phi = (2 * st.r + 1) * th;
    svg("path", { d: `M${cx} ${cy - R} A${R} ${R} 0 0 1 ${cx + R} ${cy}`, fill: "none", stroke: "rgba(150,150,150,.18)" }, sv);
    svg("line", { x1: cx, y1: cy, x2: cx + R + 6, y2: cy, stroke: "rgba(150,150,150,.35)" }, sv); svg("line", { x1: cx, y1: cy, x2: cx, y2: cy - R - 6, stroke: "rgba(150,150,150,.35)" }, sv);
    svg("text", { x: cx + 6, y: cy - R - 8 + 14, fill: "#a594bf", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, sv, "|worst⟩");
    svg("text", { x: cx + R - 2, y: cy - 8, "text-anchor": "end", fill: "#8a877f", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, sv, "|rest⟩");
    const ang = Math.min(phi, Math.PI), x = cx + R * Math.cos(ang), y = cy - R * Math.sin(ang);
    svg("path", { d: `M${cx + 40} ${cy} A40 40 0 0 0 ${cx + 40 * Math.cos(ang)} ${cy - 40 * Math.sin(ang)}`, fill: "none", stroke: "#a594bf", "stroke-width": 2 }, sv);
    const n = Math.min(st.r, 30); for (let j = 0; j < n; j++) { const a = (2 * Math.round((j * st.r) / Math.max(n, 1)) + 1) * th; svg("line", { x1: cx, y1: cy, x2: cx + R * Math.cos(a), y2: cy - R * Math.sin(a), stroke: "rgba(165,148,191,.12)" }, sv); }
    svg("line", { x1: cx, y1: cy, x2: x, y2: y, stroke: "#c8bcd8", "stroke-width": 3, "stroke-linecap": "round" }, sv);
    svg("circle", { cx: x, cy: y, r: 5, fill: "#fff" }, sv);
    svg("text", { x: cx + 48, y: cy - 10, fill: "#b3afa6", "font-size": 10.5, "font-family": "IBM Plex Mono, monospace" }, sv, `${((2 * st.r + 1) * th * 180 / Math.PI).toFixed(2)}°`);
  }
  function drawCurve() {
    const sv = $("hunt-curve"); sv.innerHTML = ""; const W = 520, H = 150, Pd = { l: 34, r: 10, t: 10, b: 24 }, rm = +rIn.max, x = (r) => Pd.l + (r / rm) * (W - Pd.l - Pd.r), y = (p) => Pd.t + (1 - p) * (H - Pd.t - Pd.b);
    const defs = svg("defs", {}, sv), lg = svg("linearGradient", { id: "hc", x1: 0, y1: 0, x2: 0, y2: 1 }, defs); svg("stop", { offset: 0, "stop-color": "#a594bf", "stop-opacity": 0.45 }, lg); svg("stop", { offset: 1, "stop-color": "#a594bf", "stop-opacity": 0 }, lg);
    [0, 0.5, 1].forEach((v) => { svg("line", { x1: Pd.l, x2: W - Pd.r, y1: y(v), y2: y(v), stroke: "rgba(150,150,150,.12)" }, sv); svg("text", { x: Pd.l - 6, y: y(v) + 4, "text-anchor": "end", fill: "#8a877f", "font-size": 10, "font-family": "IBM Plex Mono, monospace" }, sv, v.toFixed(1)); });
    const n = 160, pts = []; for (let i = 0; i <= n; i++) { const r = (i / n) * rm; pts.push([x(r), y(P(r))]); }
    svg("path", { d: `M${pts.map((p) => p.join(",")).join("L")}L${x(rm)},${y(0)}L${x(0)},${y(0)}Z`, fill: "url(#hc)" }, sv);
    svg("path", { d: `M${pts.map((p) => p.join(",")).join("L")}`, fill: "none", stroke: "#a594bf", "stroke-width": 2 }, sv);
    svg("line", { x1: x(st.s.r_star), x2: x(st.s.r_star), y1: Pd.t, y2: H - Pd.b, stroke: "rgba(255,255,255,.35)", "stroke-dasharray": "3 4" }, sv);
    svg("text", { x: x(st.s.r_star) + 5, y: Pd.t + 10, fill: "#b3afa6", "font-size": 10, "font-family": "IBM Plex Mono, monospace" }, sv, `r* = ${fmtInt(st.s.r_star)}`);
    svg("circle", { cx: x(st.r), cy: y(P(st.r)), r: 5.5, fill: "#fff" }, sv);
    svg("text", { x: Pd.l, y: H - 6, fill: "#8a877f", "font-size": 10, "font-family": "IBM Plex Mono, monospace" }, sv, "P(measure a worst set) vs Grover iterations r · sin²((2r+1)θ), exact");
  }
  function stopAnim() { if (st.anim) { cancelAnimationFrame(st.anim); st.anim = null; } }
  function playGrover() {
    stopAnim(); const target = st.s.r_star, T = RM ? 0 : clamp(target * 140, 1400, 5200), t0 = performance.now();
    const step = (t) => { const k = T ? clamp((t - t0) / T, 0, 1) : 1; st.r = Math.round(target * ease(k)); render(); if (k < 1) st.anim = requestAnimationFrame(step); else st.anim = null; };
    st.anim = requestAnimationFrame(step);
  }
  function callout() {
    const s = st.s, e7 = headline?.e7?.[`${st.g}_k${st.k}`], rand = (s.N + 1) / (s.M_maximisers + 1);
    $("hunt-callout").innerHTML = `Ideal Grover with M known needs <b>${fmtInt(s.r_star)}</b> oracle calls. Blind random sampling needs about <b>${fmtInt(rand)}</b> evaluations on average to hit a worst set.`
      + (e7 ? ` But structure helps classical search too: the best tuned heuristic in our benchmark (${e7.best_method.split("|")[0].toUpperCase()}, E7) found it in <b>${fmtInt(e7.best_mean_discovery)}</b> evaluations on average in the ${pct(e7.best_success_rate, 0)} of runs where it succeeded within budget.` : "")
      + ` Each quantum call would also cost far more than one classical evaluation: see the crossover model below.`;
  }

  // ---- race ----
  function buildRace() {
    const box = $("race"); box.innerHTML = ""; const s = st.s, e7 = headline?.e7?.[`${st.g}_k${st.k}`];
    const axis = document.createElement("div"); axis.className = "axis"; axis.innerHTML = `<span></span><div class="ax"></div><span style="text-align:right">result</span>`;
    const lx = (c) => (100 * Math.log10(Math.max(c, 1))) / Math.log10(s.N);
    for (let e = 0; 10 ** e <= s.N; e++) axis.querySelector(".ax").insertAdjacentHTML("beforeend", `<span style="left:${lx(10 ** e)}%">${e === 0 ? "1" : `10${sup(e)}`}</span>`);
    st.lanes = [];
    for (const [key, name, col] of LANES) {
      const tr = s.race[key]; if (!tr || !tr.length) continue; const found = tr.find(([, v]) => v >= s.Smax - 1e-9);
      const row = document.createElement("div"); row.className = "lane"; row.innerHTML = `<span class="nm" title="${name}">${name}</span><div class="track"><div class="fill" style="width:0;background:linear-gradient(90deg, transparent, ${col}55)"></div><div class="car" style="left:0;color:${col}"></div></div><span class="res">–</span>`;
      box.appendChild(row); st.lanes.push({ row, tr, found: found ? found[0] : null, last: tr[tr.length - 1][0], lastS: tr[tr.length - 1][1], lx });
    }
    const stat = (name, at, note, col) => { const row = document.createElement("div"); row.className = "lane static"; row.innerHTML = `<span class="nm" title="${name}">${name}</span><div class="track"><div class="car" style="left:${lx(at)}%;color:${col}"></div></div><span class="res" style="color:${col}">${note}</span>`; box.appendChild(row); };
    stat("Grover, M known", s.r_star, fmtInt(s.r_star), "#c8bcd8");
    if (e7) stat(`best tuned (${e7.best_method.split("|")[0]}, E7)`, e7.best_mean_discovery, `${fmtInt(e7.best_mean_discovery)} · ${pct(e7.best_success_rate, 0)} ok`, "#7fa37a");
    box.appendChild(axis);
    const sq = document.createElement("div"); sq.className = "lane"; sq.style.marginTop = "-6px"; sq.innerHTML = `<span></span><div style="position:relative;height:12px"><span class="mono" style="position:absolute;left:${lx(Math.sqrt(s.N))}%;transform:translateX(-50%);font-size:.66rem;color:#b3afa6">▲ √N = ${fmtInt(Math.sqrt(s.N))}</span></div><span></span>`; box.appendChild(sq);
    raceAt(RM ? 1 : 0);
  }
  function raceAt(k) {
    const s = st.s, cur = Math.pow(s.N, k);
    for (const L of st.lanes) {
      const stopAt = L.found ?? L.last, pos = Math.min(cur, stopAt), done = cur >= stopAt; const best = L.tr.filter(([c]) => c <= pos).slice(-1)[0];
      L.row.querySelector(".car").style.left = `${L.lx(pos)}%`; L.row.querySelector(".fill").style.width = `${L.lx(pos)}%`;
      const res = L.row.querySelector(".res");
      if (done && L.found) { res.textContent = `found · ${fmtInt(L.found)}`; res.className = "res won"; }
      else if (done) { res.textContent = `best ${pct(L.lastS)}`; res.className = "res"; }
      else { res.textContent = best ? pct(best[1]) : "–"; res.className = "res"; }
    }
  }
  function playRace() {
    if (st.raceAnim) cancelAnimationFrame(st.raceAnim); const T = RM ? 0 : 6500, t0 = performance.now();
    const step = (t) => { const k = T ? clamp((t - t0) / T, 0, 1) : 1; raceAt(k); if (k < 1) st.raceAnim = requestAnimationFrame(step); };
    st.raceAnim = requestAnimationFrame(step);
  }
  pick("ieee118", 3);
  once($("race"), () => { playRace(); }, 0.4);
  once($("field-canvas"), () => { playGrover(); }, 0.5);
  return { play: () => { playGrover(); playRace(); } };
}
