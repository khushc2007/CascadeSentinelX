// Scenario validation, rank lookup against the exhaustive tables, comparison rows and the exportable findings text. Pure functions.

export const MAX_K = 8;                       // the API accepts up to 8 outages; the browser engine has no lower limit of its own
export const LIVE_API_GRIDS = new Set(["ieee14", "ieee30"]);

export function validateScenario({ model, outage, engine, apiAvailable, tableKs = [], acPrecomputed = false, nPrecomputedAc = 0 }) {
  const errors = [], warnings = [], info = [];
  const k = outage.length;
  if (!k) errors.push("Select at least one branch for the contingency.");
  if (k > MAX_K) errors.push(`At most ${MAX_K} branches (got ${k}).`);
  if (new Set(outage).size !== k) errors.push("Branches in the contingency must be distinct.");
  for (const l of outage) {
    if (!Number.isInteger(l) || l < 0 || l >= model.nBranch) errors.push(`Branch ${l} does not exist in ${model.id}.`);
    else if (!model.branches[l].in_service) errors.push(`Branch ${l} is out of service in the base case.`);
  }
  if (engine === "api-dc" || engine === "api-ac") {
    if (!apiAvailable) errors.push("The API is not reachable from this page (start it with `make serve`). The browser engine is available.");
    else if (!LIVE_API_GRIDS.has(model.id)) warnings.push(`The API runs live cascades only for IEEE-14/30; on ${model.id} it answers only for its precomputed sets and returns 409 otherwise.`);
  }
  if (engine === "pre-ac" && k && !acPrecomputed) errors.push(`No precomputed AC run for this set. Precomputed AC exists for ${nPrecomputedAc} sets on ${model.id} (the ten worst per table and the three example sets: see Scenarios); other sets need the API (\`make serve\`).`);
  if (engine === "pre-ac") info.push("Retrieved from the data files: a Python AC run made when the demo data was built (not recomputed here).");
  if (engine === "api-ac") info.push("AC runs use the Newton–Raphson AC model with the load-shedding ladder (S may be an interval: S … S_total).");
  if (k && tableKs.length) {
    if (tableKs.includes(k)) info.push(`Exhaustive DC table exists for k = ${k}: the result will be ranked against all C(${model.nBranch}, ${k}) sets.`);
    else info.push(`No exhaustive table for k = ${k} on ${model.id} (tables: k ∈ {${tableKs.join(", ")}}); the run is valid but cannot be ranked.`);
  }
  return { ok: errors.length === 0, errors, warnings, info, k };
}

// Rank of severity S among all N sets of a table: exact inside the stored top list, histogram-based (approximate) below it.
export function rankOf(d, S, band = 1e-9) {
  if (!d) return null;
  const top = d.top, minTop = top[top.length - 1][0];
  if (S <= band) return { rank: d.N - d.n_zero + 1, exact: false, zero: true, N: d.N, tiedZero: d.n_zero };
  if (S >= minTop - band) { let above = 0; for (const [v] of top) if (v > S + band) above++; return { rank: above + 1, exact: true, N: d.N }; }
  const b = Math.min(d.bins - 1, Math.floor(S * d.bins)); let above = 0; for (let i = b + 1; i < d.bins; i++) above += d.hist[i];
  above += Math.round(d.hist[b] * (1 - (d.bins * S - b)));
  return { rank: above + 1, exact: false, N: d.N };
}

const pc = (x) => (x == null ? "unavailable" : `${(100 * x).toFixed(2)}%`);
export function compareRows(a, b) {
  const f = (r, g) => (r ? g(r) : "–");
  const rows = [
    ["Network", (r) => r.grid], ["Outage set", (r) => r.outage.join(", ")], ["k", (r) => r.outage.length], ["Engine", (r) => r.engineLabel.split(" (")[0]],
    ["Trip policy", (r) => r.result.policy], ["S (final unserved)", (r) => pc(r.result.metrics.S)], ["S₀ (initial islanding)", (r) => pc(r.result.metrics.S0)],
    ["C = S − S₀ (cascade)", (r) => pc(r.result.metrics.C)], ["Rounds", (r) => r.result.metrics.rounds], ["Status", (r) => r.result.metrics.status],
    ["Secondary trips", (r) => (r.result.trips_per_round || r.result.frames.map((x) => x.tripped)).flat().length], ["Final islands", (r) => r.result.frames[r.result.frames.length - 1].islands],
    ["Rank in exhaustive table", (r) => (r.rank ? `${r.rank.exact ? "#" : "≈#"}${r.rank.rank.toLocaleString("en-US")} of ${r.rank.N.toLocaleString("en-US")}` : "not ranked")],
  ];
  return rows.map(([name, g]) => [name, f(a, g), f(b, g)]);
}

export function findingsMarkdown({ model, scenario, events, rank, evidence }) {
  const r = scenario.result, m = r.metrics, L = [];
  L.push(`# Contingency finding — ${model.id.toUpperCase()}`, "");
  L.push(`- Outage set (branch indices): ${r.outage.join(", ")}  (k = ${r.outage.length})`);
  L.push(`- Branches: ${r.outage.map((l) => `${l} = bus ${model.branches[l].fromId}–${model.branches[l].toId}${model.branches[l].transformer ? " (transformer)" : ""}`).join("; ")}`);
  L.push(`- Engine: ${scenario.engineLabel}; trip policy ${r.policy}; source ${scenario.source}`);
  L.push(`- Result: S = ${pc(m.S)} of base demand unserved at termination; S₀ = ${pc(m.S0)}; C = S − S₀ = ${pc(m.C)}; ${m.rounds} rounds; status ${m.status}`);
  if (m.S_total != null && Math.abs(m.S_total - m.S) > 1e-9) L.push(`- AC interval: S between ${pc(m.S)} (load-shed ladder) and ${pc(m.S_total)} (failed islands fully lost)`);
  if (rank) L.push(`- Rank: ${rank.zero ? `no load lost (tied with ${rank.tiedZero.toLocaleString("en-US")} sets)` : `${rank.exact ? "#" : "≈#"}${rank.rank.toLocaleString("en-US")} of ${rank.N.toLocaleString("en-US")} sets in the exhaustive DC table`}`);
  L.push("", "## Event sequence", "");
  for (const e of events) if (e.type !== "round") L.push(`- R${e.round} · ${e.title}${e.detail ? ` — ${e.detail}` : ""}`);
  L.push("", "## Model and provenance", "");
  L.push(`- Quasi-steady-state DC overload cascade (V2 §8); stress λ = 1.10; synthetic thermal ratings (${model.ratingFamily}); topology/loads: official MATPOWER 8.1 ${model.id} (commit ${String(model.provenance.matpower_commit).slice(0, 12)}, sha256 ${String(model.provenance.file_sha256).slice(0, 16)}…)`);
  L.push(`- Layout is synthetic (Kamada–Kawai), not geographic. S is a fraction of test-case demand under this model; it is not a blackout probability or a real-world impact estimate.`);
  if (evidence) L.push(`- Evidence class: ${evidence}`);
  return L.join("\n");
}
