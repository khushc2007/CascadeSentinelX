"""Scenario evaluation (V2 16.3) with TWO Dicke-preparation scenarios reported side by side, and with quantum oracle calls, classical
verifications and preprocessing kept as DISTINCT quantities. Everything here is [ESTIMATED]/[DESIGN-STAGE]; calibrated = False always."""
from __future__ import annotations
from math import comb, inf, log10, sqrt
from . import calibration
from .components import SCENARIOS, grover_iteration_cost, oracle_compute_cost, round_components
from .crossover import classical_time, crossover_N, k_bracket, quantum_time
from .params import ModelParams
from .components import once_only_cost
from .prep import dicke_prep_cost_be, dicke_prep_cost_tree, dicke_prep_cost_v2
from .qubits import logical_qubits, physical_qubits

PREPS = ("v2_assumed", "tree_counted")
PREPS_ALL = PREPS + ("be_counted",)          # (Phase 8/11) BE construction verified; opt-in so Phase 6 outputs are unchanged
PREP_NOTE = {"v2_assumed": "ASSUMPTION: V2 11.3 theoretical C_D = k*L*c_rot (Baertschi-Eidenbenz O(kL)); that construction has NOT been reproduced here",
             "tree_counted": "operation counts of the IMPLEMENTED multiplexed-RY tree (exact count); Toffoli-equivalent conversion is an ESTIMATE made here. "
                             "Not equivalent to the V2 assumption: the two must never be mixed or compared as the 'same' cost."}

def evaluate(L: int, B: int, k: int, scenario: str = "realistic", prep: str = "v2_assumed", p: ModelParams | None = None, M: int = 1,
             kappa: dict | None = None, kappa_source: str = "") -> dict:
    """kappa (Phase 11, optional): per-primitive kappa_cal from E14; None (default) = the uncalibrated V2 formulas exactly as in Phase 6."""
    p = p or ModelParams()
    if scenario not in SCENARIOS or prep not in PREPS_ALL: raise ValueError((scenario, prep))
    for name, v in (("L", L), ("B", B), ("k", k), ("M", M)):
        if isinstance(v, bool) or not isinstance(v, int): raise ValueError(f"{name} must be an integer, got {v!r}")
    if L < 1 or B < 1 or not 1 <= k <= L: raise ValueError(f"need L,B >= 1 and 1 <= k <= L, got L={L}, B={B}, k={k}")
    if not 1 <= M <= comb(L, k): raise ValueError(f"need 1 <= M <= N={comb(L, k)}, got M={M}")
    keff = p.keff(k); N = comb(L, k)
    Ef = oracle_compute_cost(L, B, k, p.R, keff, p.b, p.D, p.c_lab, scenario); comp_prov = None
    if kappa:
        scaled, comp_prov = calibration.apply(round_components(L, B, keff, p.b, p.D, p.c_lab, scenario), kappa)
        Ef = p.R * sum(scaled.values()) + once_only_cost(L, k, p.b)
    if prep == "v2_assumed": CD, prep_detail = dicke_prep_cost_v2(L, k, p.c_rot), {"toffoli_equivalents": dicke_prep_cost_v2(L, k, p.c_rot)}
    elif prep == "be_counted": prep_detail = dicke_prep_cost_be(L, k, p.c_rot, p.and_overhead); CD = prep_detail["toffoli_equivalents"]
    else: prep_detail = dicke_prep_cost_tree(L, k, p.c_rot, p.and_overhead); CD = prep_detail["toffoli_equivalents"]
    g = grover_iteration_cost(Ef, CD, L, p.uncompute_factor); G = g["G"]
    Q = p.c_q * sqrt(N / M)                                                   # QUANTUM oracle calls (Grover iterations + marking checks)
    Tq_oracle = quantum_time(N, G, p.t_toffoli_s, p.c_q, M, p.Pq)
    Q_stop = Q + p.c_tail * sqrt(N)                                           # discovery + certified-stop tail (only if c_tail > 0)
    V = p.verif_per_qcall * Q; T_verif = V * p.t_classical_s                  # CLASSICAL verifications, separate cost class
    Tc = classical_time(N, p.t_classical_s, p.P, p.kappa, p.alpha)
    Nstar = crossover_N(G, p.t_toffoli_s, p.t_classical_s, p.P, p.c_q, p.Pq, p.kappa, p.alpha, M)
    lq = logical_qubits(L, B, keff, p.b, p.R, scenario, search_register=L)
    if prep == "tree_counted":
        anc = prep_detail["ancillas_for_and_ladder"]; lq["parts"]["tree_and_ladder_ancillas"] = anc; lq["total"] += anc
    volume = Q * G
    phys_v2 = physical_qubits(lq["total"], volume, p.p_ratio, p.logical_budget_eps, p.factory_routing_overhead)
    phys_cons = physical_qubits(lq["total"], volume, p.p_ratio, p.logical_budget_eps, p.factory_routing_overhead, conservative=True)
    return {
        "evidence": "[ESTIMATED] analytical resource model; parameters carry their own provenance ([DESIGN-STAGE] unless stated); NOT a synthesized-circuit count",
        **{"calibrated": "partial" if kappa else False},
        "calibration": calibration.calibrated_status(kappa, kappa_source) if kappa else calibration.status(), "component_calibration": comp_prov,
        "inputs": {"L": L, "B": B, "k": k, "N": N, "M": M, "scenario": scenario, "prep_scenario": prep, "k_eff": keff, "params": p.to_dict()},
        "prep_scenario_note": PREP_NOTE.get(prep, "Baertschi-Eidenbenz circuit verified in Phase 8; Toffoli-equivalent conversion is an ESTIMATE"),
        "warnings": ([] if prep in ("v2_assumed", "be_counted") else ["tree_counted: Baertschi-Eidenbenz construction not reproduced; do not equate with the V2 assumption"]),
        "toffoli_per_grover_iteration": {"G": G, **g["parts"], "oracle_compute_E_f": Ef, "oracle_components_per_round": round_components(L, B, keff, p.b, p.D, p.c_lab, scenario),
                                          "dicke_prep_C_D": CD, "dicke_prep_detail": prep_detail},
        "separate_costs": {
            "quantum_oracle_calls_Q": Q, "quantum_oracle_time_s": Tq_oracle,
            "quantum_oracle_calls_to_certified_stop": Q_stop if p.c_tail > 0 else None, "quantum_oracle_time_to_certified_stop_s": (Q_stop * G * p.t_toffoli_s / sqrt(p.Pq)) if p.c_tail > 0 else None,
            "classical_verifications_V": V, "classical_verification_time_s": T_verif,
            "tier_B_emulation_preprocessing": {"classical_evaluations": N, "time_s": N * p.t_classical_s,
                                               "note": "needed ONLY to emulate (build the predicate table); a coherent Tier C run has no such table, and it is never part of the quantum cost"},
            "classical_exhaustive_evaluations": p.kappa * N ** p.alpha, "classical_time_s": Tc},
        "totals": {"quantum_total_time_s": Tq_oracle + T_verif, "verification_fraction_of_quantum": T_verif / (Tq_oracle + T_verif),
                   "quantum_faster_than_classical": (Tq_oracle + T_verif) < Tc, "ratio_Tq_over_Tc": (Tq_oracle + T_verif) / Tc},
        "crossover": {"N_star": Nstar, "k_bracket_at_N_star": k_bracket(L, Nstar) if Nstar != inf else None,
                      "note": "read at this k with this G; for a different k the self-consistent crossover must use G(k) (see k_star)"},
        "logical_qubits": lq,
        "physical_qubits_estimate": {"v2_volume_convention": phys_v2, "conservative_volume_x_logical": phys_cons, "toffoli_volume_Q_times_G": volume,
                                     "quality": "bound only: factory footprint, routing and T-count accounting not modelled in detail"}}

def sweep_k(L: int, B: int, ks, scenario: str, prep: str, p: ModelParams | None = None, kappa: dict | None = None) -> list:
    out = []
    for k in ks:
        r = evaluate(L, B, k, scenario, prep, p, kappa=kappa); out.append({"k": k, "N": r["inputs"]["N"], "G": r["toffoli_per_grover_iteration"]["G"], "Tq_s": r["totals"]["quantum_total_time_s"],
                                                              "Tc_s": r["separate_costs"]["classical_time_s"], "ratio": r["totals"]["ratio_Tq_over_Tc"], "N_star": r["crossover"]["N_star"],
                                                              "quantum_faster": r["totals"]["quantum_faster_than_classical"]})
    return out

def k_star(L: int, B: int, scenario: str, prep: str, p: ModelParams | None = None, kmax: int | None = None, kappa: dict | None = None):
    """Smallest k whose OWN G(k) (keff grows with k) already puts the quantum model ahead of classical exhaustive search; None if none up to kmax."""
    kmax = kmax or min(L, 60)
    for row in sweep_k(L, B, range(1, kmax + 1), scenario, prep, p, kappa):
        if row["quantum_faster"]: return row["k"]
    return None

def tornado(L: int, B: int, k: int, scenario: str, prep: str, base: ModelParams, ranges: dict, kappa: dict | None = None) -> list:
    """One-at-a-time variation of N* (V2 17). ranges: {param: [low, high]}; a 'prep' entry may list the two prep scenarios."""
    ev = lambda *a, **kw: evaluate(*a, **kw, kappa=kappa)
    n0 = ev(L, B, k, scenario, prep, base)["crossover"]["N_star"]; rows = []
    for name, vals in ranges.items():
        res = []
        for v in vals:
            if name == "prep": res.append(ev(L, B, k, scenario, v, base)["crossover"]["N_star"])
            elif name == "scenario": res.append(ev(L, B, k, v, prep, base)["crossover"]["N_star"])
            else: res.append(ev(L, B, k, scenario, prep, base.with_(**{name: v}))["crossover"]["N_star"])
        lo, hi = min(res), max(res); rows.append({"param": name, "values": list(vals), "N_star": res, "log10_swing": log10(hi) - log10(lo) if lo > 0 and hi != inf else None})
    return {"baseline_N_star": n0, "rows": sorted(rows, key=lambda r: -(r["log10_swing"] or 0))}

def heatmap_N_star(L: int, B: int, k: int, scenario: str, prep: str, base: ModelParams, tT_values, P_values, kappa: dict | None = None) -> dict:
    Z = [[evaluate(L, B, k, scenario, prep, base.with_(t_toffoli_s=t, P=P), kappa=kappa)["crossover"]["N_star"] for t in tT_values] for P in P_values]
    return {"tT_s": list(tT_values), "P": list(P_values), "N_star": Z}
