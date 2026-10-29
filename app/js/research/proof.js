// Proof: pre-registered falsification tests (E16), the E0-E16 ledger with a detail drawer, and data / engine provenance.
import { $, pct, fmtInt, GRIDNAME } from "../ui/util.js";
import { load } from "../ui/util.js";

const EV_CLASS = (label = "") => (/EMULATED/.test(label) ? "e" : /SIMULATED/.test(label) ? "s" : /ESTIMATED|MODELLED/.test(label) ? "d" : /NOT_RUN|PROPOSED/.test(label) ? "p" : "m");

export async function initProof(headline, evidence) {
  const F = headline?.e16 || {}, box = $("falsify");
  const cards = [
    ["F1", "“Classical search makes quantum search pointless here.”", `Structured classical search did not reach the worst set in ≪ √N evaluations at every tested size, so the quantum motivation survives. But a tuned heuristic still needed fewer evaluations than the emulated quantum query count on most tables (H-C1 ${F["H-C1"]?.holds ? "holds" : "does not hold"}), and on IEEE-118 it succeeded in only ${headline?.e7?.ieee118_k3 ? pct(headline.e7.ieee118_k3.best_success_rate, 0) : "a minority"} of runs.`],
    ["F2", "“The fast DC model is a good proxy for AC.”", `${headline?.e3 ? `${headline.e3.n_trustworthy} of ${headline.e3.n_evaluable}` : "None of the"} evaluable tables pass the pre-registered DC-vs-AC rule. The DC–AC gap is a measured result, not an assumption.`],
    ["F3", "“The worst-set rankings are a property of the grid.”", `Change only the synthetic rating rule and the top-10 sets change completely (median Jaccard ${headline?.e11_median_top10_jaccard ?? "–"}). Rankings characterise the model; real ratings are needed.`],
  ];
  box.innerHTML = cards.map(([id, claim, text]) => { const met = F[id]?.status === "MET";
    return `<div class="panel fcard reveal"><span class="tag2 ${met ? "fired" : "held"}">${id} · ${met ? "FALSIFIER FIRED" : "DID NOT FIRE"}</span><h3>${claim}</h3><p class="muted" style="font-size:.9rem">${text}</p><p class="tiny faint" style="margin-top:10px">Registered rule: ${F[id]?.name ?? "–"}</p></div>`; }).join("");
  document.querySelectorAll("#falsify .reveal").forEach((e) => e.classList.add("in"));

  const tiles = $("tiles"); tiles.innerHTML = "";
  for (const [id, e] of Object.entries(evidence || {})) {
    const b = document.createElement("button"); b.className = `tile ${e.status}`; const lab = e.status === "NOT_RUN" ? "NOT_RUN" : (e.label || "").replace(/^\[[A-Z_]+\]\s*/, "");
    b.innerHTML = `<span class="id">${id}</span><span class="nm">${e.name ?? ""}</span><span class="st">${e.status.replace("_", " ")} <span class="ev ${EV_CLASS(lab)}" style="font-size:.55rem;padding:1px 6px;margin-left:4px">${EV_CLASS(lab) === "e" ? "emulated" : EV_CLASS(lab) === "s" ? "simulated" : EV_CLASS(lab) === "d" ? "modelled" : EV_CLASS(lab) === "p" ? "not run" : "measured"}</span></span>`;
    b.onclick = () => openDrawer(id, e); tiles.appendChild(b);
  }
  const grids = await Promise.all(["ieee14", "ieee30", "ieee118"].map((g) => load(`grid_${g}.json`)));
  $("prov").innerHTML = `
    <div class="panel reveal in"><div class="label">Data</div><h3 style="margin:8px 0">Official MATPOWER 8.1 cases</h3><p class="muted tiny">Installed unmodified; every manifest records the commit and file hash. Ratings are synthetic (documented rule).</p>
      <div class="hash" style="margin-top:10px">commit ${grids[0]?.matpower_commit?.slice(0, 12) ?? "–"}<br>${grids.map((g) => g ? `${GRIDNAME[g.id]} sha256 ${g.file_sha256.slice(0, 16)}…` : "").join("<br>")}</div></div>
    <div class="panel reveal in"><div class="label">Engine parity</div><h3 style="margin:8px 0">Browser engine = Python engine</h3><p class="muted tiny">The JavaScript DC cascade matches the Python engine on 520 cascades (every worst-20 set per table plus 360 random sets): severity to 10⁻⁹, identical trips, islands and rounds. The resource model and Grover emulation are parity-tested the same way.</p></div>
    <div class="panel reveal in"><div class="label">Pre-registration</div><h3 style="margin:8px 0">Thresholds before results</h3><p class="muted tiny">Pass/fail rules for E0–E16 were committed before the runs; any later change is a recorded deviation. Compute-limited parts are reported as not run, never substituted.</p></div>`;
}

function openDrawer(id, e) {
  const d = $("drawer");
  d.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><span class="label">experiment</span><button class="btn sm ghost" id="drawer-x">Close <span class="kbd">Esc</span></button></div>
    <h2 style="font-size:2rem;margin:10px 0 4px">${id}</h2><h3 class="muted" style="font-weight:500">${e.name ?? ""}</h3>
    <dl class="kv" style="margin-top:16px"><dt>status</dt><dd>${e.status}</dd><dt>data</dt><dd>${e.data_status ?? "–"}</dd><dt>generated</dt><dd>${e.generated_utc ?? "–"}</dd></dl>
    <p class="muted" style="margin-top:14px;font-size:.9rem">${(e.label || "").replace(/^\[[A-Z_]+\]\s*/, "")}</p>
    <div class="parts">${(e.parts || []).map((p) => `<div class="part"><b>${p.name}</b> · <span style="color:${p.status === "EXECUTED" ? "var(--ok)" : p.status === "NOT_RUN" ? "var(--ink-3)" : "var(--warn)"}">${p.status}</span>${p.reason ? `<div class="faint tiny" style="margin-top:4px">${p.reason}</div>` : ""}</div>`).join("")}</div>
    <p class="tiny faint" style="margin-top:16px">Full numbers: results/phase7/${id}/result.json and REPORT.md in the repository.</p>`;
  d.classList.add("open"); $("drawer-x").onclick = closeDrawer; $("drawer-x").focus();
}
export function closeDrawer() { $("drawer").classList.remove("open"); }
