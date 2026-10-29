// The combinatorial wall: C(L, k) for the three grids (exact), and the one-core time for an exhaustive check at the measured E1 cascade time.
import { $, svg, dur, rangeFill, GRIDNAME, showTip, hideTip, sup } from "../ui/util.js";
import { combBig } from "../core/resource.js";

export function initWall(headline, index) {
  const L = { ieee14: 20, ieee30: 41, ieee118: 186 }, grids = ["ieee14", "ieee30", "ieee118"], cols = { ieee14: "#7f97ad", ieee30: "#a594bf", ieee118: "#8fa8bf" };
  const tcMs = headline?.tc_ms_dc_mean?.ieee118 ?? null, kIn = $("wall-k"), fill = rangeFill(kIn);
  const built = (g, k) => !!index?.grids?.find((x) => x.id === g)?.k?.[k]?.available;
  function draw() {
    const k = +kIn.value, s = $("wall-svg"); s.innerHTML = ""; const W = 720, H = 340, P = { l: 52, r: 12, t: 34, b: 34 }, ks = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], yMax = 17;
    const y = (v) => H - P.b - (Math.log10(Math.max(v, 1)) / yMax) * (H - P.t - P.b), bw = (W - P.l - P.r) / ks.length;
    const defs = svg("defs", {}, s);
    grids.forEach((g) => { const lg = svg("linearGradient", { id: `wg-${g}`, x1: 0, y1: 0, x2: 0, y2: 1 }, defs); svg("stop", { offset: 0, "stop-color": cols[g], "stop-opacity": 1 }, lg); svg("stop", { offset: 1, "stop-color": cols[g], "stop-opacity": 0.15 }, lg); });
    for (let e = 0; e <= yMax; e += 3) { svg("line", { x1: P.l, x2: W - P.r, y1: y(10 ** e), y2: y(10 ** e), stroke: "rgba(150,150,150,.12)" }, s); svg("text", { x: P.l - 8, y: y(10 ** e) + 4, "text-anchor": "end", fill: "#8a877f", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, s, e === 0 ? "1" : `10${sup(e)}`); }
    // human-scale references at the measured cascade time
    if (tcMs) [[86400, "1 day of CPU"], [3.156e7, "1 year of CPU"]].forEach(([sec, lab]) => { const n = sec / (tcMs / 1000); svg("line", { x1: P.l, x2: W - P.r, y1: y(n), y2: y(n), stroke: "rgba(208,71,58,.45)", "stroke-dasharray": "4 5" }, s); svg("text", { x: W - P.r, y: y(n) - 5, "text-anchor": "end", fill: "#e09a90", "font-size": 11, "font-family": "IBM Plex Mono, monospace" }, s, `${lab} (IEEE-118)`); });
    ks.forEach((kk, i) => {
      const sel = kk === k; if (sel) svg("rect", { x: P.l + i * bw + 2, y: P.t - 6, width: bw - 4, height: H - P.b - P.t + 6, rx: 8, fill: "rgba(143,168,191,.06)", stroke: "rgba(143,168,191,.25)" }, s);
      grids.forEach((g, j) => {
        const n = Number(combBig(L[g], kk)), x = P.l + i * bw + 8 + j * ((bw - 16) / 3), w = (bw - 16) / 3 - 3, b = built(g, kk);
        const r = svg("rect", { x, y: y(n), width: w, height: Math.max(1, H - P.b - y(n)), rx: 3, fill: `url(#wg-${g})`, opacity: sel ? 1 : 0.55 }, s);
        if (b) svg("circle", { cx: x + w / 2, cy: y(n) - 7, r: 2.6, fill: "#7fa37a" }, s);
        r.addEventListener("pointermove", (e) => showTip(`<b>${GRIDNAME[g]}, k = ${kk}</b><br>${combBig(L[g], kk).toLocaleString("en-US")} sets${b ? "<br><span style='color:#7fa37a'>● exhaustive DC table built</span>" : ""}`, e.clientX, e.clientY));
        r.addEventListener("pointerleave", hideTip);
      });
      svg("text", { x: P.l + i * bw + bw / 2, y: H - 12, "text-anchor": "middle", fill: sel ? "#e8e5de" : "#8a877f", "font-size": 12, "font-family": "IBM Plex Mono, monospace" }, s, `k=${kk}`);
    });
    grids.forEach((g, j) => { svg("rect", { x: P.l + 4 + j * 110, y: 8, width: 10, height: 10, rx: 2, fill: cols[g] }, s); svg("text", { x: P.l + 20 + j * 110, y: 17, fill: "#b3afa6", "font-size": 12 }, s, GRIDNAME[g]); });
    svg("circle", { cx: P.l + 352, cy: 13, r: 3, fill: "#7fa37a" }, s); svg("text", { x: P.l + 360, y: 17, fill: "#b3afa6", "font-size": 12 }, s, "exhaustive table built");
    $("wall-k-v").textContent = k; const N = combBig(186, k); $("wall-n").textContent = N.toLocaleString("en-US");
    $("wall-t").textContent = tcMs ? dur(Number(N) * tcMs / 1000) : "–";
    $("wall-note").textContent = tcMs ? `At ${tcMs.toFixed(2)} ms per cascade, the measured mean on IEEE-118 (E1), on one core.` : "Cascade timing not available.";
    $("wall-done").textContent = built("ieee118", k) ? "We built this exhaustive table: every set was simulated." : k <= 3 ? "" : "Beyond what we can enumerate here: this is where search has to replace enumeration.";
  }
  kIn.addEventListener("input", draw); draw(); fill();
}
