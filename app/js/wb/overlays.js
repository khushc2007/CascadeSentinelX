// Viewport overlays: camera controls, layers menu, legend, navigation guide, scene-relative gizmo, saved viewpoints and entity labels.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function initOverlays(wb) {
  const { store, rig, gs } = wb;
  // ---- camera mode / view / fit / focus -----------------------------------------------------------------------------------------
  const modeBtns = [...$("cam-mode").querySelectorAll("button")], viewBtns = [...$("view-mode").querySelectorAll("button")];
  modeBtns.forEach((b) => (b.onclick = () => { if (b.dataset.m === "follow" && !store.get().selection) { wb.toast?.("Select an entity to follow"); } wb.setCameraMode(b.dataset.m); }));
  viewBtns.forEach((b) => (b.onclick = () => wb.setViewMode(b.dataset.v)));
  $("cam-fit").onclick = () => rig && rig.overview();
  $("cam-focus").onclick = () => { const s = store.get(); if (s.selection) wb.focus(s.selection); };
  $("cam-speed").onchange = (e) => { if (rig) rig.speed = e.target.value; store.set({ camera: { ...store.get().camera, speed: e.target.value } }); };
  // ---- guide ------------------------------------------------------------------------------------------------------------------------
  const guide = $("guide");
  const renderGuide = () => {
    const s = store.get(), recon = s.camera.mode === "recon", sch = s.camera.schematic;
    guide.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px"><span class="micro">${sch ? "schematic" : recon ? "recon flight" : s.camera.mode} controls</span><button class="btn sm ghost" id="guide-x" style="height:20px">hide</button></div><table>${
      (sch ? [["drag", "pan"], ["wheel", "zoom"], ["click", "select"], ["Shift+click", "add/remove branch"]]
        : recon ? [["W A S D", "move"], ["R / F", "rise / descend"], ["drag", "look"], ["Shift", "faster"], ["wheel", "move forward/back"], ["Esc", "back to orbit"]]
          : [["drag", "rotate"], ["right-drag", "pan"], ["wheel", "zoom"], ["click", "select · dbl-click branch: add"], ["Shift+click", "add/remove branch"], ["F / O", "focus / overview"], ["Space · [ ]", "play · step events"], ["Enter", "run"]]).map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join("")}</table>`;
    $("guide-x").onclick = () => wb.toggleGuide();
  };
  wb.toggleGuide = () => { const v = !store.get().ui.guide; store.set({ ui: { ...store.get().ui, guide: v } }); };
  $("help-btn").onclick = () => wb.toggleGuide();
  // ---- layers -----------------------------------------------------------------------------------------------------------------------
  const LAYERS = [["equipment", "Equipment (buses, generators, transformers)"], ["context", "Context city (decorative, not data)"], ["loads", "Demand columns (served / shed)"], ["flow", "Flow direction"], ["utilization", "Utilisation ramp"],
    ["outages", "Outages and trips"], ["islands", "Islands"], ["reference", "Ground reference grid"], ["reduced", "Reduced motion"]];
  const lm = $("layers-menu");
  const renderLayers = () => {
    const L = store.get().layers;
    lm.innerHTML = `<div class="micro" style="margin-bottom:4px">analytical layers</div>${LAYERS.map(([k, n]) => `<label><input type="checkbox" data-k="${k}" ${L[k] ? "checked" : ""}> ${n}</label>`).join("")}
      <div class="micro" style="margin:8px 0 4px">labels</div><div class="seg" id="lbl-seg">${["none", "key", "all"].map((v) => `<button data-v="${v}" aria-pressed="${L.labels === v}">${v}</button>`).join("")}</div>
      ${L.isolate != null || L.neighbourhood ? `<div style="margin-top:8px"><button class="btn sm" id="iso-x">Show the whole network</button></div>` : ""}`;
    lm.querySelectorAll("input[data-k]").forEach((i) => (i.onchange = () => store.set({ layers: { ...store.get().layers, [i.dataset.k]: i.checked } })));
    lm.querySelectorAll("#lbl-seg button").forEach((b) => (b.onclick = () => store.set({ layers: { ...store.get().layers, labels: b.dataset.v } })));
    const ix = $("iso-x"); if (ix) ix.onclick = () => store.set({ layers: { ...store.get().layers, isolate: null, neighbourhood: null } });
  };
  const toggleMenu = (btn, menu) => { const open = menu.hidden; document.querySelectorAll(".menu").forEach((m) => (m.hidden = true)); document.querySelectorAll("[aria-expanded]").forEach((b) => b.id !== "help-btn" && b.id !== "h-diag" && b.setAttribute("aria-expanded", "false")); menu.hidden = !open; btn.setAttribute("aria-expanded", String(open)); };
  $("layers-btn").onclick = () => toggleMenu($("layers-btn"), lm);
  $("bm-btn").onclick = () => toggleMenu($("bm-btn"), $("bm-menu"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll(".menu").forEach((m) => { if (!m.hidden) { m.hidden = true; document.querySelectorAll("#layers-btn, #bm-btn").forEach((b) => b.setAttribute("aria-expanded", "false")); } }); });
  document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".menu") && !e.target.closest("#layers-btn") && !e.target.closest("#bm-btn")) document.querySelectorAll(".menu").forEach((m) => (m.hidden = true)); });
  // ---- bookmarks ------------------------------------------------------------------------------------------------------------------
  let marks = [];
  const bmKey = () => `gdf.views.${store.get().gridId}`;
  wb.bookmarksLoad = () => { try { marks = JSON.parse(localStorage.getItem(bmKey()) || "[]"); } catch { marks = []; } renderBm(); };
  const bmSave = () => { try { localStorage.setItem(bmKey(), JSON.stringify(marks)); } catch { /* storage unavailable: kept for this session */ } };
  const renderBm = () => {
    const box = $("bm-list"); box.innerHTML = marks.length ? "" : `<span class="faint" style="font-size:12px">No saved views yet.</span>`;
    marks.forEach((m, i) => { const r = document.createElement("div"); r.className = "row"; r.innerHTML = `<button class="btn sm" style="flex:1;justify-content:flex-start">${esc(m.name)}</button><button class="btn sm ghost" aria-label="Delete ${esc(m.name)}">×</button>`;
      r.children[0].onclick = () => { rig.restore(m.pose); if (!!m.pose.schematic !== store.get().camera.schematic) wb.setSchematic(!!m.pose.schematic); };
      r.children[1].onclick = () => { marks.splice(i, 1); bmSave(); renderBm(); }; box.appendChild(r); });
    $("bm-save").disabled = marks.length >= 6;
  };
  $("bm-save").onclick = () => { if (!rig) return; marks.push({ name: `View ${marks.length + 1}${store.get().selection ? ` · ${wb.entityLabel(store.get().selection).split(" · ")[0]}` : ""}`, pose: rig.pose() }); bmSave(); renderBm(); };
  // ---- gizmo ------------------------------------------------------------------------------------------------------------------------
  const gz = $("gizmo-svg"), gro = $("gizmo-ro");
  wb.onCamera = (ro) => {
    const h = ro.heading;
    gz.innerHTML = `<circle r="20" fill="none" stroke="#3a3e44"/><g transform="rotate(${-h})"><path d="M0-19 4-8h-8z" fill="#e8e5de"/><path d="M0 19 4 8h-8z" fill="#5a5853"/><text y="-9.5" x="0" text-anchor="middle" font-size="0" fill="#000">N</text></g>
      <text x="0" y="4" text-anchor="middle" font-size="8.5" fill="#8a877f" font-family="IBM Plex Mono, monospace">${ro.schematic ? "TOP" : Math.round(ro.pitch) + "°"}</text>`;
    gro.innerHTML = ro.schematic ? `schematic · top-down<br>zoom ${ro.zoom.toFixed(1)}×<br><span class="faint">scene-relative</span>`
      : `${ro.mode}${ro.mode === "recon" ? ` · ${ro.speed}` : ""}<br>heading ${Math.round(h)}° · pitch ${Math.round(ro.pitch)}°<br>${ro.mode === "recon" ? `height ${ro.height.toFixed(1)}` : `range ${ro.distance.toFixed(1)}`} su <span class="faint">(scene units)</span>`;
  };
  // ---- legend -----------------------------------------------------------------------------------------------------------------------
  const lg = $("legend"); let legendEqOpen = false;
  const renderLegend = () => {
    const s = store.get(), L = s.layers, m = s.model; if (!m) return; const res = s.run.status === "done";
    if (!s.ui.legend) { lg.innerHTML = `<div class="legend-h"><span class="micro">legend</span><button class="btn sm ghost" id="lg-x" style="height:20px">show</button></div>`; $("lg-x").onclick = () => store.set({ ui: { ...store.get().ui, legend: true } }); return; }
    const sw = (c, dash = false, h = 3) => `<span class="sw${dash ? " dash" : ""}" style="background:${c};color:${c};height:${h}px"></span>`;
    const rows = [];
    const basis = res && s.run.result.mode === "ac" ? "AC (MVA) rating" : "DC rating";
    rows.push(`<div class="row">${L.utilization ? `<span class="sw" style="background:linear-gradient(90deg,#6a747e,#c3ced8)"></span><span>loading 0–80% of ${basis}</span>` : `${sw("#b4bcc5")}<span>branch in service</span>`}</div>`);
    rows.push(`<div class="row">${sw("#e0a33a", false, 4)}<span>80–100% (warning band)</span></div><div class="row">${sw("#d0473a", false, 5)}<span>above rating (trips this round)</span></div>`);
    if (L.outages) rows.push(`<div class="row">${sw("#d0473a", true)}<span>initial outage: bold dashes, cut markers, T0</span></div>${res ? `<div class="row"><span class="sym" style="color:#e07a68">×</span><span>tripped at this step: dashes + × at mid-span</span></div><div class="row">${sw("#8c4038", true, 2)}<span>tripped in an earlier round: fine dashes (R<i>n</i>)</span></div>` : ""}`);
    if (res && wb.gs?.kinds && [...wb.gs.kinds.values()].includes("unknown")) rows.push(`<div class="row">${sw("#7d848b")}<span>in service, loading not recorded for this result</span></div>`);
    if (!s.camera.schematic && (s.camera.context || "spatial") !== "grid" && L.context !== false) rows.push(`<div class="row"><span class="sym"><svg width="12" height="12"><rect x="1" y="4" width="4" height="8" fill="#2c2f33"/><rect x="6" y="1" width="5" height="11" fill="#24272b"/></svg></span><span>dark blocks: decorative city, not data</span></div>`);
    if (res) rows.push(`<div class="row">${sw("#3a3d42")}<span>de-energised branch / bus</span></div>`);
    if (L.flow) rows.push(`<div class="row"><span class="sym" style="color:#e6ebef">▸</span><span>DC flow direction; speed ∝ loading${res && !s.run.result.frames[0].flow ? " (not recorded for this result)" : ""}</span></div>`);
    const eq = [];
    if (L.equipment) eq.push(`<div class="row"><span class="sym"><svg width="14" height="12" viewBox="0 0 14 12"><path d="M3.5 0h7L14 6l-3.5 6h-7L0 6z" fill="#a9b2bc"/></svg></span><span>bus (size ∝ connections)</span></div>
      <div class="row"><span class="sym"><svg width="12" height="12"><rect x="1" y="1" width="10" height="10" rx="5" fill="#b8955a"/></svg></span><span>generator (size ∝ √Pmax)</span></div>
      <div class="row"><span class="sym"><svg width="12" height="12"><rect x="2" y="2" width="8" height="8" fill="#6f7680"/></svg></span><span>transformer (mid-span block)</span></div>`);
    if (L.loads) eq.push(`<div class="row"><span class="sym"><svg width="12" height="14"><rect x="3" y="4" width="6" height="10" fill="#8a7a63"/><rect x="3" y="0" width="6" height="4" fill="#d0473a" opacity=".5"/></svg></span><span>demand column (height ∝ MW); red = shed</span></div>`);
    if (L.islands && res) rows.push(`<div class="row"><span class="sym"><svg width="14" height="14"><circle cx="7" cy="7" r="6" fill="#8f7f5f" opacity=".6"/></svg></span><span>bus outside the main island</span></div>`);
    const tier = m.kvs.length > 1 && !s.camera.schematic ? `Elevation = voltage class (${m.kvs.join(" / ")} kV). ` : "";
    lg.innerHTML = `<div class="legend-h"><span class="micro">legend</span><button class="btn sm ghost" id="lg-x" style="height:20px">hide</button></div>${rows.join("")}
      ${eq.length ? `<details ${legendEqOpen ? "open" : ""} id="lg-eq"><summary>equipment symbols ▸</summary>${eq.join("")}</details>` : ""}<div class="note">${tier}Layout is synthetic (Kamada–Kawai), not geographic. Ratings are synthetic (${esc(m.ratingFamily)}).</div>`;
    const de = $("lg-eq"); if (de) de.ontoggle = () => (legendEqOpen = de.open);
    $("lg-x").onclick = () => store.set({ ui: { ...store.get().ui, legend: false } });
  };
  // ---- labels -------------------------------------------------------------------------------------------------------------------------
  const box = $("labels"), pool = new Map();
  function wantedLabels() {
    const s = store.get(), m = s.model, out = new Map(); if (!m) return out;
    const add = (key, text, cls) => { if (!out.has(key)) out.set(key, { text, cls }); };
    if (s.selection) add(s.selection, wb.entityLabel(s.selection), "sel");
    if (s.hover && s.hover !== s.selection) add(s.hover, wb.entityLabel(s.hover), "hov");
    if (s.layers.labels === "none") return out;
    const done = s.run.status === "done", v = wb.view();
    if (done && v) {
      s.run.result.outage.forEach((l) => add(`branch:${l}`, `OUT ${l}`, "init"));
      const ev = s.run.events[s.playback.i];                          // label only the equipment of the current event (readable at any size)
      if (ev && ev.type !== "initial_outage") ev.entities.slice(0, 12).forEach((k) => { const [kind, id] = k.split(":");
        add(k, kind === "bus" ? `bus ${id}` : ev.type === "trip" ? `R${ev.round} · ${id}` : ev.type === "overload" ? `${id} · ${Math.round(100 * (ev.values?.loading?.[id] ?? 0))}%` : id, kind === "bus" ? "dim" : ev.type === "trip" ? "trip" : ""); });
      if (s.layers.labels === "all") v.branches.forEach((b, l) => { if (b.state === "tripped" && b.tripRound) add(`branch:${l}`, `R${b.tripRound}`, "trip"); });
    } else s.contingency.forEach((l) => add(`branch:${l}`, `× ${l}`, "init"));
    if (s.layers.labels === "all") m.buses.forEach((b) => add(b.key, String(b.id), "dim"));
    return out;
  }
  wb.onFrame = () => {
    if (!gs || !gs.model) return; const want = wantedLabels(), seen = new Set(); const r = box.getBoundingClientRect(), placed = [];
    for (const [key, { text, cls }] of want) {                          // insertion order = priority (selection, hover, outages, event)
      const p = gs.project(gs.entityPos(key)); if (p[2] > 1 || p[0] < -40 || p[1] < -20 || p[0] > r.width + 40 || p[1] > r.height + 20) continue;
      const w = text.length * 6.7 + 10, h = 17, x0 = p[0] - w / 2, y0 = p[1] - 10 - h;
      if (cls !== "sel" && cls !== "hov" && placed.some((q) => x0 < q[2] && x0 + w > q[0] && y0 < q[3] && y0 + h > q[1])) continue;   // greedy de-overlap
      placed.push([x0, y0, x0 + w, y0 + h]);
      let el = pool.get(key); if (!el) { el = document.createElement("div"); pool.set(key, el); box.appendChild(el); }
      el.className = `lbl ${cls}`; if (el.textContent !== text) el.textContent = text; el.style.transform = `translate(${Math.round(p[0])}px, ${Math.round(p[1] - 10)}px) translate(-50%, -100%)`; el.hidden = false; seen.add(key);
    }
    for (const [k, el] of pool) if (!seen.has(k)) { el.remove(); pool.delete(k); }
  };
  // ---- reactions --------------------------------------------------------------------------------------------------------------------
  store.sub((s, ch) => {
    if (ch.has("camera")) { modeBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.m === s.camera.mode))); viewBtns.forEach((b) => b.setAttribute("aria-pressed", String(s.camera.schematic ? b.dataset.v === "schematic" : b.dataset.v === (s.camera.context || "spatial"))));
      $("cam-speed").hidden = s.camera.mode !== "recon"; $("reticle").hidden = s.camera.mode !== "recon"; modeBtns.forEach((b) => (b.disabled = s.camera.schematic && b.dataset.m === "recon")); renderGuide(); }
    if (ch.has("ui")) { guide.hidden = !s.ui.guide; $("help-btn").setAttribute("aria-expanded", String(s.ui.guide)); renderLegend(); }
    if (ch.has("layers")) { renderLayers(); renderLegend(); }
    if (ch.has("model") || ch.has("run") || ch.has("camera") || ch.has("playback")) renderLegend();
    if (gs && ["selection", "hover", "run", "playback", "layers", "contingency"].some((k) => ch.has(k))) gs.dirty = true;
  });
  renderGuide(); renderLayers(); $("cam-speed").hidden = true;
}
