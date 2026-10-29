// Live exhaustive scan: every pair of lines through the JS DC cascade in a worker, painted into a severity matrix, then checked against the table.
import { $, fmtInt, pct, GRIDNAME, fitCanvas, showTip, hideTip, lineLabel, toast } from "../ui/util.js";
import { gridBundle, dist } from "../ui/data.js";

const STOPS = [[0, [13, 16, 19]], [0.06, [44, 58, 69]], [0.3, [111, 133, 151]], [0.6, [201, 176, 122]], [0.85, [208, 71, 58]], [1, [240, 199, 191]]];
function cmap(t) { if (t <= 0) return [20, 22, 25]; for (let i = 1; i < STOPS.length; i++) if (t <= STOPS[i][0]) { const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], k = (t - a) / (b - a); return ca.map((v, j) => Math.round(v + (cb[j] - v) * k)); } return STOPS[STOPS.length - 1][1]; }

export function initScan(lab) {                       // lab: { loadSet(gridId, outage) } — opens a pair in the Investigate workspace
  const cv = $("scan-canvas"), ctx = cv.getContext("2d"); const st = { id: "ieee30", B: null, S: null, L: 0, worker: null, img: null, max: 0, running: false, done: false };
  const segBtns = [...$("scan-grid").querySelectorAll("button")];
  segBtns.forEach((b) => (b.onclick = () => { if (st.running) return; setGrid(b.dataset.g); }));
  $("scan-go").onclick = () => run();
  async function setGrid(id) {
    st.id = id; segBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.g === id))); st.B = await gridBundle(id); st.L = st.B.grid.n_branch;
    st.S = new Float32Array(st.L * st.L).fill(-1); st.max = 0; st.done = false; st.img = new ImageData(st.L, st.L);
    for (let p = 0; p < st.L * st.L; p++) { st.img.data[p * 4 + 3] = 255; st.img.data[p * 4] = 14; st.img.data[p * 4 + 1] = 15; st.img.data[p * 4 + 2] = 16; }
    const N = (st.L * (st.L - 1)) / 2; $("scan-count").textContent = `0 / ${fmtInt(N)}`; $("scan-bar").style.width = "0"; ["scan-rate", "scan-time", "scan-pos", "scan-max"].forEach((i) => ($(i).textContent = "–"));
    $("scan-check").innerHTML = ""; $("scan-go").disabled = false; $("scan-go").lastChild.textContent = `Run all ${fmtInt(N)} pairs`; paint();
  }
  function paint() {
    const { w, h, d } = fitCanvas(cv), L = st.L; ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, w, h); if (!L) return;
    const off = paint.off || (paint.off = document.createElement("canvas")); off.width = L; off.height = L; off.getContext("2d").putImageData(st.img, 0, 0);
    const s = Math.min(w, h) - 8, ox = (w - s) / 2, oy = (h - s) / 2; ctx.imageSmoothingEnabled = false; ctx.drawImage(off, ox, oy, s, s);
    ctx.strokeStyle = "rgba(150,150,150,.22)"; ctx.strokeRect(ox + 0.5, oy + 0.5, s - 1, s - 1);
    st.geom = { ox, oy, s };
    if (!st.running && !st.done) { ctx.fillStyle = "rgba(170,181,201,.8)"; ctx.font = '500 13px "IBM Plex Mono", ui-monospace, monospace'; ctx.textAlign = "center";
      ctx.fillText(`${(L * (L - 1) / 2).toLocaleString("en-US")} pairs · press Run to simulate them all`, w / 2, h / 2); ctx.textAlign = "start"; }
  }
  function setCell(i, j, S) {
    st.S[i * st.L + j] = S; st.S[j * st.L + i] = S; const scale = Math.max(st.max, 0.05), c = cmap(S <= 1e-9 ? 0 : 0.04 + 0.96 * Math.min(S / scale, 1));
    for (const p of [i * st.L + j, j * st.L + i]) { st.img.data[p * 4] = c[0]; st.img.data[p * 4 + 1] = c[1]; st.img.data[p * 4 + 2] = c[2]; }
  }
  function recolor() { for (let i = 0; i < st.L; i++) for (let j = i + 1; j < st.L; j++) { const v = st.S[i * st.L + j]; if (v >= 0) setCell(i, j, v); } }
  function run() {
    if (st.running || !st.B) return; setGrid(st.id).then(() => {
      st.running = true; $("scan-go").disabled = true; segBtns.forEach((b) => (b.disabled = true)); let pos = 0, best = null, lastMax = 0;
      const queue = []; let qi = 0, shown = 0, computeMs = 0, computed = 0, NN = (st.L * (st.L - 1)) / 2; const tStart = performance.now(), MIN_REVEAL = 2600;
      const onBatch = ({ batch, done, N, ms }) => { for (let q = 0; q < batch.length; q++) queue.push(batch[q]); computed = done; computeMs = ms; NN = N; };
      const tick = () => {                                     // reveal pacing only: the stats always show the true compute time
        const target = Math.min(computed, Math.ceil(NN * Math.min(1, (performance.now() - tStart) / MIN_REVEAL)));
        while (shown < target && queue.length - qi >= 3) { const i = queue[qi++], j = queue[qi++], S = queue[qi++]; shown++; if (S > 1e-9) pos++; if (S > st.max) { st.max = S; best = [i, j]; } setCell(i, j, S); }
        if (st.max > lastMax * 1.25 + 1e-6) { recolor(); lastMax = st.max; }
        paint(); $("scan-count").textContent = `${fmtInt(shown)} / ${fmtInt(NN)}`; $("scan-bar").style.width = `${(100 * shown) / NN}%`;
        $("scan-rate").textContent = computed ? fmtInt(computed / (computeMs / 1000)) : "–"; $("scan-time").textContent = `${(computeMs / 1000).toFixed(2)} s compute`; $("scan-pos").textContent = shown ? `${fmtInt(pos)} (${pct(pos / shown)})` : "–";
        $("scan-max").textContent = best ? `${pct(st.max)} · ${lineLabel(st.B.grid, best[0])} + ${lineLabel(st.B.grid, best[1])}` : "–";
        if (shown >= NN) finish(pos, NN, best); else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      try {
        st.worker = new Worker(new URL("../scan-worker.js", import.meta.url), { type: "module" });
        st.worker.onmessage = (e) => onBatch(e.data); st.worker.onerror = () => { st.worker.terminate(); st.worker = null; fallback(onBatch); };
        st.worker.postMessage({ model: st.B.model });
      } catch { fallback(onBatch); }
    });
  }
  function fallback(onBatch) {                      // main-thread chunks when module workers are unavailable
    const eng = st.B.engine, L = st.L, N = (L * (L - 1)) / 2; let i = 0, j = 1, done = 0; const t0 = performance.now();
    const step = () => { const out = [], tEnd = performance.now() + 14; while (done < N && performance.now() < tEnd) { out.push(i, j, eng.run([i, j]).metrics.S); done++; if (++j >= L) { i++; j = i + 1; } } onBatch({ batch: out, done, N, ms: performance.now() - t0 }); if (done < N) setTimeout(step, 0); };
    step();
  }
  async function finish(pos, N, best) {
    st.running = false; st.done = true; if (st.worker) { st.worker.terminate(); st.worker = null; } recolor(); paint(); segBtns.forEach((b) => (b.disabled = false)); $("scan-go").disabled = false; $("scan-go").lastChild.textContent = "Run again";
    const d = await dist(st.id, 2), box = $("scan-check");
    if (!d) { box.innerHTML = ""; return; }
    const okMax = Math.abs(d.top[0][0] - st.max) <= 1e-9, okPos = d.N - d.n_zero === pos, ok = okMax && okPos && d.N === N;
    box.innerHTML = `<div class="check${ok ? "" : " bad"}">${ok ? '<svg viewBox="0 0 18 18"><circle cx="9" cy="9" r="8" fill="none" stroke="#7fa37a"/><path d="M5 9.5l2.6 2.6L13 6.6" fill="none" stroke="#7fa37a" stroke-width="1.8"/></svg>' : '<svg viewBox="0 0 18 18"><circle cx="9" cy="9" r="8" fill="none" stroke="#d0473a"/><path d="M6 6l6 6M12 6l-6 6" stroke="#d0473a" stroke-width="1.8"/></svg>'}
      <span>${ok ? `Matches the exhaustive table built offline: worst pair ${pct(d.top[0][0], 2)} and ${fmtInt(pos)} pairs with load lost, both identical.` : `Differs from the exhaustive table (table max ${pct(d.top[0][0], 2)}, ${fmtInt(d.N - d.n_zero)} pairs with loss).`}</span></div>`;
  }
  cv.addEventListener("pointermove", (e) => {
    if (!st.geom || !st.L) return; const r = cv.getBoundingClientRect(), { ox, oy, s } = st.geom, x = e.clientX - r.left - ox, y = e.clientY - r.top - oy;
    const i = Math.floor((y / s) * st.L), j = Math.floor((x / s) * st.L); if (i < 0 || j < 0 || i >= st.L || j >= st.L || i === j) { hideTip(); return; }
    const v = st.S[i * st.L + j]; showTip(`<b>lines ${Math.min(i, j)} + ${Math.max(i, j)}</b><br><span class="t">${lineLabel(st.B.grid, i)} · ${lineLabel(st.B.grid, j)}</span><br>${v < 0 ? "not simulated yet" : `${pct(v)} demand lost · click to open in Investigate`}`, e.clientX, e.clientY);
  });
  cv.addEventListener("pointerleave", hideTip);
  cv.addEventListener("click", (e) => {
    if (!st.geom || !st.L) return; const r = cv.getBoundingClientRect(), { ox, oy, s } = st.geom, i = Math.floor(((e.clientY - r.top - oy) / s) * st.L), j = Math.floor(((e.clientX - r.left - ox) / s) * st.L);
    if (i < 0 || j < 0 || i >= st.L || j >= st.L || i === j || st.S[i * st.L + j] < 0) return;
    lab.loadSet(st.id, [Math.min(i, j), Math.max(i, j)]); toast(`Opened branches ${Math.min(i, j)} + ${Math.max(i, j)} in Investigate`);
  });
  new ResizeObserver(() => paint()).observe(cv);
  setGrid("ieee118");
  return { run: () => run(), get done() { return st.done; }, setGrid };
}
