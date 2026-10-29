// Bengaluru Grid Explorer — interactive map (MapLibre GL, vendored) of publicly mapped power infrastructure. Data: OpenStreetMap through the
// Overpass API, queried from this browser when the mode opens (or a cached copy, or a file the user loads). Basemap: OpenStreetMap raster
// tiles, shown dimmed and adjustable. Nothing here is connected to the cascade engine, and nothing is drawn that the loaded source does not
// contain. Data model and rules: ./osm.js.
import * as O from "./osm.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const RM = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
// voltage-class colours: one ordinal ramp (higher voltage = lighter); widths repeat the order so colour is never the only cue
export const VCOL = { v400: "#dbe8f4", v220: "#a9c4dc", v110: "#7fa2c2", v66: "#5f84a6", v33: "#4c6782", vna: "#8a877f" };
const VW = { v400: 3.2, v220: 2.6, v110: 2.0, v66: 1.6, v33: 1.2, vna: 1.3 };
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const CACHE_KEY = "bengaluru-osm-power-v1";
const FETCH_TIMEOUT_MS = 150000;

// ---------------------------------------------------------------- tiny IndexedDB cache (per browser; failures are ignored)
function idb() { return new Promise((res, rej) => { try { const r = indexedDB.open("gdf-geo", 1); r.onupgradeneeded = () => r.result.createObjectStore("kv"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); } catch (e) { rej(e); } }); }
async function cacheGet(k) { try { const db = await idb(); return await new Promise((res) => { const q = db.transaction("kv").objectStore("kv").get(k); q.onsuccess = () => res(q.result || null); q.onerror = () => res(null); }); } catch { return null; } }
async function cacheSet(k, v) { try { const db = await idb(); await new Promise((res) => { const t = db.transaction("kv", "readwrite"); t.objectStore("kv").put(v, k); t.oncomplete = res; t.onerror = res; }); return true; } catch { return false; } }
async function cacheDel(k) { try { const db = await idb(); await new Promise((res) => { const t = db.transaction("kv", "readwrite"); t.objectStore("kv").delete(k); t.oncomplete = res; t.onerror = res; }); } catch { /* ignore */ } }

function loadScript(src) { return new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error(`could not load ${src}`)); document.head.appendChild(s); }); }

export function initGeo({ toast = () => {} } = {}) {
  const st = {
    map: null, ready: false, recs: [], shown: [], byId: new Map(), source: null, load: { status: "idle" }, sel: null,
    layers: { substation: true, plant: true, line: true, minor_line: true, cable: true, outlines: true, extent: true, labels: true },
    filters: { kinds: new Set(Object.keys(O.KINDS)), vclasses: new Set(O.VCLASSES.map(([k]) => k)), operator: null, namedOnly: false },
    basemap: { on: true, prominence: 0.45, error: null }, ctl: null,
  };
  const api = { state: st };
  window.__gdfGeo = api;                                            // handle for automated tests

  // ---------------------------------------------------------------- map
  async function ensureMap() {
    if (st.map) return true;
    if (!window.maplibregl) { try { await loadScript("vendor/maplibre/maplibre-gl.js"); } catch (e) { status(`The map library could not be loaded (${e.message}). Search and the asset list still work.`, true); return false; } }
    const ml = window.maplibregl;
    try {
      st.map = new ml.Map({ container: "geo-map", style: style(), center: O.CENTER, zoom: 10.4, minZoom: 8, maxZoom: 18.5, pitch: 0, bearing: 0, maxPitch: 70, attributionControl: false,
        maxBounds: [[O.AREA.west - 0.6, O.AREA.south - 0.6], [O.AREA.east + 0.6, O.AREA.north + 0.6]], fadeDuration: RM ? 0 : 300 });
    } catch (e) { status(`The map could not start (${e.message || e}); WebGL may be unavailable. Search and the asset list still work.`, true); st.map = null; return false; }
    const m = st.map;
    m.addControl(new ml.NavigationControl({ visualizePitch: true }), "top-right");
    m.addControl(new ml.ScaleControl({ unit: "metric" }), "bottom-left");
    m.addControl(new ml.AttributionControl({ compact: matchMedia("(max-width: 760px)").matches, customAttribution: `Infrastructure data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a> (ODbL)` }), "bottom-right");
    m.on("error", (e) => { if (e && e.sourceId === "basemap") { if (!st.basemap.error) { st.basemap.error = "Basemap tiles could not be loaded (no network access to tile.openstreetmap.org, or the tile server refused). Infrastructure layers still work."; renderLayers(); } } });
    await new Promise((res) => (m.loaded() ? res() : m.once("load", res)));
    addDataLayers(); st.ready = true; bindMap(); pushData(); return true;
  }
  function style() {
    return { version: 8, sources: { basemap: { type: "raster", tiles: [TILE_URL], tileSize: 256, maxzoom: 19, attribution: "Basemap © OpenStreetMap contributors" } },
      layers: [{ id: "bg", type: "background", paint: { "background-color": "#0e0f10" } },
        { id: "basemap", type: "raster", source: "basemap", paint: basemapPaint(), layout: { visibility: st.basemap.on ? "visible" : "none" } }] };
  }
  function basemapPaint() { const p = st.basemap.prominence; return { "raster-saturation": -0.85, "raster-brightness-max": 0.25 + 0.6 * p, "raster-brightness-min": 0, "raster-contrast": -0.15, "raster-opacity": 0.35 + 0.65 * p }; }
  const vcolor = () => ["match", ["get", "vclass"], ...Object.entries(VCOL).flat(), "#8a877f"];
  const vwidth = (k) => ["interpolate", ["linear"], ["zoom"], 9, ["*", k * 0.55, ["match", ["get", "vclass"], ...Object.entries(VW).flat(), 1.2]], 15, ["*", k * 1.6, ["match", ["get", "vclass"], ...Object.entries(VW).flat(), 1.2]]];
  function addDataLayers() {
    const m = st.map, empty = { type: "FeatureCollection", features: [] };
    m.addSource("extent", { type: "geojson", data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[O.AREA.west, O.AREA.south], [O.AREA.east, O.AREA.south], [O.AREA.east, O.AREA.north], [O.AREA.west, O.AREA.north], [O.AREA.west, O.AREA.south]] } } });
    m.addLayer({ id: "extent", type: "line", source: "extent", paint: { "line-color": "#8a877f", "line-width": 1, "line-dasharray": [3, 3], "line-opacity": 0.7 } });
    m.addSource("polys", { type: "geojson", data: empty }); m.addSource("lines", { type: "geojson", data: empty });
    m.addSource("pts", { type: "geojson", data: empty, cluster: true, clusterMaxZoom: 12, clusterRadius: 42 });
    m.addLayer({ id: "poly-fill", type: "fill", source: "polys", minzoom: 12, paint: { "fill-color": vcolor(), "fill-opacity": 0.12 } });
    m.addLayer({ id: "poly-line", type: "line", source: "polys", minzoom: 12, paint: { "line-color": vcolor(), "line-width": 1, "line-opacity": 0.8 } });
    // lines: voltage known (solid, width by class) and voltage not tagged (dashed); cables dotted, minor lines thinner
    m.addLayer({ id: "lines", type: "line", source: "lines", filter: ["all", ["!=", ["get", "vclass"], "vna"], ["!=", ["get", "kind"], "cable"]], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": vcolor(), "line-width": vwidth(1), "line-opacity": 0.95 } });
    m.addLayer({ id: "lines-na", type: "line", source: "lines", filter: ["all", ["==", ["get", "vclass"], "vna"], ["!=", ["get", "kind"], "cable"]], paint: { "line-color": VCOL.vna, "line-width": vwidth(1), "line-dasharray": [2, 1.5], "line-opacity": 0.85 } });
    m.addLayer({ id: "cables", type: "line", source: "lines", filter: ["==", ["get", "kind"], "cable"], paint: { "line-color": vcolor(), "line-width": vwidth(0.8), "line-dasharray": [0.6, 1.2], "line-opacity": 0.9 } });
    m.addLayer({ id: "lines-hit", type: "line", source: "lines", paint: { "line-color": "#000", "line-width": 12, "line-opacity": 0.001 } });
    m.addLayer({ id: "sel-line", type: "line", source: "lines", filter: ["==", ["get", "id"], ""], paint: { "line-color": "#f2efe8", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 15, 7], "line-opacity": 0.95 } });
    m.addLayer({ id: "clusters", type: "circle", source: "pts", filter: ["has", "point_count"], paint: { "circle-color": "#2b2e33", "circle-stroke-color": "#b3afa6", "circle-stroke-width": 1.2,
      "circle-radius": ["step", ["get", "point_count"], 11, 10, 14, 50, 18, 200, 23] } });
    m.addLayer({ id: "pts", type: "circle", source: "pts", filter: ["!", ["has", "point_count"]], paint: { "circle-color": vcolor(), "circle-stroke-color": ["match", ["get", "kind"], "plant", "#e8e5de", "#0e0f10"],
      "circle-stroke-width": ["match", ["get", "kind"], "plant", 2.5, 1.2], "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, ["match", ["get", "kind"], "plant", 5, 3.5], 15, ["match", ["get", "kind"], "plant", 10, 7.5]] } });
    m.addLayer({ id: "sel-pt", type: "circle", source: "pts", filter: ["==", ["get", "id"], ""], paint: { "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#f2efe8", "circle-stroke-width": 2.5, "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 9, 15, 15] } });
    applyLayerVisibility();
  }
  function applyLayerVisibility() {
    const m = st.map; if (!m || !m.getLayer("pts")) return; const L = st.layers, vis = (on) => (on ? "visible" : "none");
    m.setLayoutProperty("extent", "visibility", vis(L.extent));
    ["poly-fill", "poly-line"].forEach((id) => m.setLayoutProperty(id, "visibility", vis(L.outlines)));
    m.setLayoutProperty("basemap", "visibility", vis(st.basemap.on)); Object.entries(basemapPaint()).forEach(([k, v]) => m.setPaintProperty("basemap", k, v));
  }
  function bindMap() {
    const m = st.map, hit = ["pts", "lines-hit", "poly-fill"];
    m.on("click", (e) => {
      const cl = m.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0];
      if (cl) { m.getSource("pts").getClusterExpansionZoom(cl.properties.cluster_id).then((z) => move({ center: cl.geometry.coordinates, zoom: Math.min(z + 0.2, 16) })).catch(() => {}); return; }
      const f = m.queryRenderedFeatures(e.point, { layers: hit.filter((l) => m.getLayer(l)) })[0];
      select(f ? f.properties.id : null);
    });
    m.on("mousemove", (e) => { const f = m.queryRenderedFeatures(e.point, { layers: ["clusters", ...hit].filter((l) => m.getLayer(l)) })[0]; m.getCanvas().style.cursor = f ? "pointer" : ""; m.getCanvas().title = f ? (f.properties.point_count ? `${f.properties.point_count} assets: click to expand` : st.byId.get(f.properties.id)?.name || O.KINDS[f.properties.kind]) : ""; });
    ["move", "moveend", "sourcedata"].forEach((ev) => m.on(ev, () => scheduleOverlay()));
    m.on("pitchend", () => $("geo-tilt").setAttribute("aria-pressed", String(m.getPitch() > 5)));
  }
  const move = (opt) => (RM ? st.map.jumpTo(opt) : st.map.easeTo({ ...opt, duration: 700 }));

  // cluster counts and asset name labels as HTML (the map style uses no remote glyph server), de-overlapped, at most 40 labels
  let raf = 0; function scheduleOverlay() { if (!raf) raf = requestAnimationFrame(() => { raf = 0; overlay(); }); }
  function overlay() {
    const m = st.map, box = $("geo-labels"); if (!m || !st.ready) return; const html = [], placed = [];
    const seen = new Set();
    for (const f of m.queryRenderedFeatures({ layers: ["clusters"] })) { const id = f.properties.cluster_id; if (seen.has(id)) continue; seen.add(id); const p = m.project(f.geometry.coordinates);
      html.push(`<span class="gc" style="transform:translate(${p.x.toFixed(0)}px,${p.y.toFixed(0)}px) translate(-50%,-50%);color:#e8e5de">${f.properties.point_count}</span>`); }
    if (st.layers.labels && m.getZoom() >= 12.2) {
      const fs = m.queryRenderedFeatures({ layers: ["pts"] }).map((f) => st.byId.get(f.properties.id)).filter((r) => r && r.name);
      fs.sort((a, b) => (b.kv[0] || 0) - (a.kv[0] || 0));
      for (const r of fs) { if (placed.length >= 40) break; const p = m.project(r.point), w = r.name.length * 6.4 + 10, x0 = p.x + 8, y0 = p.y - 8;
        if (placed.some((q) => x0 < q[2] && x0 + w > q[0] && y0 < q[3] && y0 + 16 > q[1])) continue; placed.push([x0, y0, x0 + w, y0 + 16]);
        html.push(`<span class="gl" style="transform:translate(${x0.toFixed(0)}px,${y0.toFixed(0)}px)">${esc(r.name)}</span>`); }
    }
    box.innerHTML = html.join("");
  }

  // ---------------------------------------------------------------- data
  function setRecords(recs, source) {
    st.recs = recs; st.byId = new Map(recs.map((r) => [r.id, r])); st.source = source;
    if (st.sel && !st.byId.has(st.sel)) st.sel = null;                // selection never survives a data change it does not belong to
    if (st.filters.operator && !recs.some((r) => (r.operator || "(not tagged)") === st.filters.operator)) st.filters.operator = null;
    refresh();
  }
  function refresh() {
    st.shown = O.applyFilters(st.recs, { ...st.filters, kinds: new Set([...st.filters.kinds].filter((k) => st.layers[k])) });
    pushData(); renderSrc(); renderLayers(); renderFilters(); renderCoverage(); renderSearch(); renderIns();
    $("geo-count").textContent = st.recs.length ? `${st.shown.length.toLocaleString("en-US")} of ${st.recs.length.toLocaleString("en-US")} shown` : "";
  }
  function pushData() {
    const m = st.map; if (!m || !st.ready) return; const L = O.toLayers(st.shown);
    m.getSource("pts").setData(L.points); m.getSource("lines").setData(L.lines); m.getSource("polys").setData(L.polygons); highlight(); scheduleOverlay();
  }
  async function loadOverpass({ force = false } = {}) {
    if (!force) { const c = await cacheGet(CACHE_KEY); if (c && c.json) { useOverpass(c.json, { via: c.via, retrievedAt: c.retrievedAt, cached: true }); return; } }
    if (st.ctl) st.ctl.abort(); const ctl = new AbortController(); st.ctl = ctl; const t0 = Date.now(), errors = [];
    st.load = { status: "running", t0 }; renderSrc(); const tick = setInterval(() => { if (st.load.status === "running") renderSrc(); }, 1000);
    try {
      for (const ep of O.ENDPOINTS) {
        if (ctl.signal.aborted) break;
        const timer = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS);
        try {
          const r = await fetch(ep, { method: "POST", body: new URLSearchParams({ data: O.overpassQuery() }), signal: ctl.signal });
          if (!r.ok) { errors.push(`${new URL(ep).host}: HTTP ${r.status}${r.status === 429 ? " (rate limited)" : r.status === 504 ? " (server busy)" : ""}`); continue; }
          const json = await r.json(); if (!json || !Array.isArray(json.elements)) { errors.push(`${new URL(ep).host}: response is not Overpass JSON`); continue; }
          const retrievedAt = new Date().toISOString(); useOverpass(json, { via: ep, retrievedAt, cached: false });
          const saved = await cacheSet(CACHE_KEY, { json, via: ep, retrievedAt }); if (!saved) toast("Browser storage unavailable: the data will be queried again next time");
          return;
        } catch (e) { if (st.leaving) break; errors.push(`${new URL(ep).host}: ${e.name === "AbortError" ? (ctl.signal.aborted && Date.now() - t0 < FETCH_TIMEOUT_MS ? "cancelled" : "timed out") : e.message || "network error"}`); }
        finally { clearTimeout(timer); }
      }
      if (st.leaving) { st.load = { status: "idle" }; return; }                 // left the mode mid-query: not an error; it is retried on return
      st.load = { status: "error", errors }; renderSrc();
      status("OpenStreetMap infrastructure could not be loaded from the Overpass API. The map still works; you can retry, or load an export file (see Data source).", true);
    } finally { clearInterval(tick); if (st.ctl === ctl) st.ctl = null; }
  }
  function useOverpass(json, { via, retrievedAt, cached }) {
    const osmBase = json.osm3s?.timestamp_osm_base || null, recs = O.fromOverpass(json, { via, retrievedAt, osmBase });
    st.load = { status: "done" }; status(null);
    setRecords(recs, { kind: "overpass", via, retrievedAt, osmBase, cached, elements: json.elements.length });
  }
  async function loadFile(file) {
    let json; try { json = JSON.parse(await file.text()); } catch (e) { status(`${file.name} is not valid JSON (${e.message}). Nothing was loaded.`, true); return; }
    const retrievedAt = new Date().toISOString();
    let recs; if (Array.isArray(json.elements)) recs = O.fromOverpass(json, { file: file.name, retrievedAt, osmBase: json.osm3s?.timestamp_osm_base || null }).map((r) => ({ ...r, prov: { ...r.prov, via: `file ${file.name}` } }));
    else if (json.type === "FeatureCollection") recs = O.fromGeoJSON(json, { file: file.name, retrievedAt });
    else { status(`${file.name}: expected Overpass JSON (with "elements") or a GeoJSON FeatureCollection. Nothing was loaded.`, true); return; }
    if (!recs.length) { status(`${file.name} contains no features tagged power=substation, plant, line, minor_line or cable. Nothing was loaded.`, true); return; }
    st.load = { status: "done" }; status(null); setRecords(recs, { kind: "file", file: file.name, retrievedAt, elements: Array.isArray(json.elements) ? json.elements.length : json.features.length });
    fitTo(recs.flatMap((r) => (r.point ? [r.point] : r.line ? [r.line[0], r.line[r.line.length - 1]] : [])));
  }
  function fitTo(pts) { if (!st.map || !pts.length) return; const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]); st.map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]], { padding: 40, duration: RM ? 0 : 700, maxZoom: 14 }); }
  function status(msg, err = false) { const el = $("geo-status"); el.hidden = !msg; el.textContent = msg || ""; el.classList.toggle("err", !!err); }

  // ---------------------------------------------------------------- selection
  function select(id, { focus = false } = {}) {
    st.sel = id && st.byId.has(id) ? id : null; highlight(); renderIns(); renderSearch();
    if (st.sel && matchMedia("(max-width: 1180px)").matches) { $("geo").classList.add("show-ins"); $("geo").classList.remove("show-exp"); }   // narrow screens: open the asset sheet
    if (focus && st.sel) focusRec(st.byId.get(st.sel));
  }
  function focusRec(r) { if (!st.map) return; if (r.line) fitTo(r.line); else move({ center: r.point, zoom: Math.max(st.map.getZoom(), 14.5) }); }
  function highlight() { const m = st.map; if (!m || !m.getLayer("sel-pt")) return; const id = st.sel || ""; m.setFilter("sel-pt", ["==", ["get", "id"], id]); m.setFilter("sel-line", ["==", ["get", "id"], id]); }
  api.select = select;

  // ---------------------------------------------------------------- panels
  function renderSrc() {
    const s = st.source, L = st.load; let h = "";
    if (L.status === "running") h += `<div class="msg inf">Querying the Overpass API for OpenStreetMap power features… ${Math.round((Date.now() - L.t0) / 1000)} s elapsed. The server does not report progress; large queries can take a minute. <button class="btn sm" id="geo-cancel">Cancel</button></div>`;
    if (L.status === "error") h += `<div class="msg err"><b>Not loaded.</b> ${L.errors.map(esc).join("; ")}.</div>`;
    if (s) h += `<dl class="kv"><dt>source</dt><dd>${s.kind === "file" ? `file · ${esc(s.file)}` : "OpenStreetMap via Overpass API"}</dd>${s.via ? `<dt>endpoint</dt><dd>${esc(new URL(s.via).host)}</dd>` : ""}
      <dt>${s.kind === "file" ? "loaded" : "retrieved"}</dt><dd>${esc(new Date(s.retrievedAt).toISOString().replace("T", " ").slice(0, 16))} UTC${s.cached ? " (cached copy in this browser)" : ""}</dd>
      ${s.osmBase ? `<dt>OSM data as of</dt><dd>${esc(s.osmBase.replace("T", " ").replace("Z", " UTC"))}</dd>` : ""}<dt>elements returned</dt><dd>${s.elements.toLocaleString("en-US")}</dd><dt>licence</dt><dd>${s.kind === "file" ? "as stated by the file's publisher (OSM data: ODbL 1.0)" : "ODbL 1.0"}</dd></dl>`;
    else if (L.status !== "running") h += `<p class="faint" style="margin:0;font-size:12px">No infrastructure data loaded.</p>`;
    h += `<div class="row" style="flex-wrap:wrap"><button class="btn sm" id="geo-refresh" ${L.status === "running" ? "disabled" : ""}>${s?.kind === "overpass" ? "Query again" : "Query OpenStreetMap"}</button><label class="btn sm" for="geo-file">Load a file…</label><input type="file" id="geo-file" accept=".json,.geojson,application/json" hidden>${s?.cached ? `<button class="btn sm ghost" id="geo-clear">Clear cache</button>` : ""}</div>
      <details><summary class="faint" style="cursor:pointer;font-size:11.5px">Query used, and how to make an export file</summary><pre class="mono" style="white-space:pre-wrap;font-size:10.5px;margin:6px 0">${esc(O.overpassQuery())}</pre>
      <p class="faint" style="font-size:11.5px;margin:0">Run this in overpass-turbo.eu and export the raw Overpass JSON (or GeoJSON), then load the file here. ${esc(O.AREA.note)}</p><div class="row" style="margin-top:6px"><button class="btn sm" id="geo-copyq">Copy query</button></div></details>`;
    $("geo-src").innerHTML = h;
    const on = (id, f) => { const e = $(id); if (e) e.onclick = f; };
    on("geo-cancel", () => st.ctl && st.ctl.abort()); on("geo-refresh", () => loadOverpass({ force: true })); on("geo-clear", async () => { await cacheDel(CACHE_KEY); toast("Cached copy removed"); if (st.source) st.source.cached = false; renderSrc(); });
    on("geo-copyq", () => navigator.clipboard?.writeText(O.overpassQuery()).then(() => toast("Query copied"), () => toast("Clipboard blocked: select the query text and copy it")));
    $("geo-file").onchange = (e) => { const f = e.target.files && e.target.files[0]; if (f) loadFile(f); e.target.value = ""; };
  }
  function renderLayers() {
    const c = O.coverage(st.recs), L = st.layers, chk = (k, label, n, sw = "") => `<label class="chk"><input type="checkbox" data-layer="${k}" ${L[k] ? "checked" : ""}>${sw}${label}${n != null ? `<span class="n">${n.toLocaleString("en-US")}</span>` : ""}</label>`;
    const unavailable = ["Distribution transformers, poles and towers (not queried)", "Administrative boundaries (not loaded)", "Terrain (not loaded)", "Data-confidence overlay (no loaded source provides confidence values)", "KPTCL/BESCOM substation list (public list has no coordinates and no stated licence; not used)"];
    $("geo-layers").innerHTML = `${chk("substation", "Substations", c.byKind.substation)}${chk("plant", "Power plants", c.byKind.plant)}${chk("line", "Power lines", c.byKind.line)}${chk("minor_line", "Minor power lines", c.byKind.minor_line)}${chk("cable", "Power cables", c.byKind.cable)}
      ${chk("outlines", "Substation outlines (zoom ≥ 12)", null)}${chk("labels", "Names (zoom ≥ 12)", null)}${chk("extent", "Query extent (bounding box)", null)}
      <label class="chk"><input type="checkbox" id="geo-bm" ${st.basemap.on ? "checked" : ""}>Basemap (OpenStreetMap tiles)</label>
      <label class="chk" for="geo-bmp" style="gap:8px">prominence<input type="range" id="geo-bmp" min="0" max="1" step="0.05" value="${st.basemap.prominence}" style="flex:1" ${st.basemap.on ? "" : "disabled"} aria-label="Basemap prominence"></label>
      ${st.basemap.error ? `<div class="msg wrn">${esc(st.basemap.error)}</div>` : ""}
      <details><summary class="faint" style="cursor:pointer;font-size:11.5px">Not available (${unavailable.length})</summary><ul class="faint" style="font-size:11.5px;margin:4px 0 0;padding-left:16px">${unavailable.map((u) => `<li>${u}</li>`).join("")}</ul></details>`;
    $("geo-layers").querySelectorAll("[data-layer]").forEach((i) => (i.onchange = () => { st.layers[i.dataset.layer] = i.checked; applyLayerVisibility(); if (O.KINDS[i.dataset.layer]) refresh(); else scheduleOverlay(); }));
    $("geo-bm").onchange = (e) => { st.basemap.on = e.target.checked; applyLayerVisibility(); renderLayers(); };
    $("geo-bmp").oninput = (e) => { st.basemap.prominence = +e.target.value; applyLayerVisibility(); };
  }
  function renderFilters() {
    const c = O.coverage(st.recs), F = st.filters;
    $("geo-filters").innerHTML = `<div class="micro" style="font-size:10px">voltage class (from the voltage tag; line width and lightness both show it)</div>${O.VCLASSES.map(([k, n]) => `<label class="chk"><input type="checkbox" data-vc="${k}" ${F.vclasses.has(k) ? "checked" : ""}><span class="vsw" style="background:${VCOL[k]};height:${Math.max(2, VW[k])}px"></span>${n}<span class="n">${c.byVoltage[k].toLocaleString("en-US")}</span></label>`).join("")}
      <label class="micro" for="geo-op" style="font-size:10px;margin-top:4px">operator (operator tag)</label><select class="sel" id="geo-op"><option value="">all operators</option>${c.operators.slice(0, 30).map(([o, n]) => `<option value="${esc(o)}" ${F.operator === o ? "selected" : ""}>${esc(o)} (${n})</option>`).join("")}</select>
      <label class="chk"><input type="checkbox" id="geo-named" ${F.namedOnly ? "checked" : ""}>Only assets with a name</label>`;
    $("geo-filters").querySelectorAll("[data-vc]").forEach((i) => (i.onchange = () => { i.checked ? F.vclasses.add(i.dataset.vc) : F.vclasses.delete(i.dataset.vc); refresh(); }));
    $("geo-op").onchange = (e) => { F.operator = e.target.value || null; refresh(); };
    $("geo-named").onchange = (e) => { F.namedOnly = e.target.checked; refresh(); };
  }
  function renderCoverage() {
    const c = O.coverage(st.recs); if (!c.total) { $("geo-cov").innerHTML = `<p class="faint" style="margin:0;font-size:12px">Nothing loaded yet.</p>`; return; }
    const pc = (n) => `${((100 * n) / c.total).toFixed(0)}%`;
    $("geo-cov").innerHTML = `<dl class="kv"><dt>records</dt><dd>${c.total.toLocaleString("en-US")}</dd><dt>with a voltage tag</dt><dd>${c.withVoltage.toLocaleString("en-US")} (${pc(c.withVoltage)})</dd><dt>with a name</dt><dd>${c.named.toLocaleString("en-US")} (${pc(c.named)})</dd><dt>mapped line length</dt><dd>${c.lineKm.toFixed(0)} km (all line kinds, geometry length)</dd></dl>
      <p class="faint" style="margin:0;font-size:11.5px">Coverage is whatever volunteers have mapped in OpenStreetMap inside the query extent. It is not a complete or validated model of the KPTCL/BESCOM network: line endpoints are not matched to substations, ratings and impedances are not available, and nothing here can be simulated. The cascade engine runs only on the IEEE benchmarks.</p>`;
  }
  function renderSearch() {
    const q = $("geo-q").value, res = O.search(st.recs, q, 30), ul = $("geo-results");
    ul.innerHTML = !q.trim() ? "" : res.length ? res.map((r) => `<li><button data-id="${esc(r.id)}" aria-current="${r.id === st.sel}"><b style="font-weight:500;color:var(--ink-1)">${esc(r.name || "(no name)")}</b> <span class="faint">· ${O.KINDS[r.kind]}${r.kv.length ? ` · ${r.kv.join("/")} kV` : ""}</span><br><span class="faint mono" style="font-size:10.5px">${esc(r.prov.sourceId)}${st.shown.includes(r) ? "" : " · hidden by filters"}</span></button></li>`).join("") : `<li class="faint" style="font-size:12px;padding:4px">No loaded asset matches.</li>`;
    ul.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => select(b.dataset.id, { focus: true })));
  }
  function renderIns() {
    const box = $("geo-ins-b"), r = st.sel && st.byId.get(st.sel);
    if (!r) { box.innerHTML = `<p class="faint" style="margin:0;font-size:12px">Select a substation, plant or line on the map, or search for one. Values shown are the source's own tags; derived values are marked.</p>`; return; }
    const tagRows = Object.entries(r.tags).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
    let len = null; if (r.line) { len = 0; for (let i = 1; i < r.line.length; i++) len += O.haversineKm(r.line[i - 1], r.line[i]); }
    box.innerHTML = `<div class="ins-title">${esc(r.name || "(no name in the source)")}<small>${O.KINDS[r.kind]} · ${esc(r.prov.sourceId)}</small></div>
      <div class="stat-l">${r.status.map((x) => `<span class="${/not|Unverified|Incomplete|Approximate/.test(x) ? "w" : ""}">${esc(x)}</span>`).join("")}</div>
      <dl class="kv"><dt>voltage <span class="src case">tag</span></dt><dd>${r.voltageTag ? esc(r.voltageTag) : `<span class="faint">not tagged</span>`}</dd><dt>voltage class <span class="src derived">derived</span></dt><dd>${r.kv.length ? `${r.kv.join(" / ")} kV · ${O.VCLASSES.find(([k]) => k === r.vclass)[1]}` : "unknown"}</dd>
        <dt>operator <span class="src case">tag</span></dt>${r.operator ? `<dd>${esc(r.operator)}</dd>` : `<dd class="na">Not tagged</dd>`}<dt>ref <span class="src case">tag</span></dt>${r.ref ? `<dd>${esc(r.ref)}</dd>` : `<dd class="na">Not tagged</dd>`}
        ${r.nameKn ? `<dt>name (kn) <span class="src case">tag</span></dt><dd>${esc(r.nameKn)}</dd>` : ""}
        ${r.point ? `<dt>marker <span class="src derived">derived</span></dt><dd>${r.point[1].toFixed(5)}, ${r.point[0].toFixed(5)}</dd>` : ""}${len != null ? `<dt>geometry length <span class="src derived">derived</span></dt><dd>${len.toFixed(2)} km</dd>` : ""}
        <dt>geometry</dt><dd>${esc(r.precision)}</dd><dt>connectivity</dt><dd>${r.line ? "not established" : "not modelled"}</dd><dt>ratings, impedance</dt><dd class="na">Not available from this source</dd></dl>
      <div class="row"><button class="btn sm" id="geo-focus">Focus</button>${r.prov.url ? `<a class="btn sm" href="${esc(r.prov.url)}" target="_blank" rel="noopener">Open in OpenStreetMap</a>` : ""}</div>
      <details open><summary class="micro" style="cursor:pointer">provenance</summary><dl class="kv" style="margin-top:4px"><dt>source</dt><dd>${esc(r.prov.source)}</dd><dt>record</dt><dd>${esc(r.prov.sourceId)}</dd><dt>licence</dt><dd>${esc(r.prov.license)}</dd>
        ${r.prov.via ? `<dt>retrieved via</dt><dd>${esc(r.prov.via.startsWith("http") ? new URL(r.prov.via).host : r.prov.via)}</dd>` : ""}${r.prov.retrievedAt ? `<dt>retrieved</dt><dd>${esc(r.prov.retrievedAt.slice(0, 16).replace("T", " "))} UTC</dd>` : ""}${r.prov.osmBase ? `<dt>OSM data as of</dt><dd>${esc(r.prov.osmBase.slice(0, 16).replace("T", " "))} UTC</dd>` : ""}</dl></details>
      <details><summary class="micro" style="cursor:pointer">all source tags (${Object.keys(r.tags).length})</summary><table class="tagt">${tagRows}</table></details>
      <p class="faint" style="font-size:11.5px;margin:0">Mapped by OpenStreetMap volunteers. Not verified against KPTCL or BESCOM records, and not part of any simulated network.</p>`;
    $("geo-focus").onclick = () => focusRec(r);
  }
  $("geo-q").addEventListener("input", () => renderSearch());
  $("geo-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { const r = O.search(st.recs, e.target.value, 1)[0]; if (r) select(r.id, { focus: true }); } });
  $("geo-pan-data").onclick = () => { $("geo").classList.toggle("show-exp"); $("geo").classList.remove("show-ins"); };
  $("geo-pan-asset").onclick = () => { $("geo").classList.toggle("show-ins"); $("geo").classList.remove("show-exp"); };
  $("geo-home").onclick = () => st.map && move({ center: O.CENTER, zoom: 10.4, pitch: 0, bearing: 0 });
  $("geo-tilt").onclick = () => { if (!st.map) return; const on = st.map.getPitch() < 5; move({ pitch: on ? 50 : 0 }); $("geo-tilt").setAttribute("aria-pressed", String(on)); };
  $("geo-north").onclick = () => st.map && move({ bearing: 0 });
  $("geo-fs").onclick = () => { const el = document.querySelector(".geo-map-wrap"); if (document.fullscreenElement) document.exitFullscreen?.(); else (el.requestFullscreen ? el.requestFullscreen() : Promise.reject()).catch?.(() => toast("Full screen is not available here")); };
  document.addEventListener("fullscreenchange", () => st.map && st.map.resize());

  // ---------------------------------------------------------------- mode lifecycle
  api.enter = async () => {
    st.leaving = false; refresh();
    const ok = await ensureMap(); if (ok) { st.map.resize(); pushData(); }
    if (!st.recs.length && st.load.status !== "running") await loadOverpass();
  };
  api.leave = () => { if (st.ctl) { st.leaving = true; st.ctl.abort(); } };
  api.loadOverpass = loadOverpass; api.loadFile = loadFile;
  return api;
}
