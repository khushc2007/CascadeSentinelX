"""E6 (Tier B Durr-Hoyer scaling), E7 (classical comparison, V2 15.2 protocol), E8 (threshold regime map). Accounting classes are never merged:
quantum oracle calls (emulated, ideal), classical verifications, classical unique evaluations and table construction are separate keys."""
from __future__ import annotations
import math, time
import numpy as np
from ..classical import STOCHASTIC, classical_search
from ..qsearch.bbht import bbht_search
from ..qsearch.dh_gas import DH_BOUND, durr_hoyer
from ..qsearch.predicate import PredicateTable
from . import specs as SP
from .benchmark import reference, run_one
from .common import TableMissing, boot_ci, loglog_fit, qstats, tables_for
from .framework import ExpOutput, Part, accounting, data_status_for

TABLES_DC = [("ieee14", 2), ("ieee14", 3), ("ieee14", 4), ("ieee30", 2), ("ieee30", 3), ("ieee30", 4), ("ieee118", 2), ("ieee118", 3)]

def _load(ctx, grid, k, fid="dc"):
    """Tables for every cardinality 1..k (beam search queries partial sets; DC loads 1..k already, AC needs it explicitly)."""
    return tables_for(ctx, grid, fid, [1, k] if fid == "ac" else [k])

# =============================================================================================== E6
def e6(config, ctx) -> ExpOutput:
    seeds = config["params"]["seeds"]; parts, rows = [], []
    for grid, k in TABLES_DC:
        name = f"tierB_DH[{grid},k={k}]"
        try:
            tab = _load(ctx, grid, k)
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        pt = PredicateTable.from_oracle(tab); N = pt.N; sq = math.sqrt(N); M = int((pt.S >= pt.Smax - SP.BAND).sum()); row = {"grid": grid, "k": k, "N": N, "Smax": pt.Smax, "M_at_Smax": M, "sqrtN": sq}
        for variant in ("y0_zero", "y0_heuristic"):
            disc, tot, ok, ver, heur = [], [], 0, [], []
            for s in range(seeds):
                y0 = 0.0
                if variant == "y0_heuristic":                     # classical heuristic warm start; its evaluations are reported separately
                    h = classical_search(tab, "hillclimb", budget=math.ceil(sq), seed=s, n_starts=1); y0 = float(h.best_severity); heur.append(h.oracle_calls)
                    if y0 >= pt.Smax - SP.BAND: y0 = float(np.nextafter(y0, -1)) - 2 * SP.BAND   # keep the maximiser markable; DH still must find it
                r = durr_hoyer(tab, seed=s, y0=y0, grid=grid, pt=pt); acc = r.aux["accounting"]
                tot.append(acc["quantum_oracle_calls"]); ver.append(acc["classical_verifications"])
                if r.found_target: ok += 1; disc.append(r.aux["discovery_quantum_calls"])
            row[variant] = {"success_rate": ok / seeds, "discovery_quantum_calls": qstats(disc), "discovery_mean_CI95": boot_ci(disc),
                            "c_hat_discovery_over_sqrtN": (float(np.mean(disc)) / sq) if disc else None,
                            "c_q_discovery_over_sqrt_N_over_M": (float(np.mean(disc)) / math.sqrt(N / M)) if disc else None,
                            "certified_stop_quantum_calls": qstats(tot), "certified_stop_over_sqrtN": float(np.mean(tot)) / sq, "classical_verifications": qstats(ver),
                            "heuristic_classical_evaluations": qstats(heur) if heur else None}
        row["dh_proven_bound"] = DH_BOUND(N); row["table_construction_evals"] = N; rows.append(row)
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "EMULATED", dataset=grid))
    fits = {}
    for v in ("y0_zero", "y0_heuristic"):
        pts = [(r["N"], r[v]["discovery_quantum_calls"]["mean"]) for r in rows if r[v]["discovery_quantum_calls"]]
        fits[v] = {"all_tables": loglog_fit(pts), **{g: loglog_fit([(r["N"], r[v]["discovery_quantum_calls"]["mean"]) for r in rows if r["grid"] == g and r[v]["discovery_quantum_calls"]]) for g in ("ieee14", "ieee30", "ieee118")}}
        cert = [(r["N"], r[v]["certified_stop_quantum_calls"]["mean"]) for r in rows]
        fits[v]["certified_stop_all_tables"] = loglog_fit(cert)
    cq = [r["y0_zero"]["c_q_discovery_over_sqrt_N_over_M"] for r in rows if r["y0_zero"]["c_q_discovery_over_sqrt_N_over_M"]]
    payload = {"rows": rows, "loglog_fits": fits, "hypothesis": {"slope": 0.5, "c_below": 22.5},
               "resource_inputs": {"c_q_mean_over_tables": float(np.mean(cq)) if cq else None, "c_q_p95_over_tables": float(np.percentile(cq, 95)) if cq else None,
                                   "c_tail_certified_minus_discovery_over_sqrtN": float(np.mean([(r["y0_zero"]["certified_stop_quantum_calls"]["mean"] - r["y0_zero"]["discovery_quantum_calls"]["mean"]) / r["sqrtN"] for r in rows if r["y0_zero"]["discovery_quantum_calls"]])) if rows else None}}
    return ExpOutput(parts=parts, payload=payload, datasets_used=sorted({g for g, _ in TABLES_DC}), seeds=list(range(seeds)),
                     accounting=accounting(quantum_oracle_calls_emulated="per row: discovery and certified-stop quantum calls (sum j+1)", classical_verification_calls="per row",
                                           preprocessing_evaluations="table_construction_evals = N per table (Tier B needs the predicate table; never part of the quantum count)",
                                           classical_function_evaluations="y0_heuristic: hill-climb evaluations reported separately", notes="never summed"),
                     limitations=["Tier B is an exact classical emulation of ideal amplitude amplification; not a quantum runtime, no noise, no oracle cost.",
                                  "c_q here is per sqrt(N/M) with M = number of maximisers (ties)."],
                     parameters={"seeds": seeds, "lambda": 1.2, "patience": 3})

# =============================================================================================== E7
def _budget(N):
    return math.ceil(0.5 * N) if N <= SP.E7_BUDGET["small_N"] else math.ceil(50 * math.sqrt(N))

def _suite_for(L, tuned):
    pools = [m for m in (8, 12, 16) if m < L] if L <= 20 else [m for m in (20, 40, 60) if m < L]
    s = [("brute", {}), ("random", {}), ("hillclimb", tuned["hillclimb"]), ("beam", {"width": 5}), ("beam", {"width": 20}), ("beam", {"width": 100}),
         ("sa", tuned["sa"]), ("ga", tuned["ga"]), *[("lodf_pool", {"m": m}) for m in pools], ("ml_screen", tuned["ml_screen"]),
         ("milp", {"n_solutions": 5}), ("bnb", {"theta": 0.5}), ("bnb", {"theta": 0.8})]
    return s

GRID_TUNE = {"hillclimb": [{"n_starts": 3}, {"n_starts": 5}, {"n_starts": 10}], "sa": [{"T0": 0.01}, {"T0": 0.05}, {"T0": 0.2}],
             "ga": [{"pop": 20}, {"pop": 40}, {"pop": 80}], "ml_screen": [{"n_train_frac": 0.02, "T_frac": 0.02}, {"n_train_frac": 0.05, "T_frac": 0.04}, {"n_train_frac": 0.08, "T_frac": 0.04}]}

def _ml_params(p, N):
    if "n_train_frac" in p: return {"n_train": max(20, math.ceil(p["n_train_frac"] * N)), "T": max(5, math.ceil(p["T_frac"] * N))}
    return p

def _tune(ctx, seeds):
    grid, k = SP.E7_TUNING["held_out"]; tab = _load(ctx, grid, k); ref = reference(tab); N = ref["N"]; res = {}
    for m, grid_ in GRID_TUNE.items():
        scores = []
        for p in grid_:
            rs = [run_one(tab, m, _ml_params(p, N), s, _budget(N), grid, ref) for s in range(seeds)]
            d = [r["discovery_calls"] for r in rs if r["discovery_calls"] is not None]; sr = np.mean([r["success"] for r in rs])
            scores.append({"params": p, "success_rate": float(sr), "mean_discovery": float(np.mean(d)) if d else None})
        best = sorted(scores, key=lambda z: (-(z["success_rate"]), z["mean_discovery"] if z["mean_discovery"] is not None else 1e18))[0]
        res[m] = {"grid": scores, "chosen": best["params"]}
    return res

def _agg(rows, N):
    out = {}
    for r in rows:
        key = f"{r['algorithm']}|{r['params']}"; out.setdefault(key, []).append(r)
    agg = {}
    for key, rs in out.items():
        d = [r["discovery_calls"] for r in rs if r["discovery_calls"] is not None]
        agg[key] = {"algorithm": rs[0]["algorithm"], "params": rs[0]["params"], "n_runs": len(rs), "success_rate": float(np.mean([r["success"] for r in rs])),
                    "discovery_calls": qstats(d), "discovery_over_sqrtN": (float(np.mean(d)) / math.sqrt(N)) if d else None,
                    "oracle_calls_mean": float(np.mean([r["oracle_calls"] for r in rs])), "certified_stop_calls": rs[0]["certified_stop_calls"],
                    "search_runtime_s_mean": float(np.mean([r["runtime_s"] for r in rs])), "best_severity_mean": float(np.mean([r["best_severity"] for r in rs])),
                    "coverage_top10_mean": float(np.mean([r.get("coverage_top10", np.nan) for r in rs])), "coverage_top100_mean": float(np.mean([r.get("coverage_top100", np.nan) for r in rs])),
                    "calls_to_within_1pct_mean": (float(np.mean([r["calls_to_within_1pct"] for r in rs if r["calls_to_within_1pct"] is not None])) if any(r["calls_to_within_1pct"] is not None for r in rs) else None),
                    "label": rs[0]["label"], "exact": rs[0]["exact"]}
    return agg

def e7(config, ctx) -> ExpOutput:
    seeds, tseeds, ac_seeds = config["params"]["seeds"], config["params"]["tuning_seeds"], config["params"]["ac_seeds"]; parts, payload = [], {"budget_rule": SP.E7_BUDGET}
    t0 = time.perf_counter(); tuning = _tune(ctx, tseeds); payload["tuning"] = {"held_out": SP.E7_TUNING, "result": tuning, "runtime_s": time.perf_counter() - t0}
    tuned = {m: v["chosen"] for m, v in tuning.items()}; payload["dc"] = {}; payload["ac"] = {}
    e6 = ctx.load_result("E6"); chat = {(r["grid"], r["k"]): r["y0_zero"]["c_hat_discovery_over_sqrtN"] for r in (e6["payload"]["rows"] if e6 else [])}
    e1 = ctx.load_result("E1"); tc = (e1["payload"].get("t_c_ms_for_resource_model", {}) if e1 else {})
    for fid, tables, ns in (("dc", [t for t in TABLES_DC if t != SP.E7_TUNING["held_out"]], seeds),
                            ("ac", [("ieee14", 2), ("ieee14", 3), ("ieee14", 4), ("ieee30", 3), ("ieee118", 2)], ac_seeds)):
        for grid, k in tables:
            name = f"classical_{fid}[{grid},k={k}]"
            try:
                tab = _load(ctx, grid, k, fid)
            except TableMissing as e:
                parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
            ref = reference(tab); N = ref["N"]; rows = []
            for m, p in _suite_for(tab.space.L, tuned):
                for s in (range(ns) if m in STOCHASTIC else [0]):
                    rows.append(run_one(tab, m, _ml_params(p, N) if m == "ml_screen" else p, s, None if m in ("brute", "milp") else _budget(N), grid, ref))
            agg = _agg(rows, N); t_ms = tc.get(grid, {}).get(f"{fid}_mean_random")
            for a in agg.values():
                a["estimated_wall_clock_s_incl_oracle"] = (a["oracle_calls_mean"] * t_ms / 1e3) if t_ms else None
            struct = [a for a in agg.values() if a["algorithm"] in SP.F1["structured_methods"] and a["discovery_calls"] and a["success_rate"] > 0]
            best = min(struct, key=lambda a: a["discovery_calls"]["mean"]) if struct else None
            c = chat.get((grid, k)) if fid == "dc" else None
            payload[fid][f"{grid}_k{k}"] = {"N": N, "Smax": ref["Smax"], "M_at_Smax": ref["M_at_Smax"], "budget": _budget(N), "aggregate": agg,
                                            "best_structured": {"method": f"{best['algorithm']}|{best['params']}", "mean_discovery": best["discovery_calls"]["mean"], "success_rate": best["success_rate"]} if best else None,
                                            "c_hat_E6": c, "c_hat_sqrtN": (c * math.sqrt(N)) if c else None, "dh_bound": DH_BOUND(N),
                                            "HC1_best_structured_below_c_sqrtN": (best["discovery_calls"]["mean"] < c * math.sqrt(N)) if (best and c) else None,
                                            "F1_best_structured_le_0.1_sqrtN": (best["discovery_calls"]["mean"] <= SP.F1["much_less_than_factor"] * math.sqrt(N)) if best else None,
                                            "t_c_ms_used_for_wall_clock_estimate": t_ms}
            parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    alphas = {}
    for key in {k for v in payload["dc"].values() for k in v["aggregate"]}:
        pts = [(v["N"], v["aggregate"][key]["discovery_calls"]["mean"]) for v in payload["dc"].values() if key in v["aggregate"] and v["aggregate"][key]["discovery_calls"] and v["aggregate"][key]["success_rate"] >= 0.5]
        alphas[key] = loglog_fit(pts)
    payload["alpha_fits_dc"] = alphas
    hc = [v["HC1_best_structured_below_c_sqrtN"] for v in payload["dc"].values() if v["HC1_best_structured_below_c_sqrtN"] is not None]
    payload["HC1"] = {**SP.HC1, "pairs_evaluated": len(hc), "pairs_true": int(sum(hc)), "holds": (sum(hc) / len(hc) > SP.HC1["most"]) if hc else None}
    return ExpOutput(parts=parts, payload=payload, datasets_used=["ieee14", "ieee30", "ieee118"], seeds=list(range(seeds)),
                     accounting=accounting(classical_function_evaluations="unique (k,set) evaluations per run (V2 15.2)", notes="MILP: solver calls + re-evaluations; ML: n_train + T"),
                     limitations=["Search runs on truth-table oracles: runtime_s excludes the oracle; estimated_wall_clock adds unique evaluations x E1 mean t_c (derived, machine-specific).",
                                  "Hyper-parameters tuned once on the held-out pair (IEEE-30, k=2, DC), excluded from comparison tables.",
                                  f"Budget rule: {SP.E7_BUDGET['rule']}."],
                     parameters={"seeds": seeds, "ac_seeds": ac_seeds, "tuning_seeds": tseeds})

# =============================================================================================== E8
def e8(config, ctx) -> ExpOutput:
    seeds = config["params"]["seeds"]; parts, payload = [], {}
    for grid, k in (("ieee14", 3), ("ieee30", 3), ("ieee118", 3)):
        name = f"threshold_map[{grid},k={k}]"
        try:
            tab = _load(ctx, grid, k)
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        pt = PredicateTable.from_oracle(tab); S = pt.S; N = pt.N; vals = np.unique(S[S > SP.BAND])
        taus = sorted(set([float(t) for t in np.quantile(vals, np.linspace(0, 1, 16))] + [t for t in (0.05, 0.1, 0.2, 0.3, 0.5) if t <= S.max()]))
        rows = []
        for tau in taus:
            ms = pt.marked_ge(tau); M = ms.M
            calls, succ = [], 0
            for s in range(seeds):
                r = bbht_search(ms, lambda x: pt.verify_ge(x, tau), np.random.default_rng(s))
                if r["found"]: succ += 1; calls.append(r["counter"].quantum_oracle_calls)
            rand_exp = (N + 1) / (M + 1)
            rows.append({"tau": tau, "M": M, "M_over_N": M / N, "bbht_quantum_calls": qstats(calls), "bbht_success_rate": succ / seeds,
                         "random_expected_unique_evals_analytic": rand_exp, "grover_ideal_known_M": (math.pi / 4) * math.sqrt(N / M) if M else None,
                         "bbht_cheaper_than_random": bool(np.mean(calls) < rand_exp) if calls else None})
        cross = [r["M_over_N"] for r in rows if r["bbht_cheaper_than_random"] is not None and not r["bbht_cheaper_than_random"]]
        payload[f"{grid}_k{k}"] = {"N": N, "rows": rows, "smallest_M_over_N_where_random_wins": min(cross) if cross else None,
                                   "largest_M_over_N_where_bbht_cheaper": max((r["M_over_N"] for r in rows if r["bbht_cheaper_than_random"]), default=None)}
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "EMULATED", dataset=grid))
    return ExpOutput(parts=parts, payload=payload, datasets_used=["ieee14", "ieee30", "ieee118"], seeds=list(range(seeds)),
                     accounting=accounting(quantum_oracle_calls_emulated="BBHT sum(j+1) until first marked set (emulated)", classical_function_evaluations="random search: analytic expectation (N+1)/(M+1)"),
                     limitations=["BBHT is Tier B emulation; random-search cost is the exact expectation for sampling without replacement."], parameters={"seeds": seeds})
