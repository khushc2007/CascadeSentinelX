// Workbench orchestration: loads a network, keeps the scene in sync with the store, runs scenarios (browser engine or API), plays the
// recorded cascade events, and wires keyboard and pointer input. Panels live in their own modules and talk only through the store.
import { load, toast, RM } from "../ui/util.js";
import { gridBundle, dist } from "../ui/data.js";
import { buildModel, entityLabel } from "../core/model.js";
import { buildEvents, tripRounds } from "../core/events.js";
import { viewState } from "../core/encoding.js";
import { validateScenario, rankOf } from "../core/scenario.js";
import { loadThree, webglAvailable } from "../three/loader.js";
import { GridScene, PAL } from "../three/scene.js";
import { CameraRig } from "../three/camera.js";
import { createStore, DEFAULT_LAYERS } from "./store.js";
import { initOverlays } from "./overlays.js";
import { initExplorer } from "./explorer.js";
import { initInspector } from "./inspector.js";
import { initTimeline } from "./timeline.js";

const $ = (id) => document.getElementById(id);
const API_TIMEOUT_MS = 30000;
export const ENGINE_LABEL = { "browser-dc": "Browser · DC cascade (JS port of gridtwin/cascade.py, parity-tested)", "api-dc": "API · DC cascade (Python engine)", "api-ac": "API · AC cascade (Python engine, Newton–Raphson)",
  "pre-ac": "Precomputed · AC cascade (Python engine run stored in the data files)" };
const setKey = (o) => [...o].sort((a, b) => a - b).join(",");

export async function createWorkbench(index) {
  const store = createStore({
    gridId: null, model: null, tableKs: [], dists: {},
    selection: null, hover: null, contingency: [],
    config: { engine: "browser-dc", policy: "all_overloaded" },
    run: { status: "idle" }, playback: { i: 0, playing: false, speed: 1, autoFrame: true },
    layers: { ...DEFAULT_LAYERS, reduced: RM }, camera: { mode: "orbit", schematic: false, speed: "normal", context: "spatial" },
    saved: [], compare: { a: null, b: null, showing: null }, api: { available: false }, ui: { guide: false, legend: !(typeof matchMedia === "function" && matchMedia("(max-width: 760px)").matches) },
  });
  const wb = { store, ENGINE_LABEL, toast };

  // ---------------------------------------------------------------- 3-D renderer
  if (!webglAvailable()) { fatal("WebGL is not available in this browser, so the 3-D view cannot start. The Research workspace still works."); }
  let T = null; try { T = await loadThree(); } catch (e) { fatal("three.js could not be loaded (no network access to the CDN and no local copy). The Research workspace still works."); }
  const canvas = $("gl");
  const gs = T && webglAvailable() ? new GridScene(T, canvas) : null; wb.gs = gs;
  const rig = gs ? new CameraRig(T, gs, canvas, { onChange: (ro) => wb.onCamera && wb.onCamera(ro) }) : null; wb.rig = rig;
  function fatal(msg) { const f = $("fatal"); f.hidden = false; f.textContent = msg; }

  // ---------------------------------------------------------------- derived view
  let view = null;
  wb.currentFrameIndex = () => { const s = store.get(); if (s.run.status !== "done") return null; const ev = s.run.events[s.playback.i]; return ev ? ev.frame : 0; };
  function computeView() {
    const s = store.get(); if (!s.model) return null;
    const res = s.run.status === "done" ? s.run.result : null;
    view = res ? viewState(s.model, res, wb.currentFrameIndex(), s.run.trips) : viewState(s.model, null, 0);
    return view;
  }
  wb.view = () => view;
  function syncScene() {
    if (!gs || !store.get().model) return; const s = store.get(); computeView();
    const layers = { ...s.layers }; gs.reduced = layers.reduced; rig.reduced = layers.reduced;
    gs.setView(view, layers);
    gs.highlight("sel", s.selection, PAL.sel); gs.highlight("hov", s.hover && s.hover !== s.selection ? s.hover : null, PAL.hover);
    armHighlight();
  }
  function armHighlight() {                       // pending contingency (not yet run): dashed red tubes
    const s = store.get(); const g = gs.armGroup || (gs.armGroup = new T.Group()); if (!g.parent) gs.root.add(g);
    g.children.slice().forEach((c) => { g.remove(c); c.geometry.dispose(); c.material.dispose(); });
    const ranSame = s.run.status === "done" && sameSet(s.run.result.outage, s.contingency);
    if (ranSame) return;
    for (const l of s.contingency) {
      const rt = gs.L.branch[l]; const curve = new T.CatmullRomCurve3(rt.pts.map((p) => new T.Vector3(...p)));
      const m = new T.Mesh(new T.TubeGeometry(curve, 40, 0.11, 6, false), new T.MeshBasicMaterial({ color: PAL.fail, transparent: true, opacity: 0.85, depthTest: false })); m.renderOrder = 9; g.add(m);
    }
    gs.dirty = true;
  }
  const sameSet = (a, b) => a.length === b.length && [...a].sort((x, y) => x - y).every((v, i) => v === [...b].sort((x, y) => x - y)[i]);
  wb.sameSet = sameSet;

  // ---------------------------------------------------------------- network loading
  wb.loadGrid = async function loadGrid(id) {
    stopPlayback();
    const B = await gridBundle(id); const model = buildModel(B.grid, B.model); wb.engine = B.engine;
    const ks = Object.entries(index?.grids?.find((g) => g.id === id)?.k || {}).filter(([, v]) => v.available).map(([k]) => +k);
    const dists = {}; await Promise.all(ks.map(async (k) => (dists[k] = await dist(id, k))));
    const precomp = new Map();                                           // stored Python runs (DC and AC) for the worst sets and examples
    await Promise.all([2, 3].map(async (k) => { const [t, e] = await Promise.all([load(`top_cascades_${id}_k${k}.json`), load(`examples_${id}_k${k}.json`)]);
      (t || []).forEach((r) => r.dc && precomp.set(setKey(r.dc.outage), { dc: r.dc, ac: r.ac || null }));
      Object.values(e || {}).forEach((r) => r && r.dc && precomp.set(setKey(r.dc.outage), { dc: r.dc, ac: r.ac || null })); }));
    if (gs) { gs.build(model, { schematic: store.get().camera.schematic }); rig.setScene(gs.L); }
    $("grid-sel").value = id;
    store.set({ gridId: id, model, params: B.params, tableKs: ks, dists, precomp, selection: null, hover: null, contingency: [], run: { status: "idle" }, playback: { ...store.get().playback, i: 0, playing: false }, layers: { ...store.get().layers, isolate: null, neighbourhood: null } });
    wb.bookmarksLoad && wb.bookmarksLoad();
  };

  // ---------------------------------------------------------------- selection & contingency
  wb.select = (key, { focus = false } = {}) => { store.set({ selection: key }); if (focus && key) wb.focus(key); };
  wb.neighbourhood = (key, hops = 2) => {                               // bus indices within `hops` branches of the selection (topology only)
    const m = store.get().model; if (!m || !key) return null; const [kind, v] = key.split(":"), id = +v;
    let seed = kind === "branch" ? [m.branches[id].from, m.branches[id].to] : kind === "bus" ? [m.busById.get(id).i] : kind === "gen" ? [m.gens[id].bus] : [m.busById.get(id).i];
    const seen = new Set(seed); for (let h = 0; h < hops; h++) { const nxt = []; for (const b of seed) for (const l of m.buses[b].branches) { const br = m.branches[l]; for (const o of [br.from, br.to]) if (!seen.has(o)) { seen.add(o); nxt.push(o); } } seed = nxt; }
    return [...seen];
  };
  wb.toggleNeighbourhood = () => { const s = store.get(), on = s.layers.neighbourhood; const nb = on ? null : wb.neighbourhood(s.selection);
    store.set({ layers: { ...s.layers, neighbourhood: nb, isolate: null } }); if (nb && gs) rig.frame(nb.map((i) => gs.entityPos(s.model.buses[i].key)), { minRadius: 8 }); };
  wb.focus = (key) => { if (!gs || !key) return; rig.frame(gs.entityPoints(key), { minRadius: 6 }); };
  wb.toggleContingency = (l) => {
    const s = store.get(), c = s.contingency.includes(l) ? s.contingency.filter((x) => x !== l) : [...s.contingency, l];
    if (c.length > 8) { toast("At most 8 branches in one contingency"); return; }
    if (!s.model.branches[l].in_service) { toast(`Branch ${l} is out of service in the base case`); return; }
    store.set({ contingency: c });
  };
  wb.setContingency = (c) => store.set({ contingency: [...c] });
  wb.loadSet = async (id, outage, run = true) => { if (store.get().gridId !== id) await wb.loadGrid(id); wb.setContingency(outage); if (gs) rig.frame(outage.flatMap((l) => gs.entityPoints(`branch:${l}`)), { minRadius: 10 }); if (run) await wb.run(); };

  // ---------------------------------------------------------------- run
  let reqSeq = 0, inflight = null;
  wb.acPrecomputed = (o) => { const p = store.get().precomp?.get(setKey(o || store.get().contingency)); return !!(p && p.ac); };
  wb.validate = () => { const s = store.get(); return validateScenario({ model: s.model, outage: s.contingency, engine: s.config.engine, apiAvailable: s.api.available, tableKs: s.tableKs,
    acPrecomputed: wb.acPrecomputed(), nPrecomputedAc: s.precomp ? [...s.precomp.values()].filter((v) => v.ac).length : 0 }); };
  wb.run = async function run() {
    const s = store.get(); if (!s.model) return; const v = wb.validate();
    if (!v.ok) { toast(v.errors[0]); return; }
    if (inflight) inflight.abort();                                   // a new request supersedes the previous one
    stopPlayback(); const id = ++reqSeq, outage = [...s.contingency].sort((a, b) => a - b), engine = s.config.engine, policy = s.config.policy;
    store.set({ run: { status: "running", id, engine, startedAt: performance.now() } });
    let res, source, ms;
    try {
      if (engine === "pre-ac") {
        const t0 = performance.now(); const p = s.precomp.get(setKey(outage)); if (!p || !p.ac) throw new Error("No precomputed AC run for this set.");
        res = p.ac; source = "retrieved from the data files (precomputed Python AC run)"; ms = performance.now() - t0;
      } else if (engine === "browser-dc") {
        await new Promise((r) => setTimeout(r, 0)); const t0 = performance.now(); res = wb.engine.run(outage, { policy }); ms = performance.now() - t0; source = "computed in this browser";
      } else {
        const ctl = new AbortController(); inflight = ctl; const timer = setTimeout(() => ctl.abort(new Error("timeout")), API_TIMEOUT_MS); const t0 = performance.now();
        try {
          const r = await fetch("cascade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ grid: s.gridId, outage, mode: engine === "api-ac" ? "ac" : "dc", policy }), signal: ctl.signal });
          const body = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(`API ${r.status}: ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || body)}`);
          res = body; source = body.source === "precomputed" ? "retrieved from the API (precomputed run)" : "computed by the API (live Python run)"; ms = performance.now() - t0;
        } finally { clearTimeout(timer); inflight = null; }
      }
    } catch (e) {
      if (id !== reqSeq) return;                                      // superseded
      const msg = e?.name === "AbortError" || /timeout/.test(String(e?.message || e)) ? `Request cancelled or timed out after ${API_TIMEOUT_MS / 1000} s` : String(e.message || e);
      store.set({ run: { status: "error", id, engine, error: msg } }); return;
    }
    if (id !== reqSeq) return;
    const events = buildEvents(res, s.model), trips = tripRounds(res), k = outage.length, rank = res.mode !== "ac" && s.dists[k] ? rankOf(s.dists[k], res.metrics.S) : null;   // the tables are DC: AC results are not ranked against them
    store.set({ run: { status: "done", id, engine, engineLabel: ENGINE_LABEL[engine], source, ms, result: res, events, trips, rank, k }, playback: { ...store.get().playback, i: 0, playing: false }, compare: { ...store.get().compare, showing: null } });
    if (!store.get().layers.reduced) wb.play(); else wb.goEvent(0);
  };
  wb.cancel = () => { if (inflight) inflight.abort(); };

  // ---------------------------------------------------------------- playback
  let ptimer = null;
  const DWELL = { initial_outage: 1500, round: 700, islanding: 1300, load_shed: 1200, overload: 1500, trip: 1500, termination: 0 };
  function stopPlayback() { clearTimeout(ptimer); ptimer = null; if (store.get().playback.playing) store.set({ playback: { ...store.get().playback, playing: false } }); }
  wb.stop = stopPlayback;
  wb.goEvent = (i, { frame = true } = {}) => {
    const s = store.get(); if (s.run.status !== "done") return; const n = s.run.events.length; i = Math.max(0, Math.min(n - 1, i));
    store.set({ playback: { ...s.playback, i } });
    const ev = s.run.events[i];
    if (frame && gs && s.playback.autoFrame) {
      const keys = ev.entities.length ? ev.entities : ev.type === "termination" || ev.type === "round" ? null : s.run.result.outage.map((l) => `branch:${l}`);
      if (keys) rig.frame(keys.flatMap((k) => gs.entityPoints(k)), { minRadius: 10, ms: 800 }); else if (ev.type === "termination") rig.overview();
    }
  };
  wb.play = () => {
    const s = store.get(); if (s.run.status !== "done") return; let i = s.playback.i >= s.run.events.length - 1 ? 0 : s.playback.i;
    store.set({ playback: { ...s.playback, playing: true } }); wb.goEvent(i);
    const tick = () => { const st = store.get(); if (!st.playback.playing) return; const ev = st.run.events[st.playback.i];
      if (st.playback.i >= st.run.events.length - 1) { store.set({ playback: { ...st.playback, playing: false } }); return; }
      ptimer = setTimeout(() => { if (!store.get().playback.playing) return; wb.goEvent(store.get().playback.i + 1); tick(); }, (DWELL[ev.type] ?? 1000) / st.playback.speed); };
    tick();
  };
  wb.togglePlay = () => (store.get().playback.playing ? stopPlayback() : wb.play());

  // ---------------------------------------------------------------- DC vs AC on the same set
  wb.acAvailable = () => { const s = store.get(); return wb.acPrecomputed() || (s.api.available && s.gridId !== "ieee118"); };
  wb.compareDcAc = async () => {
    const s0 = store.get(), keep = s0.config.engine;
    store.set({ config: { ...s0.config, engine: "browser-dc" } }); await wb.run(); stopPlayback(); if (store.get().run.status !== "done") return; wb.save();
    const acEngine = wb.acPrecomputed() ? "pre-ac" : "api-ac"; store.set({ config: { ...store.get().config, engine: acEngine } }); await wb.run(); stopPlayback();
    if (store.get().run.status !== "done") { store.set({ config: { ...store.get().config, engine: keep } }); return; }
    wb.save(); const sv = store.get().saved; store.set({ compare: { a: sv[sv.length - 2].id, b: sv[sv.length - 1].id, showing: sv[sv.length - 1].id }, config: { ...store.get().config, engine: keep } });
    const sec = $("sec-cmp"); if (sec) { sec.open = true; sec.scrollIntoView({ block: "nearest" }); }
    wb.goEvent(store.get().run.events.length - 1, { frame: false });
  };

  // ---------------------------------------------------------------- saved scenarios & comparison
  wb.save = () => {
    const s = store.get(); if (s.run.status !== "done") return; const r = s.run;
    const item = { id: `S${s.saved.length + 1}`, grid: s.gridId, outage: r.result.outage, engineLabel: r.engineLabel, source: r.source, result: r.result, events: r.events, trips: r.trips, rank: r.rank };
    store.set({ saved: [...s.saved, item] }); toast(`Saved as ${item.id} (kept for this session)`);
  };
  wb.show = (item) => {                                                // A/B: load a saved run into the scene, camera unchanged (coordinated view)
    const s = store.get(); if (item.grid !== s.gridId) { toast(`${item.id} is on ${item.grid}; switch network first`); return; }
    stopPlayback(); store.set({ contingency: [...item.outage], run: { status: "done", id: ++reqSeq, engine: "saved", engineLabel: item.engineLabel, source: `${item.source} · saved ${item.id}`, result: item.result, events: item.events, trips: item.trips, rank: item.rank, k: item.outage.length },
      playback: { ...s.playback, i: item.events.length - 1, playing: false }, compare: { ...s.compare, showing: item.id } });
  };

  // ---------------------------------------------------------------- pointer picking on the canvas
  if (gs) {
    let raf = 0, lastXY = null;
    canvas.addEventListener("pointermove", (e) => { if (rig.drag) return; lastXY = [e.offsetX, e.offsetY]; if (!raf) raf = requestAnimationFrame(() => { raf = 0; if (!lastXY) return;
      const k = gs.pick(lastXY[0], lastXY[1], e.pointerType === "touch" ? 16 : 9); if (k !== store.get().hover) store.set({ hover: k }); canvas.classList.toggle("pointing", !!k); }); });
    canvas.addEventListener("pointerleave", () => { lastXY = null; if (store.get().hover) store.set({ hover: null }); });
    canvas.addEventListener("click", (e) => {
      if ((rig.lastDragMoved || 0) > 4) return;                        // a drag is not a click
      const k = gs.pick(e.offsetX, e.offsetY, e.pointerType === "touch" ? 16 : 10);
      if (k && k.startsWith("branch:") && (e.shiftKey || e.altKey)) { wb.toggleContingency(+k.split(":")[1]); return; }
      wb.select(k || null);
    });
    canvas.addEventListener("dblclick", (e) => { const k = gs.pick(e.offsetX, e.offsetY, 10); if (k && k.startsWith("branch:")) wb.toggleContingency(+k.split(":")[1]); else if (k) wb.focus(k); });
  }

  // ---------------------------------------------------------------- keyboard
  window.addEventListener("keydown", (e) => {
    if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return; if (!$("research").hidden || document.body.dataset.mode === "geo") return;
    const s = store.get(), k = e.key;
    if (s.camera.mode === "recon" && ["w", "a", "s", "d", "r", "f", "W", "A", "S", "D", "R", "F"].includes(k)) return;   // flight keys
    if (k === "f" || k === "F") { if (s.selection) wb.focus(s.selection); }
    else if (k === "o" || k === "O" || k === "Home") rig && rig.overview();
    else if (k === "Escape") { if (s.camera.mode === "recon") wb.setCameraMode("orbit"); else if (s.selection) wb.select(null); }
    else if (k === " ") { e.preventDefault(); wb.togglePlay(); }
    else if (k === "]" || k === ".") wb.goEvent(s.playback.i + 1);
    else if (k === "[" || k === ",") wb.goEvent(s.playback.i - 1);
    else if (k === "Enter" && e.target === document.body) wb.run();
    else if ((k === "c" || k === "C") && s.selection?.startsWith("branch:")) wb.toggleContingency(+s.selection.split(":")[1]);
    else if (k === "?") wb.toggleGuide && wb.toggleGuide();
  });
  wb.setCameraMode = (m) => { if (!rig) return; rig.setMode(m); store.set({ camera: { ...store.get().camera, mode: m } }); };
  // view modes: spatial / focus / grid (3-D with decreasing context) and schematic (top-down topology)
  wb.setViewMode = (v) => {
    if (!rig) return; const c = store.get().camera;
    if (v === "schematic") { if (!c.schematic) wb.setSchematic(true); return; }
    if (c.schematic) wb.setSchematic(false);
    gs.setContext(v); store.set({ camera: { ...store.get().camera, context: v } });
  };
  wb.setSchematic = (on) => { if (!rig) return; gs.build(store.get().model, { schematic: on }); rig.setSchematic(on); rig.setScene(gs.L); store.set({ camera: { ...store.get().camera, schematic: on, mode: on ? "orbit" : store.get().camera.mode } }); syncScene(); };

  // ---------------------------------------------------------------- store → scene
  store.sub((s, ch) => {
    if (!s.model) return;
    if (!gs) { if (["model", "run", "playback"].some((k) => ch.has(k))) computeView(); return; }
    if (["model", "run", "playback", "layers"].some((k) => ch.has(k))) { syncScene(); return; }
    if (ch.has("contingency")) armHighlight();
    if (ch.has("selection") || ch.has("hover")) { gs.highlight("sel", s.selection, PAL.sel); gs.highlight("hov", s.hover && s.hover !== s.selection ? s.hover : null, PAL.hover); }
  });

  // ---------------------------------------------------------------- render loop
  if (gs) {
    const ro = new ResizeObserver(() => { gs.resize(); rig._apply && rig._apply(); }); ro.observe($("viewport"));
    let last = performance.now();
    const vp = $("viewport");
    const loop = (t) => { const dt = Math.min((t - last) / 1000, 0.05); last = t;
      if (vp.offsetParent === null || document.hidden) { requestAnimationFrame(loop); return; }      // not visible: no rendering
      const s = store.get(); rig.update(dt, s.camera.mode === "follow" && s.selection ? gs.entityPos(s.selection) : null); gs.setLOD(rig.p.distanceTo(rig.t));
      const drawn = gs.render(dt); if (drawn && wb.onFrame) wb.onFrame(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- panels
  initOverlays(wb); initExplorer(wb); initInspector(wb); initTimeline(wb);
  // API availability (only when the page is served by the FastAPI app)
  fetch("health", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((h) => { if (h && h.status === "ok") { store.set({ api: { available: true } }); toast("API detected: API DC/AC engines are available"); } }).catch(() => {});
  wb.entityLabel = (key) => entityLabel(store.get().model, key);
  wb.load = load;
  return wb;
}
