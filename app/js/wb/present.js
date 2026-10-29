// Presentation mode: a guided, reproducible walk-through that drives the real workbench (same engine, same data). Every step can be left
// at any time; the workbench stays in the state the step produced, so the audience's questions can be answered by inspecting it.
const $ = (id) => document.getElementById(id);
const pc = (x) => `${(100 * x).toFixed(1)}%`;

export function initPresent(wb, { switchWorkspace, headline }) {
  const card = $("present"); let i = -1, steps = [];
  const s = () => wb.store.get();
  const build = () => [
    { t: "The network", go: async () => { switchWorkspace("investigate"); if (s().gridId !== "ieee118") await wb.loadGrid("ieee118"); wb.setContingency([]); if (s().camera.schematic) wb.setSchematic(false); wb.rig?.overview(); },
      body: () => { const m = s().model; return `IEEE-118 from the official MATPOWER 8.1 case: <b>${m.nBus} buses, ${m.nBranch} branches, ${m.gens.length} generators</b>, ${m.totalLoadMw.toFixed(0)} MW of demand (scaled by λ = 1.10). Elevation shows the voltage class; the layout itself is synthetic, not a map. Thermal ratings are synthetic.`; } },
    { t: "The most damaging 3-branch contingency", go: async () => { const d = s().dists[3]; await wb.loadSet("ieee118", d.top[0][1], false); },
      body: () => { const d = s().dists[3]; return `Out of <b>${d.N.toLocaleString("en-US")}</b> possible 3-branch outages, all simulated offline (exhaustive DC table), this set loses the most demand. The three branches are marked in red.`; } },
    { t: "Run it", go: async () => { wb.store.set({ config: { ...s().config, engine: "browser-dc", policy: "all_overloaded" }, playback: { ...s().playback, autoFrame: true, speed: 1 } }); await wb.run(); },
      body: () => `The cascade runs now, in this browser, with the same DC engine used for the tables. Each round: islands are re-formed and balanced, power flow is solved, branches above their rating trip. The timeline below records every event.` },
    { t: "What was lost", go: async () => { wb.stop(); const r = s().run; if (r.status === "done") wb.goEvent(r.events.length - 1); wb.rig?.overview(); wb.store.set({ layers: { ...s().layers, islands: true, loads: true } }); },
      body: () => { const r = s().run; if (r.status !== "done") return "Run the previous step first."; const M = r.result.metrics; return `<b>S = ${pc(M.S)}</b> of base demand unserved at the end: S₀ = ${pc(M.S0)} from the initial islanding and <b>C = ${pc(M.C)}</b> from the cascade itself, over ${M.rounds} rounds. Red columns are shed demand; dark buses lost all generation. Rank: ${r.rank ? `#${r.rank.rank.toLocaleString("en-US")} of ${r.rank.N.toLocaleString("en-US")}` : "–"}.`; } },
    { t: "What this does and does not show", go: async () => {},
      body: () => `This is a quasi-steady-state DC overload model on a test case. Our pre-registered tests found that DC screening does not reliably reproduce AC severity (E3), and that rankings change with the synthetic rating rule (E11). It identifies candidate contingencies for detailed study; it is not a blackout forecast.` },
    { t: "Could quantum search find it faster?", go: async () => { switchWorkspace("research"); document.getElementById("r-oracle").scrollIntoView({ behavior: "smooth" }); },
      body: () => { const e7 = headline?.e7?.ieee118_k3, e15 = headline?.e15; return `Ideal Grover search (emulated exactly) needs about 570 oracle calls for this table; a tuned genetic algorithm found the worst set in ${e7 ? Math.round(e7.best_mean_discovery) : "–"} evaluations in the ${e7 ? Math.round(100 * e7.best_success_rate) : "–"}% of runs where it succeeded. Our fault-tolerant resource model puts the quantum search about <b>${e15 ? Math.round(e15.ratio_realistic_ieee118_k3).toLocaleString("en-US") : "–"}× slower</b> than one CPU core at this size. No quantum hardware was used.`; } },
  ];
  async function show(k) {
    i = Math.max(0, Math.min(steps.length - 1, k)); const st = steps[i];
    card.hidden = false; card.innerHTML = `<div class="step"><span>presentation · ${i + 1} / ${steps.length}</span><span>← → keys</span></div><h3>${st.t}</h3><p>…</p>`;
    try { await st.go(); } catch (e) { console.error(e); }
    card.innerHTML = `<div class="step"><span>presentation · ${i + 1} / ${steps.length}</span><span>← → keys</span></div><h3>${st.t}</h3><p>${st.body()}</p>
      <div class="row"><button class="btn sm" id="pr-b" ${i === 0 ? "disabled" : ""}>Back</button><button class="btn sm primary" id="pr-n">${i === steps.length - 1 ? "Finish" : "Next"}</button><button class="btn sm ghost" id="pr-x">Exit and explore</button></div>`;
    $("pr-b").onclick = () => show(i - 1); $("pr-n").onclick = () => (i === steps.length - 1 ? exit() : show(i + 1)); $("pr-x").onclick = exit;
    if (!$("research").hidden) { $("research").prepend(card); card.style.position = "fixed"; card.style.top = "auto"; card.style.bottom = "16px"; card.style.left = "16px"; }
    else { $("viewport").appendChild(card); card.style.position = ""; card.style.top = ""; card.style.bottom = ""; card.style.left = ""; }
  }
  function exit() { card.hidden = true; i = -1; $("viewport").appendChild(card); card.style.position = ""; }
  document.addEventListener("keydown", (e) => { if (i < 0 || e.target.closest?.("input, select, textarea")) return; if (e.key === "ArrowRight") { e.preventDefault(); show(i + 1); } else if (e.key === "ArrowLeft") { e.preventDefault(); show(i - 1); } else if (e.key === "Escape") exit(); });
  return { start: () => { steps = build(); show(0); }, exit, get active() { return i >= 0; } };
}
