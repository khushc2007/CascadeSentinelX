// Explorer: entity lists (branches, buses, generators, loads), table scenarios, saved runs and islands; search by id; filters.
// Selecting a row selects the same entity id in the scene and inspector; "+" adds a branch to the contingency.
const $ = (id) => document.getElementById(id);
const pc = (x, d = 0) => (x == null ? "–" : `${(100 * x).toFixed(d)}%`);
const TABS = [["branches", "Branches"], ["buses", "Buses"], ["gens", "Generators"], ["loads", "Loads"], ["scenarios", "Scenarios"], ["islands", "Islands"]];
const BR_FILTERS = [["all", "all"], ["in", "in service"], ["out", "out"], ["over", "overloaded"], ["warn", "≥ 80%"], ["xfmr", "transformers"]];

export function parseQuery(q, m) {                       // exported for tests
  q = q.trim().toLowerCase(); if (!q) return null; let mm;
  if ((mm = q.match(/^(?:bus|b)\s*#?(\d+)$/))) return m.busById.has(+mm[1]) ? [`bus:${+mm[1]}`] : [];
  if ((mm = q.match(/^(?:line|branch|br|l|t|xfmr)\s*#?(\d+)$/))) return +mm[1] < m.nBranch ? [`branch:${+mm[1]}`] : [];
  if ((mm = q.match(/^(?:gen|g)\s*#?(\d+)$/))) return +mm[1] < m.gens.length ? [`gen:${+mm[1]}`] : [];
  if ((mm = q.match(/^(?:load)\s*#?(\d+)$/))) return m.byKey.has(`load:${+mm[1]}`) ? [`load:${+mm[1]}`] : [];
  if ((mm = q.match(/^(\d+)\s*[-–]\s*(\d+)$/))) { const a = +mm[1], b = +mm[2]; return m.branches.filter((br) => (br.fromId === a && br.toId === b) || (br.fromId === b && br.toId === a)).map((br) => br.key); }
  if ((mm = q.match(/^(\d+)$/))) { const n = +mm[1], out = []; if (m.busById.has(n)) out.push(`bus:${n}`); if (n < m.nBranch) out.push(`branch:${n}`); if (n < m.gens.length) out.push(`gen:${n}`); return out; }
  return m.buses.filter((b) => String(b.id).startsWith(q.replace(/\D/g, "")) && q.replace(/\D/g, "")).map((b) => b.key).slice(0, 30);
}

export function initExplorer(wb) {
  const { store } = wb; let tab = "branches", filter = "all", query = "";
  const tabsEl = $("exp-tabs"), filtEl = $("exp-filters"), list = $("exp-list");
  tabsEl.innerHTML = TABS.map(([k, n]) => `<button role="tab" data-t="${k}" aria-selected="${k === tab}">${n}</button>`).join("");
  tabsEl.querySelectorAll("button").forEach((b) => (b.onclick = () => { tab = b.dataset.t; query = ""; $("search").value = ""; render(); }));
  $("search").addEventListener("input", (e) => { query = e.target.value; render(); });
  $("search").addEventListener("keydown", (e) => { if (e.key === "Enter") { const first = list.querySelector("li[data-key]"); if (first) { wb.select(first.dataset.key, { focus: true }); } } if (e.key === "Escape") { e.target.value = ""; query = ""; render(); } });

  const row = (key, title, sub, extra = "", right = "") => `<li data-key="${key}" tabindex="0" aria-selected="${store.get().selection === key}"><div style="min-width:0"><div class="t">${title} ${extra}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>${right}</li>`;
  const addBtn = (l, s) => `<button class="addc" data-add="${l}" aria-pressed="${s.contingency.includes(l)}" title="${s.contingency.includes(l) ? "Remove from" : "Add to"} the contingency" aria-label="${s.contingency.includes(l) ? "Remove" : "Add"} branch ${l} ${s.contingency.includes(l) ? "from" : "to"} the contingency">${s.contingency.includes(l) ? "−" : "+"}</button>`;
  const barColor = (st) => (st === "overload" ? "var(--fail)" : st === "warning" ? "var(--warn)" : "#7d8a96");

  function branchRow(br, s, v) {
    const st = v.branches[br.l], u = st.u, tags = [];
    if (br.transformer) tags.push(`<span class="tag">T</span>`);
    if (st.state === "initial_outage") tags.push(`<span class="tag f">initial outage</span>`); else if (st.state === "tripped") tags.push(`<span class="tag t">tripped R${st.tripRound ?? "?"}</span>`);
    else if (st.state === "overload") tags.push(`<span class="tag f">over</span>`); else if (st.state === "warning") tags.push(`<span class="tag w">≥80%</span>`); else if (st.state === "deenergized") tags.push(`<span class="tag">dead</span>`);
    const ac = s.run.status === "done" && s.run.result.mode === "ac";
    const sub = `bus ${br.fromId}–${br.toId} · ${u == null ? "–" : pc(u)} of ${ac ? `${br.rating_ac_mva.toFixed(0)} MVA` : `${br.rating_dc_mw.toFixed(0)} MW`}${st.flow_mw != null ? ` · ${Math.abs(st.flow_mw).toFixed(0)} MW` : ""}<div class="bar"><i style="width:${Math.min(100, 100 * (u ?? 0))}%;background:${barColor(st.state)}"></i></div>`;
    return row(br.key, `${br.l}`, sub, tags.join(" "), addBtn(br.l, s));
  }
  function render() {
    const s = store.get(), m = s.model, v = wb.view(); if (!m || !v) { list.innerHTML = ""; return; }
    tabsEl.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(!query && b.dataset.t === tab)));
    filtEl.innerHTML = !query && tab === "branches" ? BR_FILTERS.map(([k, n]) => `<button class="chipf" data-f="${k}" aria-pressed="${filter === k}">${n}</button>`).join("") : "";
    filtEl.querySelectorAll("button").forEach((b) => (b.onclick = () => { filter = b.dataset.f; render(); }));
    let html = "", count = 0;
    if (query) {
      const keys = parseQuery(query, m) || []; count = keys.length;
      html = keys.length ? keys.map((k) => { const e = m.byKey.get(k); if (e.kind === "branch") return branchRow(e, s, v); if (e.kind === "bus") return busRow(e, s, v); if (e.kind === "gen") return genRow(e, v); return loadRow(e, v); }).join("")
        : `<li class="hdrrow"><span class="empty" style="padding:6px 0">No match. Try “bus 59”, “line 37”, “8-9”, “G4”.</span></li>`;
    } else if (tab === "branches") {
      const f = { all: () => true, in: (b) => !["initial_outage", "tripped"].includes(v.branches[b.l].state), out: (b) => ["initial_outage", "tripped"].includes(v.branches[b.l].state),
        over: (b) => v.branches[b.l].state === "overload", warn: (b) => ["warning", "overload"].includes(v.branches[b.l].state), xfmr: (b) => b.transformer }[filter];
      const rows = m.branches.filter(f); count = rows.length;
      html = rows.length ? rows.map((b) => branchRow(b, s, v)).join("") : `<li class="hdrrow"><span class="empty" style="padding:6px 0">No branch in this state${s.run.status === "done" ? " at the current event" : " (run a contingency to see cascade states)"}.</span></li>`;
    } else if (tab === "buses") { count = m.nBus; html = m.buses.map((b) => busRow(b, s, v)).join(""); }
    else if (tab === "gens") { count = m.gens.length; html = m.gens.map((g) => genRow(g, v)).join(""); }
    else if (tab === "loads") { count = m.loads.length; html = [...m.loads].sort((a, b) => b.demand_mw - a.demand_mw).map((l) => loadRow(l, v)).join(""); }
    else if (tab === "scenarios") html = scenarios(s);
    else if (tab === "islands") html = islands(s, v);
    list.innerHTML = html; $("exp-count").textContent = query ? `${count} match${count === 1 ? "" : "es"}` : count ? `${count}` : "";
    list.querySelectorAll("li[data-key]").forEach((li) => {
      li.onclick = (e) => { if (e.target.closest("[data-add]")) return; wb.select(li.dataset.key, { focus: true }); };
      li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); wb.select(li.dataset.key, { focus: true }); }
        if (e.key === "ArrowDown") { e.preventDefault(); li.nextElementSibling?.focus(); } if (e.key === "ArrowUp") { e.preventDefault(); li.previousElementSibling?.focus(); } };
    });
    list.querySelectorAll("[data-add]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); wb.toggleContingency(+b.dataset.add); }));
    list.querySelectorAll("[data-scn]").forEach((b) => (b.onclick = () => { const [k, i] = b.dataset.scn.split(":").map(Number); wb.loadSet(s.gridId, s.dists[k].top[i][1], b.dataset.run === "1"); }));
    list.querySelectorAll("[data-saved]").forEach((b) => (b.onclick = () => wb.show(s.saved.find((x) => x.id === b.dataset.saved))));
    list.querySelectorAll("[data-iso]").forEach((b) => (b.onclick = () => { const c = +b.dataset.iso; store.set({ layers: { ...store.get().layers, isolate: store.get().layers.isolate === c ? null : c } });
      const pts = m.buses.filter((bb, i) => v.buses[i].component === c).map((bb) => wb.gs.entityPos(bb.key)); if (wb.rig) wb.rig.frame(pts, { minRadius: 8 }); }));
  }
  function busRow(b, s, v) {
    const st = v.buses[b.i], tags = []; if (b.gens.length) tags.push(`<span class="tag g">G×${b.gens.length}</span>`); if (b.is_slack) tags.push(`<span class="tag">slack</span>`); if (!st.energized) tags.push(`<span class="tag f">de-energised</span>`);
    return row(b.key, `bus ${b.id}`, `${b.load_mw.toFixed(1)} MW demand · ${b.branches.length} branches${b.base_kv ? ` · ${b.base_kv} kV` : ""}`, tags.join(" "));
  }
  function genRow(g, v) { const pg = v.gens[g.g].pg_mw; return row(g.key, `G${g.g}`, `bus ${g.busId} · Pmax ${g.pmax_mw.toFixed(0)} MW · dispatch ${pg == null ? "unavailable" : `${pg.toFixed(0)} MW`}`, v.gens[g.g].energized ? "" : `<span class="tag f">de-energised</span>`); }
  function loadRow(l, v) { const f = v.buses[l.bus].served_fraction; return row(l.key, `load @ bus ${l.busId}`, `${l.demand_mw.toFixed(1)} MW · served ${f == null ? "unavailable" : pc(f, 1)}`, f != null && f < 1 - 1e-9 ? `<span class="tag f">shed ${pc(1 - f, 0)}</span>` : ""); }
  function scenarios(s) {
    let h = `<li class="hdrrow"><span class="micro">most damaging sets · exhaustive DC table</span></li>`;
    for (const k of s.tableKs) { const d = s.dists[k]; if (!d) continue;
      h += `<li class="hdrrow"><span class="faint" style="font-size:11.5px">k = ${k} · ${d.N.toLocaleString("en-US")} sets simulated · ${d.n_high.toLocaleString("en-US")} with S ≥ 20%</span></li>`;
      d.top.slice(0, 6).forEach(([S, o], i) => { h += `<li><div style="min-width:0"><div class="t">#${i + 1} · ${o.map((l) => `${l}`).join(", ")} ${wb.acPrecomputed(o) ? `<span class="tag" title="a stored Python AC run exists for this set">AC</span>` : ""}</div><div class="s">S = ${pc(S, 1)} · bus ${o.map((l) => `${s.model.branches[l].fromId}–${s.model.branches[l].toId}`).join(", ")}</div></div>
        <div class="row"><button class="btn sm" data-scn="${k}:${i}" data-run="0" title="Load as the contingency">Load</button><button class="btn sm" data-scn="${k}:${i}" data-run="1" title="Load and run">Run</button></div></li>`; }); }
    h += `<li class="hdrrow"><span class="micro">saved this session</span></li>`;
    h += s.saved.length ? s.saved.map((x) => `<li><div style="min-width:0"><div class="t">${x.id} · ${x.grid} · {${x.outage.join(", ")}}</div><div class="s">S = ${pc(x.result.metrics.S, 1)} · ${x.engineLabel.split(" (")[0]}</div></div><button class="btn sm" data-saved="${x.id}">Show</button></li>`).join("")
      : `<li class="hdrrow"><span class="faint" style="font-size:11.5px">Run a contingency, then “Save” in the Scenario panel.</span></li>`;
    return h;
  }
  function islands(s, v) {
    if (s.run.status !== "done") return `<li class="hdrrow"><span class="empty" style="padding:6px 0">Islands appear after a run.</span></li>`;
    if (v.islandIds.length === 0 || !s.run.result.frames[0].component) return `<li class="hdrrow"><span class="empty" style="padding:6px 0">Component membership per bus is unavailable for this result (API results report counts only: ${v.frame?.islands ?? "–"} islands).</span></li>`;
    const m = s.model, rows = v.islandIds.map((c) => { const bs = m.buses.filter((b, i) => v.buses[i].component === c); const dem = bs.reduce((a, b) => a + b.load_mw, 0), served = bs.reduce((a, b) => a + b.load_mw * (v.buses[b.i].served_fraction ?? 0), 0);
      return { c, n: bs.length, dem, served, main: c === v.mainIsland, gens: bs.reduce((a, b) => a + b.gens.length, 0) }; }).sort((a, b) => b.n - a.n);
    const dead = m.buses.filter((b, i) => !v.buses[i].energized).length;
    return `<li class="hdrrow"><span class="faint" style="font-size:11.5px">${v.frame.islands} connected components at this event · ${dead} buses without generation (de-energised)</span></li>` + rows.map((r) => `<li><div style="min-width:0"><div class="t">${r.main ? "main island" : `island ${r.c}`} · ${r.n} buses</div><div class="s">${r.gens} generators · demand ${r.dem.toFixed(0)} MW · served ${r.served.toFixed(0)} MW</div></div><button class="btn sm" data-iso="${r.c}" aria-pressed="${s.layers.isolate === r.c}">${s.layers.isolate === r.c ? "Show all" : "Isolate"}</button></li>`).join("");
  }
  store.sub((s, ch) => {
    if (["model", "run", "playback", "contingency", "saved", "layers"].some((k) => ch.has(k))) render();
    else if (ch.has("selection")) { list.querySelectorAll("li[data-key]").forEach((li) => li.setAttribute("aria-selected", String(li.dataset.key === s.selection)));
      const cur = list.querySelector(`li[data-key="${s.selection}"]`); if (cur && document.activeElement?.closest?.("#exp-list") == null) cur.scrollIntoView({ block: "nearest" }); }
  });
}
