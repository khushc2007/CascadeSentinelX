// Crossover oracle: the fault-tolerant resource model (JS port of doomsday/resource, parity-tested) with E15's measured inputs.
// Shows quantum vs classical time for IEEE-118, the logical Toffoli time at which they break even, and a readiness meter. ESTIMATE ONLY.
import { $, svg, fmtInt, sci, dur, clamp, rangeFill, sup } from "../ui/util.js";
import * as R from "../core/resource.js";

export function initOracle(XC, headline) {
  if (!XC?.scenario_params_measured) return;
  const st = { sc: "realistic" }, ins = { k: $("o-k"), tt: $("o-tt"), p: $("o-p"), a: $("o-a") }, fills = Object.fromEntries(Object.entries(ins).map(([k, el]) => [k, rangeFill(el)]));
  const base = (sc) => Object.fromEntries(Object.entries(XC.scenario_params_measured[sc]).filter(([k]) => k !== "provenance"));
  const scBtns = [...$("o-sc").querySelectorAll("button")];
  scBtns.forEach((b) => (b.onclick = () => { st.sc = b.dataset.v; scBtns.forEach((x) => x.setAttribute("aria-pressed", String(x === b))); reset(false); }));
  Object.values(ins).forEach((el) => el.addEventListener("input", draw)); $("o-cal").addEventListener("change", draw); $("o-reset").onclick = () => reset(true);
  function reset(all) {
    const b = base(st.sc); ins.tt.value = String(Math.log10(b.t_toffoli_s)); ins.p.value = String(Math.log10(b.P)); ins.a.value = String(b.alpha);
    if (all) { ins.k.value = "3"; $("o-cal").checked = true; st.sc = "realistic"; scBtns.forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.v === "realistic"))); ins.tt.value = String(Math.log10(base("realistic").t_toffoli_s)); }
    Object.values(fills).forEach((f) => f()); draw();
  }
  function draw() {
    const b = base(st.sc), k = +ins.k.value, tt = 10 ** +ins.tt.value, P = Math.round(10 ** +ins.p.value), a = +ins.a.value, cal = $("o-cal").checked;
    const p = R.params({ ...b, t_toffoli_s: tt, P, alpha: a }), kap = cal ? XC.kappa_cal : null, ks = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const rows = ks.map((kk) => R.evaluate(186, 118, kk, st.sc, "be_counted", p, 1, kap)), r = rows[k - 1];
    $("o-k-v").textContent = k; $("o-k-lab").textContent = k; $("o-tt-v").textContent = dur(tt); $("o-p-v").textContent = fmtInt(P); $("o-a-v").textContent = a.toFixed(2) + (a === 1 ? " · exhaustive" : "");
    const ratio = r.Tq_s / r.Tc_s;
    $("o-ratio").innerHTML = ratio >= 1 ? `${ratio >= 1e5 ? sci(ratio, 2) : fmtInt(ratio)}×<small style="font-size:.42em;letter-spacing:0;margin-left:.3em">slower</small>` : `${sci(1 / ratio, 2)}×<small style="font-size:.42em;letter-spacing:0;margin-left:.3em">faster</small>`;
    $("o-ratio").className = `big-stat ${ratio >= 1 ? "red" : "cyan"}`;
    $("o-ratio-sub").textContent = `Quantum ${dur(r.Tq_s)} vs classical ${dur(r.Tc_s)} for all ${fmtInt(r.N)} sets (${st.sc}, ${cal ? "κ-calibrated, partial" : "uncalibrated"}).`;
    const perTT = r.Tq_oracle_s / tt, beTT = (r.Tc_s - r.Tverif_s) / perTT;
    if (beTT > 0) { $("o-be").textContent = dur(beTT); $("o-be-sub").textContent = `Each logical Toffoli would need to take ${dur(beTT)} for quantum to tie at k = ${k} (now ${dur(tt)}, ${sci(tt / beTT, 2)}× too slow${tt / beTT < 1 ? ": already ahead" : ""}).`; }
    else { $("o-be").textContent = "unreachable"; $("o-be-sub").textContent = "The classical verification of quantum results alone takes longer than the classical search here."; }
    const lg = Math.log10(r.Tc_s / r.Tq_s); $("o-ready").style.left = `${clamp(((lg + 6) / 12) * 100, 0, 100)}%`;
    $("o-ready-sub").textContent = lg < 0 ? `${sci(10 ** -lg, 2)}× from parity at k = ${k}.` : `Model puts quantum ahead at k = ${k} under these inputs.`;
    const first = rows.find((x) => x.quantum_faster);
    $("o-verdict").innerHTML = first ? `<b>Crossover at k = ${rows.indexOf(first) + 1}</b> under these inputs: ${fmtInt(first.N)} sets, quantum ${dur(first.Tq_s)} vs classical ${dur(first.Tc_s)}. Check which slider drives it before believing it.`
      : `<b>No crossover for k ≤ 10</b> with these inputs. ${a <= 0.5 ? "With α ≤ 0.5 the classical method already scales like √N, so a quadratic query saving can never pay off." : `At k = 10 quantum is still ${sci(rows[9].Tq_s / rows[9].Tc_s, 2)}× slower.`} Estimate only; nothing here ran on quantum hardware.`;
    plot(rows, k);
  }
  function plot(rows, k) {
    const s = $("o-plot"); s.innerHTML = ""; const W = 640, H = 420, Q = { l: 62, r: 16, t: 16, b: 36 };
    const vals = rows.flatMap((r) => [r.Tq_s, r.Tc_s]).filter((v) => v > 0), lo = Math.floor(Math.log10(Math.min(...vals))) - 1, hi = Math.ceil(Math.log10(Math.max(...vals))) + 1;
    const x = (kk) => Q.l + ((kk - 1) / 9) * (W - Q.l - Q.r), y = (v) => Q.t + (1 - (Math.log10(v) - lo) / (hi - lo)) * (H - Q.t - Q.b);
    const defs = svg("defs", {}, s), f = svg("filter", { id: "glow", x: "-20%", y: "-20%", width: "140%", height: "140%" }, defs); svg("feGaussianBlur", { stdDeviation: 3.2, result: "b" }, f); const m = svg("feMerge", {}, f); svg("feMergeNode", { in: "b" }, m); svg("feMergeNode", { in: "SourceGraphic" }, m);
    const stepE = Math.max(1, Math.ceil((hi - lo) / 7));
    for (let e = lo; e <= hi; e += stepE) { svg("line", { x1: Q.l, x2: W - Q.r, y1: y(10 ** e), y2: y(10 ** e), stroke: "rgba(150,150,150,.1)" }, s); svg("text", { x: Q.l - 8, y: y(10 ** e) + 4, "text-anchor": "end", fill: "#8a877f", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, s, `10${sup(e)} s`); }
    [[86400, "1 day"], [3.156e7, "1 year"], [4.35e17, "age of the universe"]].forEach(([v, n]) => { const L = Math.log10(v); if (L > lo && L < hi) { svg("line", { x1: Q.l, x2: W - Q.r, y1: y(v), y2: y(v), stroke: "rgba(224,163,58,.35)", "stroke-dasharray": "4 6" }, s); svg("text", { x: W - Q.r - 4, y: y(v) - 5, "text-anchor": "end", fill: "#e0a33a", "font-size": 11, "font-family": "IBM Plex Mono, monospace", opacity: 0.85 }, s, n); } });
    // shade the gap
    const top = rows.map((r, i) => [x(i + 1), y(Math.max(r.Tq_s, r.Tc_s))]), bot = rows.map((r, i) => [x(i + 1), y(Math.min(r.Tq_s, r.Tc_s))]).reverse();
    svg("path", { d: `M${top.map((p) => p.join(",")).join("L")}L${bot.map((p) => p.join(",")).join("L")}Z`, fill: "rgba(208,71,58,.07)" }, s);
    svg("line", { x1: x(k), x2: x(k), y1: Q.t, y2: H - Q.b, stroke: "rgba(255,255,255,.35)", "stroke-dasharray": "3 4" }, s);
    [["Tc_s", "#8fa8bf"], ["Tq_s", "#a594bf"]].forEach(([fld, col]) => {
      svg("path", { d: rows.map((r, i) => `${i ? "L" : "M"}${x(i + 1)},${y(r[fld])}`).join(""), fill: "none", stroke: col, "stroke-width": 2.4 }, s);
      rows.forEach((r, i) => { const c = svg("circle", { cx: x(i + 1), cy: y(r[fld]), r: i + 1 === k ? 6 : 3.5, fill: i + 1 === k ? "#fff" : col, stroke: col, "stroke-width": 2 }, s); svg("title", {}, c, `k=${i + 1}: ${fld === "Tc_s" ? "classical" : "quantum"} ${dur(r[fld])}`); });
    });
    rows.forEach((_, i) => svg("text", { x: x(i + 1), y: H - 14, "text-anchor": "middle", fill: i + 1 === k ? "#e8e5de" : "#8a877f", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, s, String(i + 1)));
    svg("text", { x: (Q.l + W) / 2, y: H - 1, "text-anchor": "middle", fill: "#8a877f", "font-size": 11 }, s, "k, number of simultaneous line outages");
  }
  reset(true);
  return { reset };
}
