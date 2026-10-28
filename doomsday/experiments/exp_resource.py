"""Phase 11 E15 (resource and crossover sensitivity with MEASURED inputs, V2 16-17) and Phase 14 E16 (falsification summary, V2 18.1).
E15 replaces V2 placeholders by values measured in E1, E2, E6, E7, E12 and E14 wherever those experiments executed; every parameter keeps its
provenance. The model stays [ESTIMATED]: kappa_cal comes from a toy-scale synthesized micro-oracle, the IEEE-scale circuit is never synthesized."""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np
from ..resource.components import SCENARIOS
from ..resource.crossover import crossover_N
from ..resource.params import ModelParams, SRC_V2
from ..resource.scenarios import evaluate, heatmap_N_star, k_star, sweep_k, tornado
from . import specs as SP
from .framework import ExpOutput, Part

L118, B118, K = 186, 118, 3
PREPS_E15 = ("v2_assumed", "be_counted", "tree_counted")
TT = {"optimistic": 1e-6, "realistic": 10e-6, "pessimistic": 100e-6}
C1, C2, C3, GRID, INK, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#e4e3df", "#0b0b0b", "#52514e"

def measured_inputs(ctx) -> dict:
    """Collect measured parameters with provenance; missing experiments leave the V2 placeholder (flagged)."""
    m = {"sources": {}, "missing": []}
    e1 = ctx.load_result("E1"); e2 = ctx.load_result("E2"); e6 = ctx.load_result("E6"); e7 = ctx.load_result("E7"); e12 = ctx.load_result("E12"); e14 = ctx.load_result("E14")
    if e1 and "ieee118" in e1["payload"].get("t_c_ms_for_resource_model", {}):
        m["t_c_s"] = e1["payload"]["t_c_ms_for_resource_model"]["ieee118"]["dc_mean_random"] / 1e3; m["sources"]["t_c_s"] = "E1 IEEE-118 DC mean, random k=3 sets (this machine, scalar Python)"
    else: m["missing"].append("E1 (t_c)")
    ri = (e2 or {}).get("payload", {}).get("resource_inputs", {}); key = "ieee118_k3" if "ieee118_k3" in ri else ("ieee118_k2" if "ieee118_k2" in ri else None)
    if key:
        r = ri[key]; m.update(R={"p50": r["R_p50"], "p95": r["R_p95"], "max": r["R_max"]}, keff={"p50": r["keff_p50"], "p95": r["keff_p95"], "max": r["keff_max"]}, keff_k=int(key[-1]))
        m["sources"]["R_keff"] = f"E2 {key} (rounds on S>0; keff = k + trips on high-severity sets)"
    else: m["missing"].append("E2 IEEE-118 (R, keff)")
    if e6 and e6["payload"]["resource_inputs"].get("c_q_mean_over_tables"):
        ri6 = e6["payload"]["resource_inputs"]; m.update(c_q={"mean": ri6["c_q_mean_over_tables"], "p95": ri6["c_q_p95_over_tables"]}, c_tail=ri6.get("c_tail_certified_minus_discovery_over_sqrtN"))
        m["sources"]["c_q"] = "E6 Tier B emulation, discovery calls / sqrt(N/M), mean and p95 over all tables"
    else: m["missing"].append("E6 (c_q)")
    if e12 and e12["payload"].get("min_passing_b_overall"):
        m["b_min"] = e12["payload"]["min_passing_b_overall"]; m["sources"]["b"] = "E12 minimum passing b (labels + top-10 preserved)"
    else: m["missing"].append("E12 (b)")
    if e7:
        fits = {k: v for k, v in e7["payload"].get("alpha_fits_dc", {}).items() if v}
        struct = {k: v for k, v in fits.items() if k.split("|")[0] in SP.F1["structured_methods"] and v["n_points"] >= 3}
        if struct:
            best = min(struct.items(), key=lambda kv: kv[1]["exponent"]); m["alpha"] = {"best_structured": {"method": best[0], **best[1]},
                                                                                       "all": {k: {"alpha": v["exponent"], "kappa": v["coefficient"], "n": v["n_points"], "r2": v["r2"]} for k, v in fits.items()}}
            m["sources"]["alpha"] = "E7 log-log fit of mean discovery evaluations vs N (DC tables, all grids)"
    if "alpha" not in m: m["missing"].append("E7 (alpha)")
    if e14 and e14["payload"].get("all_checks_pass"):
        m["kappa_cal"] = {k: v["kappa_cal"] for k, v in e14["payload"]["calibration"].items() if isinstance(v, dict) and v.get("kappa_cal") is not None}
        m["sources"]["kappa_cal"] = "E14 A2 micro-oracle (toy, textbook synthesis)"
    else: m["missing"].append("E14 (kappa_cal)")
    return m

def params_for(m: dict, scenario: str) -> ModelParams:
    """V2 16.3 scenario rules with measured values substituted where available."""
    p = ModelParams(); kw, src = {"t_toffoli_s": TT[scenario]}, {}
    q = {"optimistic": "p50", "realistic": "p95", "pessimistic": "max"}[scenario]
    if "t_c_s" in m: kw["t_classical_s"] = m["t_c_s"]
    if "R" in m and m["R"][q]: kw["R"] = int(min(30, math.ceil(m["R"][q])))
    if "keff" in m and m["keff"][q]: kw["k_eff_factor"] = float(m["keff"][q]) / m["keff_k"]
    if "c_q" in m: kw["c_q"] = float(m["c_q"]["p95" if scenario == "pessimistic" else "mean"])
    if "b_min" in m: kw["b"] = {"optimistic": int(m["b_min"]), "realistic": int(max(16, m["b_min"])), "pessimistic": 24}[scenario]
    else: kw["b"] = {"optimistic": 16, "realistic": 16, "pessimistic": 24}[scenario]
    kw["uncompute_factor"] = 1.0 if scenario == "optimistic" else 2.0
    return p.with_(source=f"E15 measured/V2 16.3 rule ({scenario})", **kw)

def _fig(payload, d: Path) -> list:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})
    figs = []
    # time vs k (realistic, be_counted, calibrated vs uncalibrated) against classical exhaustive
    sw = payload["sweep_realistic_be_counted"]; ks = [r["k"] for r in sw["uncalibrated"]]
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=150)
    ax.plot(ks, [r["Tc_s"] for r in sw["uncalibrated"]], color=C1, lw=2, marker="o", ms=4, label="classical exhaustive (1 core, E1 t_c)")
    ax.plot(ks, [r["Tq_s"] for r in sw["uncalibrated"]], color=C2, lw=2, marker="o", ms=4, label="quantum model, V2 formulas")
    if sw.get("calibrated"):
        ax.plot(ks, [r["Tq_s"] for r in sw["calibrated"]], color=C3, lw=2, marker="o", ms=4, label="quantum model, kappa-calibrated (E14, partial)")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.set_yscale("log"); ax.set_xlabel("k (outage-set size), IEEE-118"); ax.set_ylabel("time (s), log scale"); ax.grid(True, color=GRID, lw=0.6); ax.set_xlim(ks[0] - 0.3, ks[-1] + 0.3)
    ax.set_title("E15 [ESTIMATED] realistic scenario, measured inputs, BE Dicke prep", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); p = d / "fig_E15_time_vs_k.png"; fig.savefig(p); plt.close(fig); figs.append(p.name)
    # tornado
    tor = payload["tornado_realistic_be_counted_calibrated"] or payload["tornado_realistic_be_counted_uncalibrated"]
    rows = [r for r in tor["rows"] if r["log10_swing"] is not None][:12]; n0 = math.log10(tor["baseline_N_star"])
    fig, ax = plt.subplots(figsize=(7, 4.6), dpi=150)
    for i, r in enumerate(reversed(rows)):
        lo, hi = [math.log10(v) for v in (min(r["N_star"]), max(r["N_star"]))]
        ax.barh(i, hi - lo, left=lo, color=C1, height=0.6); ax.text(hi + 0.2, i, f"{r['values'][0]:g} .. {r['values'][-1]:g}" if not isinstance(r["values"][0], str) else " / ".join(r["values"]), va="center", fontsize=7, color=MUTED)
    ax.axvline(n0, color=INK, lw=1); ax.set_yticks(range(len(rows))); ax.set_yticklabels([r["param"] for r in reversed(rows)], fontsize=8)
    ax.set_xlabel("log10 N* (crossover set count)"); ax.grid(True, axis="x", color=GRID, lw=0.6)
    ax.set_title("E15 [ESTIMATED] tornado of N*, realistic, measured base", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); p = d / "fig_E15_tornado.png"; fig.savefig(p); plt.close(fig); figs.append(p.name)
    # heat map
    hm = payload["heatmap_realistic_be_counted"]; Z = np.log10(np.array(hm["N_star"], float))
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150); im = ax.imshow(Z, cmap="Blues", aspect="auto", origin="lower")
    ax.set_xticks(range(len(hm["tT_s"]))); ax.set_xticklabels([f"{t * 1e6:g}" for t in hm["tT_s"]]); ax.set_yticks(range(len(hm["P"]))); ax.set_yticklabels([f"{P:g}" for P in hm["P"]])
    for i in range(Z.shape[0]):
        for j in range(Z.shape[1]): ax.text(j, i, f"{Z[i, j]:.0f}", ha="center", va="center", fontsize=7, color="white" if Z[i, j] > Z.mean() else INK)
    ax.set_xlabel("logical Toffoli time t_T (us)"); ax.set_ylabel("classical cores P"); fig.colorbar(im, ax=ax, label="log10 N*")
    ax.set_title("E15 [ESTIMATED] log10 N*, realistic", fontsize=10, color=INK, loc="left")
    fig.tight_layout(); p = d / "fig_E15_heatmap.png"; fig.savefig(p); plt.close(fig); figs.append(p.name)
    return figs

def e15(config, ctx) -> ExpOutput:
    m = measured_inputs(ctx); kap = m.get("kappa_cal"); payload = {"measured_inputs": m, "scenarios": {}}
    for sc in SCENARIOS:
        p = params_for(m, sc); payload["scenarios"][sc] = {"params": p.to_dict()}
        for prep in PREPS_E15:
            for cal in ("uncalibrated", "calibrated"):
                if cal == "calibrated" and not kap: continue
                kk = kap if cal == "calibrated" else None
                r = evaluate(L118, B118, K, sc, prep, p, kappa=kk, kappa_source="E14")
                r1000 = evaluate(L118, B118, K, sc, prep, p.with_(P=1000), kappa=kk)
                payload["scenarios"][sc][f"{prep}|{cal}"] = {"G": r["toffoli_per_grover_iteration"]["G"], "E_f": r["toffoli_per_grover_iteration"]["oracle_compute_E_f"],
                    "C_D": r["toffoli_per_grover_iteration"]["dicke_prep_C_D"], "Tq_s": r["totals"]["quantum_total_time_s"], "Tc_s": r["separate_costs"]["classical_time_s"],
                    "ratio_Tq_over_Tc": r["totals"]["ratio_Tq_over_Tc"], "N_star_P1": r["crossover"]["N_star"], "N_star_P1000": r1000["crossover"]["N_star"],
                    "k_star_P1": k_star(L118, B118, sc, prep, p, kmax=40, kappa=kk), "k_star_P1000": k_star(L118, B118, sc, prep, p.with_(P=1000), kmax=40, kappa=kk),
                    "logical_qubits": r["logical_qubits"]["total"], "physical_qubits": r["physical_qubits_estimate"]["v2_volume_convention"]["physical_total"],
                    "calibrated": r["calibrated"], "component_calibration": r["component_calibration"]}
    p = params_for(m, "realistic")
    payload["sweep_realistic_be_counted"] = {"uncalibrated": sweep_k(L118, B118, range(3, 13), "realistic", "be_counted", p),
                                             "calibrated": sweep_k(L118, B118, range(3, 13), "realistic", "be_counted", p, kap) if kap else None}
    RANGES = {"t_toffoli_s": [1e-6, 100e-6], "c_q": [2.0, 20.0], "t_classical_s": [p.t_classical_s / 10, p.t_classical_s * 10], "P": [1, 100000], "Pq": [1, 100],
              "b": [12, 32], "R": [2, 30], "k_eff_factor": [3.0, 1.5 * p.k_eff_factor], "c_rot": [10, 30], "uncompute_factor": [1.0, 2.0], "D": [10, 40],
              "scenario": ["optimistic", "pessimistic"], "prep": ["v2_assumed", "be_counted"]}
    payload["tornado_realistic_be_counted_uncalibrated"] = tornado(L118, B118, K, "realistic", "be_counted", p, RANGES)
    payload["tornado_realistic_be_counted_calibrated"] = tornado(L118, B118, K, "realistic", "be_counted", p, RANGES, kappa=kap) if kap else None
    payload["heatmap_realistic_be_counted"] = heatmap_N_star(L118, B118, K, "realistic", "be_counted", p, [1e-6, 3e-6, 10e-6, 30e-6, 100e-6], [1, 10, 100, 1000, 10000, 100000], kappa=kap)
    G = evaluate(L118, B118, K, "realistic", "be_counted", p, kappa=kap)["toffoli_per_grover_iteration"]["G"]; alpha = {}
    for a in (1.0, 0.9, 0.75, 0.6, 0.55, 0.5):
        alpha[str(a)] = crossover_N(G, p.t_toffoli_s, p.t_classical_s, 1, p.c_q, 1, 1.0, a)
    if "alpha" in m:
        b = m["alpha"]["best_structured"]; alpha["measured_best_structured"] = {"method": b["method"], "alpha": b["exponent"], "kappa": b["coefficient"],
                                                                               "N_star": crossover_N(G, p.t_toffoli_s, p.t_classical_s, 1, p.c_q, 1, b["coefficient"], b["exponent"])}
    payload["alpha_sensitivity_realistic"] = alpha
    head = payload["scenarios"]["realistic"].get("be_counted|calibrated") or payload["scenarios"]["realistic"]["be_counted|uncalibrated"]
    payload["headline"] = {"IEEE118_k3_realistic_be_prep": head, "classical_ahead": head["ratio_Tq_over_Tc"] > 1,
                           "statement": "Model estimate only: at IEEE-118 k=3 classical exhaustive search on one core is faster than the modelled fault-tolerant quantum search."
                                        if head["ratio_Tq_over_Tc"] > 1 else "Model estimate only: the modelled quantum time is below the classical time for these parameters."}
    d = ctx.exp_dir("E15"); payload["figures"] = _fig(payload, d)
    parts = [Part("resource_model_measured_inputs", "EXECUTED", kind="ESTIMATED_PARTIAL" if kap else "ESTIMATED", reason="")]
    for miss in m["missing"]: parts.append(Part(f"input[{miss}]", "NOT_RUN", reason=f"{miss} result unavailable; V2 placeholder kept with its provenance"))
    return ExpOutput(parts=parts, payload=payload, datasets_used=["ieee118"], figures=payload["figures"],
                     limitations=["[ESTIMATED] analytical model; no IEEE-scale circuit is synthesized; t_T, factory overhead and error-correction overhead remain bounds (V2 16.5).",
                                  "kappa_cal is from a toy-scale A2 with textbook synthesis; small_inverse uncalibrated; GE extrapolated.",
                                  "t_c is this machine's scalar-Python cascade time; an optimised classical implementation would be faster, moving N* further out."],
                     parameters={"L": L118, "B": B118, "k": K, "t_toffoli_s": TT})

# =============================================================================================== E16
def e16(config, ctx) -> ExpOutput:
    e3, e7, e11 = ctx.load_result("E3"), ctx.load_result("E7"), ctx.load_result("E11"); out = {}; parts = []
    if e7:
        ac = e7["payload"].get("ac", {}); rows = {k: v.get("F1_best_structured_le_0.1_sqrtN") for k, v in ac.items()}
        ev = [v for v in rows.values() if v is not None]
        out["F1"] = {**SP.F1, "per_table_ac": rows, "status": ("MET" if ev and all(ev) else "NOT MET") if ev else "NOT EVALUABLE",
                     "interpretation": "MET => the quantum-search motivation is empirically empty on these grids (V2 18.1)"}
        out["H-C1"] = e7["payload"].get("HC1")
        parts.append(Part("F1_from_E7", "EXECUTED", kind="MEASURED"))
    else:
        out["F1"] = {"status": "NOT EVALUABLE", "reason": "E7 result missing"}; parts.append(Part("F1_from_E7", "NOT_RUN", reason="E7 result missing"))
    if e3:
        o = e3["payload"]["overall"]; out["F2"] = {**SP.F2, "min_recall": o["min_recall"], "status": ("MET" if o["F2_recall_below_threshold_any"] else "NOT MET") if o["n_evaluable"] else "NOT EVALUABLE",
                                                   "per_table": {k: v["decision"] for k, v in e3["payload"]["E3a"].items()},
                                                   "interpretation": "MET => the DC predicate is the wrong oracle where recall < 0.9"}
        parts.append(Part("F2_from_E3", "EXECUTED", kind="MEASURED"))
    else:
        out["F2"] = {"status": "NOT EVALUABLE", "reason": "E3 result missing"}; parts.append(Part("F2_from_E3", "NOT_RUN", reason="E3 result missing"))
    if e11:
        f3 = e11["payload"]["F3"]; v = f3.get("F3_met_findings_are_rating_artefacts")
        out["F3"] = {**f3, "status": "NOT EVALUABLE" if v is None else ("MET" if v else "NOT MET"), "interpretation": "MET => the top-10 findings are artefacts of the rating rule"}
        parts.append(Part("F3_from_E11", "EXECUTED", kind="MEASURED"))
    else:
        out["F3"] = {"status": "NOT EVALUABLE", "reason": "E11 result missing"}; parts.append(Part("F3_from_E11", "NOT_RUN", reason="E11 result missing"))
    m3 = (e3 or {}).get("manifest_data_status")
    out["summary"] = {k: out[k]["status"] for k in ("F1", "F2", "F3")}
    return ExpOutput(parts=parts, payload=out, criteria=[SP.F1, SP.F2, SP.F3],
                     limitations=["Criteria and thresholds were registered in doomsday/experiments/specs.py before the experiments ran (git history)."])
