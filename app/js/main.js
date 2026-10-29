// Grid Doomsday Finder — entry point. Investigate workspace: 3-D workbench (app/js/wb, app/js/three). Research workspace: experiment results
// (app/js/research). Data: ./data (scripts/build_demo_data.py). Nothing shown is invented: values come from the data files, the experiment
// outputs, or the parity-tested JavaScript ports of the Python engine.
import { load, toast } from "./ui/util.js";
import { createWorkbench } from "./wb/app.js";
import { initPresent } from "./wb/present.js";
import { initGeo } from "./geo/explorer.js";

const $ = (id) => document.getElementById(id);
let researchReady = null;

async function main() {
  const [index, headline, evidence, XC] = await Promise.all([load("index.json"), load("headline.json"), load("evidence.json"), load("crossover.json")]);
  const wb = await createWorkbench(index);
  window.__gdf = wb;                                         // handle for automated end-to-end tests (tests/e2e)

  // Bengaluru Grid Explorer: a separate geographic mode with its own data model; the benchmark state (network, run, selection) is kept
  // untouched while it is open and restored when a benchmark network is chosen again.
  const geo = initGeo({ toast }); wb.geo = geo; let geoMode = false;
  const BENCH_ONLY = ["h-run", "h-status", "h-sev", "h-present", "h-diag"];
  function setGeoMode(on) {
    geoMode = on; $("geo").hidden = !on; $("h-geo").hidden = !on;
    if (on) { $("research").hidden = true; $("wb").hidden = true; $("ws").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ws === "investigate"))); wb.stop && wb.stop(); }
    BENCH_ONLY.forEach((id) => $(id) && ($(id).style.display = on ? "none" : "")); document.querySelectorAll(".hdr .scn").forEach((e) => (e.style.display = on ? "none" : ""));
    document.body.dataset.mode = on ? "geo" : "benchmark";
    if (on) geo.enter(); else { geo.leave(); $("wb").hidden = false; $("grid-sel").value = wb.store.get().gridId; if (wb.gs) { wb.gs.resize(); wb.gs.dirty = true; } }
  }
  wb.setGeoMode = setGeoMode;
  function switchWorkspace(ws) {
    if (geoMode && ws === "research") setGeoMode(false);
    $("ws").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ws === ws)));
    $("research").hidden = ws !== "research"; $("wb").hidden = ws === "research";
    ["h-run", "h-exp", "h-ins", "grid-sel", "h-status", "h-sev"].forEach((id) => $(id) && ($(id).style.visibility = ws === "research" ? "hidden" : ""));
    document.querySelectorAll(".hdr .scn").forEach((e) => (e.style.visibility = ws === "research" ? "hidden" : ""));
    if (ws === "research" && !researchReady) researchReady = initResearch(wb, { index, headline, evidence, XC, switchWorkspace });
    if (ws === "investigate" && wb.gs) { wb.gs.resize(); wb.gs.dirty = true; }
  }
  wb.switchWorkspace = switchWorkspace;
  $("ws").querySelectorAll("button").forEach((b) => (b.onclick = () => switchWorkspace(b.dataset.ws)));
  $("grid-sel").onchange = async (e) => {
    const v = e.target.value;
    if (v.startsWith("geo:")) { if ($("research").hidden === false) switchWorkspace("investigate"); setGeoMode(true); return; }
    if (geoMode) setGeoMode(false);
    if (v !== wb.store.get().gridId) await wb.loadGrid(v); else $("grid-sel").value = v;
  };
  const wbEl = $("wb");
  $("h-exp").onclick = () => { if (geoMode) { $("geo").classList.toggle("show-exp"); $("geo").classList.remove("show-ins"); return; } if (matchMedia("(max-width: 1180px)").matches) { wbEl.classList.toggle("show-exp"); wbEl.classList.remove("show-ins"); } else wbEl.classList.toggle("no-exp"); requestAnimationFrame(() => wb.gs && wb.gs.resize()); };
  $("h-ins").onclick = () => { if (geoMode) { $("geo").classList.toggle("show-ins"); $("geo").classList.remove("show-exp"); return; } if (matchMedia("(max-width: 1180px)").matches) { wbEl.classList.toggle("show-ins"); wbEl.classList.remove("show-exp"); } else wbEl.classList.toggle("no-ins"); requestAnimationFrame(() => wb.gs && wb.gs.resize()); };
  const present = initPresent(wb, { switchWorkspace, headline }); $("h-present").onclick = () => present.start(); wb.present = present;

  await wb.loadGrid("ieee118");
  // first view: the worst 3-branch set loaded (not run), so the next action is obvious
  const d3 = wb.store.get().dists[3]; if (d3) wb.setContingency(d3.top[0][1]);
  showIntro(wb, present, d3);
  wb.store.set({ ui: { ...wb.store.get().ui } });
  if (location.hash === "#research") switchWorkspace("research");
  if (location.hash === "#present") present.start();
  if (location.hash === "#bengaluru") { $("grid-sel").value = "geo:bengaluru"; setGeoMode(true); }
  document.body.dataset.ready = "1";
}

function showIntro(wb, present, d3) {
  let dismissed = false; try { dismissed = localStorage.getItem("gdf.intro") === "done"; } catch { /* storage unavailable */ }
  if (dismissed || !d3) return; const el = $("intro");
  el.innerHTML = `<h3>Investigate a worst-case contingency</h3><ol>
    <li>The red branches are the most damaging 3-branch outage on IEEE-118, found by simulating all ${d3.N.toLocaleString("en-US")} combinations.</li>
    <li>Press <b>Run</b> (or Enter) to simulate the cascade in this browser.</li><li>Step through the events below; select any equipment to inspect it.</li></ol>
    <p>Quasi-steady-state DC model on a test case: results are model severities, not real-world forecasts.</p>
    <div class="row" style="margin-top:8px"><button class="btn sm primary" id="in-ok">Got it</button><button class="btn sm" id="in-pr">Guided presentation</button></div>`;
  el.hidden = false; const done = () => { el.hidden = true; try { localStorage.setItem("gdf.intro", "done"); } catch { /* ignore */ } };
  $("in-ok").onclick = done; $("in-pr").onclick = () => { done(); present.start(); };
  const un = wb.store.sub((st, ch) => { if (ch.has("run") && st.run.status !== "idle") { el.hidden = true; un(); } });
}

async function initResearch(wb, { index, headline, evidence, XC, switchWorkspace }) {
  const [{ initWall }, { initScan }, { initHunt }, { initOracle }, { initProof, closeDrawer }] = await Promise.all([
    import("./research/wall.js"), import("./research/scan.js"), import("./research/hunt.js"), import("./research/oracle.js"), import("./research/proof.js")]);
  const safe = (n, f) => { try { const r = f(); if (r?.catch) r.catch((e) => console.error(n, e)); return r; } catch (e) { console.error(n, e); return null; } };
  safe("proof", () => initProof(headline, evidence));
  safe("wall", () => initWall(headline, index));
  safe("scan", () => initScan({ loadSet: async (id, outage) => { switchWorkspace("investigate"); await wb.loadSet(id, outage, true); } }));
  safe("hunt", () => initHunt(headline));
  safe("oracle", () => initOracle(XC, headline));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

main().catch((e) => { console.error(e); toast(`Start-up failed: ${e.message || e}`, 8000); const f = $("fatal"); f.hidden = false; f.textContent = `Start-up failed: ${e.message || e}`; });
