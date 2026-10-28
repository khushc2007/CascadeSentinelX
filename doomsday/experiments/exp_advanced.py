"""Phase 10: E9 (top-T cost), E10 (QAOA surrogate comparison a/b/c), E12 (fixed-point precision and truncation, V2 17.1).
Rules are read from specs (registered before execution). QAOA optimises a fitted SURROGATE (label everywhere); E9 is Tier B emulation."""
from __future__ import annotations
import math
from itertools import combinations
import numpy as np
from ..gridtwin.cascade import FP_INT_BITS
from ..gridtwin.dc import dc_power_flow
from ..gridtwin.islanding import grid_components
from ..qsearch.predicate import PredicateTable
from ..qsearch.qaoa import SubspaceQAOA, qiskit_circuit, sample
from ..qsearch.surrogate import QuadraticSurrogate, pair_set, r2
from ..qsearch.topt import exclusion_comparators, top_t, top_t_threshold
from ..resource.components import round_cost
from . import specs as SP
from .common import TableMissing, bp_cached, cfg_for, loglog_fit, qstats, tables_for
from .framework import ExpOutput, Part, accounting, data_status_for
from .ranking_metrics import spearman, tie_expanded_topT, topT_stability

# =============================================================================================== E9
def e9(config, ctx) -> ExpOutput:
    seeds = config["params"]["seeds"]; parts, payload = [], {"rule": SP.E9}
    for grid, k in SP.E9["tables"]:
        name = f"topT[{grid},k={k}]"
        try:
            tab = tables_for(ctx, grid, "dc", [k])
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        pt = PredicateTable.from_oracle(tab); out = {"N": pt.N, "table_construction_evals": pt.N}
        for variant, fn in (("exclusion_list_V2_literal", top_t), ("threshold_list", top_t_threshold)):
            rows = []
            for T in SP.E9["T"]:
                if T > pt.N: continue
                q, ok = [], 0
                for s in range(seeds):
                    r = fn(pt, T, np.random.default_rng(s)); q.append(r["quantum_oracle_calls"]); ok += r["correct_topT_values"]
                exp_c = sum(math.sqrt(pt.N / j) for j in range(1, T + 1))
                rows.append({"T": T, "quantum_calls_total": qstats(q), "correct_rate": ok / seeds, "over_sum_sqrt_N_over_j": float(np.mean(q)) / exp_c,
                             "over_2sqrtNT": float(np.mean(q)) / (2 * math.sqrt(pt.N * T)), "exclusion_comparators_coherent": exclusion_comparators(T, k),
                             "S_T": float(np.sort(pt.S)[::-1][T - 1])})
            fit = loglog_fit([(r["T"], r["quantum_calls_total"]["mean"]) for r in rows])
            out[variant] = {"rows": rows, "slope_in_T": fit, "tracks_sqrt_NT": (abs(fit["exponent"] - 0.5) <= 0.15) if fit else None}
        payload[f"{grid}_k{k}"] = out
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "EMULATED", dataset=grid))
    return ExpOutput(parts=parts, payload=payload, datasets_used=sorted({g for g, _ in SP.E9["tables"]}), seeds=list(range(seeds)),
                     accounting=accounting(quantum_oracle_calls_emulated="sum over the T rounds of sum(j+1)", classical_verification_calls="one per measurement (not tabulated here)",
                                           preprocessing_evaluations="table construction N per table (Tier B)"),
                     limitations=["Tier B emulation. Two schemes: V2's literal repeated Durr-Hoyer with an exclusion list, and the threshold-list scheme "
                                  "(specs.DEVIATIONS E9-variants); threshold-list also uses T initial classical samples.",
                                  "Ties: correctness is judged on values (any maximiser of a tied level is a valid answer)."], parameters={"seeds": seeds})

# =============================================================================================== E10
def _qaoa_metrics(qa: SubspaceQAOA, res_p: dict, S_true: np.ndarray, surr_vals: np.ndarray, rng, shots: int, T: int) -> dict:
    prob = res_p["prob"]; smp = sample(prob, shots, rng); uniq = np.unique(smp)
    order = uniq[np.argsort(-surr_vals[uniq], kind="stable")][:T]                     # top-T sampled by SURROGATE value
    true_vals = S_true[order]; Smax = float(S_true.max()); top1pct = set(np.argsort(-S_true, kind="stable")[: max(1, math.ceil(0.01 * len(S_true)))].tolist())
    t_true = set(tie_expanded_topT(S_true, 1).tolist()); s_opt = int(np.argmax(surr_vals))
    frac_top1 = len(set(order.tolist()) & top1pct) / len(order)
    return {"expected_surrogate": res_p["expected_surrogate"], "surrogate_optimum": float(surr_vals.max()),
            "p_surrogate_optimum": float(prob[s_opt]), "p_true_argmax_set": float(sum(prob[i] for i in t_true)),
            "best_verified_true_S": float(true_vals.max()), "approximation_ratio_true": float(true_vals.max() / Smax) if Smax > 0 else None,
            "top1_agreement": bool(int(order[0]) in t_true), "top1pct_overlap_of_topT": frac_top1, "enrichment_over_random": frac_top1 / 0.01,
            "error_i_optimizer_surrogate_gap": float(surr_vals.max() - surr_vals[order].max()), "verified_T": int(len(order)), "nfev_best": res_p["nfev_best"]}

def _run_qaoa(L, k, cost, seed, S_true=None, surr=None):
    qa = SubspaceQAOA(L, k, cost); res = qa.optimize(p_max=SP.E10["p_max"], starts=SP.E10["starts"], seed=seed); return qa, res

def e10(config, ctx) -> ExpOutput:
    E = SP.E10; parts, payload = [], {"rules": E, "label": "QAOA optimises a fitted quadratic SURROGATE objective, never S itself"}
    # ---- E10a planted quadratic (no grid data)
    P = E["planted"]; L, k = P["L"], P["k"]; rng = np.random.default_rng(P["seed"]); states = list(combinations(range(L), k)); N = len(states)
    h = rng.normal(0, 0.1, L); J = {pr: rng.normal(0, 0.1) for pr in combinations(range(L), 2)}; xs = tuple(sorted(rng.choice(L, k, replace=False).tolist()))
    for pr in combinations(xs, 2): J[pr] += 0.5                                     # planted bonus
    cost = np.array([h[list(s)].sum() + sum(J[pr] for pr in combinations(s, 2)) for s in states]); istar = states.index(xs)
    planted_unique = bool(np.sum(cost >= cost[istar] - 1e-12) == 1)
    qa, res = _run_qaoa(L, k, cost, 0); prng = np.random.default_rng(1); rows = {}
    for p, r in res.items():
        smp = sample(r["prob"], E["shots"], prng); rows[p] = {"P_xstar": float(r["prob"][istar]), "xstar_sampled": bool(np.any(smp == istar)), "expected_cost": r["expected_surrogate"],
                                                             "most_probable_is_xstar": bool(int(np.argmax(r["prob"])) == istar)}
    bestp = max(rows, key=lambda p: rows[p]["P_xstar"]); rec = rows[bestp]["xstar_sampled"] and rows[bestp]["P_xstar"] >= 10 / N
    payload["E10a_planted"] = {"L": L, "k": k, "N": N, "x_star": list(xs), "planted_unique_max": planted_unique, "per_p": rows, "best_p": bestp, "recovered": bool(rec),
                               "uniform_P": 1 / N}
    parts.append(Part("E10a_planted_quadratic", "EXECUTED", kind="NUMPY_STATEVECTOR"))
    # ---- E10b (k=2 exact surrogate) and E10c (k=3 surrogate gap) on IEEE-14
    grid = E["grid"]
    try:
        tabs = {kk: tables_for(ctx, grid, "dc", [kk]) for kk in (2, 3)}
    except TableMissing as e:
        parts.append(Part("E10b_E10c", "NOT_RUN", reason=str(e), dataset=grid)); tabs = None
    if tabs:
        feats = tabs[2].structure(); Lg = feats.L
        # E10b
        S2 = tabs[2].all_severities(); X2 = tabs[2].space.unrank_batch(np.arange(len(S2), dtype=np.int64))
        sur = QuadraticSurrogate(Lg, pair_set(Lg, mode="all"), ridge=E["ridge_k2"]).fit(X2, S2); sv = sur.predict(X2)
        qa, res = _run_qaoa(Lg, 2, sv, 0); mrng = np.random.default_rng(2)
        payload["E10b_k2_exact"] = {"N": len(S2), "fit": sur.fit_info, "R2_all": r2(S2, sv), "max_abs_fit_error": float(np.abs(S2 - sv).max()),
                                    "true_oracle_calls": len(S2) + E["T_verify"], "note": "exact fit needs all C(L,2) evaluations = brute force: no oracle-call advantage by construction",
                                    "classical_surrogate_optimum_true_S": float(S2[int(np.argmax(sv))]), "Smax": float(S2.max()),
                                    "per_p": {p: _qaoa_metrics(qa, r, S2, sv, mrng, E["shots"], E["T_verify"]) for p, r in res.items()}}
        # E10c
        S3 = tabs[3].all_severities(); N3 = len(S3); X3 = tabs[3].space.unrank_batch(np.arange(N3, dtype=np.int64)); pairs = pair_set(Lg, feats, mode="sparse")
        top1 = np.argsort(-S3, kind="stable")[: max(1, math.ceil(0.01 * N3))]; c_rows = {}
        for nt in E["n_train"]:
            trng = np.random.default_rng(100 + nt); tr = np.sort(trng.choice(N3, min(nt, N3), replace=False)); te = np.setdiff1d(np.arange(N3), tr)
            sur = QuadraticSurrogate(Lg, pairs, ridge=E["ridge_k3"]).fit(X3[tr], S3[tr]); sv = sur.predict(X3)
            te_top = np.intersect1d(te, top1)
            qa, res = _run_qaoa(Lg, 3, sv, 0); mrng = np.random.default_rng(3)
            per_p = {p: _qaoa_metrics(qa, r, S3, sv, mrng, E["shots"], E["T_verify"]) for p, r in res.items()}
            s_opt = int(np.argmax(sv))
            c_rows[nt] = {"fit": sur.fit_info, "n_pairs": len(pairs), "heldout_R2": r2(S3[te], sv[te]), "heldout_spearman": spearman(S3[te], sv[te]),
                          "heldout_top1pct_R2": r2(S3[te_top], sv[te_top]) if len(te_top) > 2 else None,
                          "heldout_top1pct_spearman": spearman(S3[te_top], sv[te_top]) if len(te_top) > 2 else None, "n_heldout_top1pct": int(len(te_top)),
                          "true_oracle_calls": int(len(tr)) + E["T_verify"], "brute_force_calls": N3,
                          "classical_surrogate_optimum_true_S": float(S3[s_opt]), "error_ii_model_gap_true": float(S3.max() - S3[s_opt]), "Smax": float(S3.max()),
                          "per_p": per_p}
        payload["E10c_k3_gap"] = {"N": N3, "pairs_mode": "sparse (neighbour / parallel / top-2L |LODF|)", "rows": c_rows}
        parts.append(Part("E10b_k2_exact_surrogate", "EXECUTED", data_status_for(grid), "NUMPY_STATEVECTOR", dataset=grid))
        parts.append(Part("E10c_k3_surrogate_gap", "EXECUTED", data_status_for(grid), "NUMPY_STATEVECTOR", dataset=grid))
        # ---- Aer cross-check (L <= 12 shortlist) + depth / 2q gates per layer
        A = E["aer_crosscheck"]
        try:
            from qiskit import transpile
            from qiskit_aer import AerSimulator
            cand = A["candidates"]; kk = A["k"]; Ls = len(cand); loc = list(combinations(range(Ls), kk))
            gl = np.array([[cand[i] for i in s] for s in loc], dtype=np.int64); Sv = tabs[2].severity_batch(gl)
            sur = QuadraticSurrogate(Ls, pair_set(Ls, mode="all"), ridge=E["ridge_k2"]).fit(np.array(loc), Sv); cv = sur.predict(np.array(loc))
            qa = SubspaceQAOA(Ls, kk, cv); res = qa.optimize(p_max=A["p"], starts=4, seed=0); r = res[A["p"]]
            qc = qiskit_circuit(Ls, kk, sur.ising(), r["gammas"], r["betas"]); tq = transpile(qc, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=0)
            tq.save_statevector(); sv_ = np.asarray(AerSimulator(method="statevector").run(tq).result().get_statevector())
            masks = [sum(1 << q for q in s) for s in loc]; pa = np.abs(sv_[masks]) ** 2; diff = float(np.abs(pa - r["prob"]).max())
            one = qiskit_circuit(Ls, kk, sur.ising(), [0.3], [0.2]); zero = qiskit_circuit(Ls, kk, sur.ising(), [], [])
            t1 = transpile(one, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=0); t0 = transpile(zero, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=0)
            payload["aer_crosscheck"] = {"candidates": cand, "k": kk, "L": Ls, "N": len(loc), "p": A["p"], "max_abs_prob_diff_subspace_vs_aer": diff, "pass": diff <= A["tol"],
                                         "leak_outside_weight_k": float(1 - pa.sum()), "per_layer_depth": t1.depth() - t0.depth(),
                                         "per_layer_cx": int(t1.count_ops().get("cx", 0) - t0.count_ops().get("cx", 0)), "dicke_prep_cx": int(t0.count_ops().get("cx", 0))}
            parts.append(Part("E10_aer_crosscheck_L10", "EXECUTED", data_status_for(grid), "AER_SIMULATED", dataset=grid))
        except ImportError as e:
            parts.append(Part("E10_aer_crosscheck_L10", "NOT_RUN", reason=f"qiskit unavailable: {e}"))
    return ExpOutput(parts=parts, payload=payload, datasets_used=[grid], seeds=[0, 1, 2, 3],
                     accounting=accounting(classical_function_evaluations="true-oracle calls = n_train + T (V2 14.3 metric 4)", notes="QAOA objective evaluations are surrogate-only (no oracle calls)"),
                     limitations=["QAOA is simulated exactly in the weight-k subspace (NumPy); no noise, no hardware.",
                                  "Every QAOA quantity refers to the SURROGATE objective; true-S quantities come from verifying sampled strings with the true oracle.",
                                  "No proven speedup; included as a near-term hybrid comparison (V2 14)."],
                     parameters={k_: v for k_, v in E.items() if k_ != "planted"})

# =============================================================================================== E12
def _flow_and_borderline(bp, cfg, k, bits, n=300, seed=5):
    """Round-0 post-outage DC flows on non-islanding random k-sets: float vs Q-format; borderline overload comparisons within the
    quantisation error of the trip threshold; cond(I - Phi_KK)."""
    from ..gridtwin.cascade import quantize_pu
    g = bp.grid; rng = np.random.default_rng(seed); L = g.n_branch; base = g.base_mva; pin = bp.dc_injections_mw; tf = cfg.cascade.trip_factor
    from ..gridtwin.dc import DCSensitivities
    phi = DCSensitivities(g, pin).Phi
    errs, rel_border, conds, used = {b: [] for b in bits}, {b: 0 for b in bits}, [], 0; total_cmp = 0
    tries = 0
    while used < n and tries < 20 * n:
        tries += 1; K = rng.choice(L, k, replace=False); s = g.br_status.copy(); s[K] = 0
        if grid_components(g, s)[0] != 1: continue
        used += 1; f = dc_power_flow(g, pin, status=s).flow_mw; on = s > 0; u = np.abs(f[on]) / g.rating_dc[on]; total_cmp += int(on.sum())
        M = np.eye(k) - phi[np.ix_(K, K)]; conds.append(float(np.linalg.cond(M)))
        for b in bits:
            pq = quantize_pu(pin / base, b) * base; fq = quantize_pu(dc_power_flow(g, pq, status=s).flow_mw / base, b) * base
            errs[b].append(float(np.abs(fq - f)[on].max() / base))
            lsb = 2.0 ** -(b - FP_INT_BITS) * base; rel_border[b] += int(np.sum(np.abs(np.abs(f[on]) - tf * g.rating_dc[on]) < lsb))
    return {"n_sets": used, "max_flow_error_pu": {b: max(errs[b]) for b in bits}, "mean_of_max_flow_error_pu": {b: float(np.mean(errs[b])) for b in bits},
            "borderline_fraction": {b: rel_border[b] / total_cmp for b in bits}, "cond_I_minus_PhiKK": qstats(conds) if conds else None}

def e12(config, ctx) -> ExpOutput:
    bits = SP.E12_BITS; parts, payload = [], {"bits": bits, "rule": SP.E12_RULE, "Q_format": f"{FP_INT_BITS} integer bits (incl. sign), b-{FP_INT_BITS} fractional, per unit on base MVA"}
    e2 = ctx.load_result("E2"); minima = {}
    for grid, k in SP.E12_GRID_K.items():
        name = f"fixed_point[{grid},k={k}]"
        try:
            base = tables_for(ctx, grid, "dc", [k])
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        S = base.all_severities(); hi = S >= SP.TAU - SP.BAND; rows = {}
        for b in bits:
            Sb = tables_for(ctx, grid, "dc", [k], cfg=cfg_for(grid, {"numerics": {"fixed_point_bits": b}})).all_severities(); hb = Sb >= SP.TAU - SP.BAND
            st = topT_stability(S, Sb); t10_equal = set(tie_expanded_topT(S, 10).tolist()) == set(tie_expanded_topT(Sb, 10).tolist())
            rows[b] = {"max_severity_error": float(np.abs(Sb - S).max()), "mean_severity_error": float(np.abs(Sb - S).mean()), "label_agreement": float((hb == hi).mean()),
                       "label_flips": int((hb != hi).sum()), "top10_jaccard": st["top10"]["tie_expanded_jaccard"], "top10_equal": bool(t10_equal),
                       "top100_jaccard": st["top100"].get("tie_expanded_jaccard"), "spearman": st["spearman"],
                       "passes": bool((hb == hi).all() and t10_equal)}
        passing = [b for b in bits if rows[b]["passes"] and all(rows[c]["passes"] for c in bits if c > b)]
        minima[grid] = min(passing) if passing else None
        cfg = cfg_for(grid); bp = bp_cached(grid, cfg)
        diag = _flow_and_borderline(bp, cfg, k, bits)
        trunc = {}
        R = None
        if e2:
            v = e2["payload"].get(f"{grid}_k{k}") or e2["payload"].get(f"{grid}_k3")
            R = int(math.ceil(v["rounds_on_S_gt_0"]["p95"])) if v and v.get("rounds_on_S_gt_0") else None
        if R:
            St = tables_for(ctx, grid, "dc", [k], cfg=cfg_for(grid, {"cascade": {"max_rounds": R}})).all_severities()
            trunc = {"R_p95_from_E2": R, "max_severity_error": float(np.abs(St - S).max()), "label_flips": int(((St >= SP.TAU - SP.BAND) != hi).sum()),
                     "top10_jaccard": topT_stability(S, St)["top10"]["tie_expanded_jaccard"]}
        payload[f"{grid}_k{k}"] = {"per_b": rows, "min_passing_b": minima[grid], "flow_and_borderline": diag, "truncation_R_float": trunc or "E2 result not available"}
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    vals = [v for v in minima.values()]
    payload["min_passing_b_overall"] = (max(vals) if vals and all(v is not None for v in vals) else None)
    payload["toffoli_per_round_ieee118_realistic"] = {b: round_cost(186, 118, 9, b, 20, 19.0, "realistic") for b in bits}
    payload["note"] = "Q-format emulation of input/output quantisation of the DC solve (cascade.quantize_pu); not a bit-exact reversible-arithmetic model"
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(SP.E12_GRID_K), criteria=[SP.E12_RULE],
                     limitations=["IEEE-118 at k=2 (specs.DEVIATIONS E12-118).", "Quantisation applied to injections, flows and ratings of each DC solve."],
                     parameters={"bits": bits})
