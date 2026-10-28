"""E0-E3: simulator validation, runtime profile, cascade phenomenology, DC-AC agreement (V2 10.1, 18).
Every function returns an ExpOutput; parts that cannot run (compute, missing table) are NOT_RUN with the reason. No dataset substitution."""
from __future__ import annotations
import json, subprocess, sys, time, warnings
from pathlib import Path
import numpy as np
from ..gridtwin.ac import solve_ac
from ..gridtwin.cascade import CascadeEngine
from ..gridtwin.dc import dc_power_flow, incidence
from ..gridtwin.islanding import bridges
from ..gridtwin.loader import DATA_DIR, load_grid
from ..oracle.factory import make_oracle
from . import specs as SP
from .common import TableMissing, bp_cached, boot_ci, cfg_for, qstats, tables_for
from .framework import ExpOutput, Part, accounting, data_status_for
from .ranking_metrics import jaccard, spearman, tie_expanded_topT

GRIDS = ("ieee14", "ieee30", "ieee118")
CASE = {"ieee14": "case14", "ieee30": "case30", "ieee118": "case118"}
ROOT = Path(__file__).resolve().parents[2]

# =============================================================================================== E0
def _pypower_case(grid):
    from matpowercaseframes import CaseFrames
    d = CaseFrames(str(DATA_DIR / f"{CASE[grid]}.m")).to_mpc()
    return {"version": "2", "baseMVA": float(d["baseMVA"]), "bus": np.array(d["bus"], float), "gen": np.array(d["gen"], float), "branch": np.array(d["branch"], float)}

def _runpf(ppc):
    from pypower.ppoption import ppoption
    from pypower.runpf import runpf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return runpf(ppc, ppoption(VERBOSE=0, OUT_ALL=0, PF_TOL=1e-12, PF_MAX_IT=30, ENFORCE_Q_LIMS=0))

def _ac_compare(g, r, res, status):
    Va = np.angle(r.V); va = np.deg2rad(res["bus"][:, 8]); sl = g.slack_bus; on = status > 0
    return {"dVm": float(np.abs(res["bus"][:, 7] - r.Vm).max()), "dVa_rad": float(np.abs((va - va[sl]) - (Va - Va[sl])).max()),
            "dPf_pu": float(np.abs(res["branch"][on, 13] - r.Sf_mva.real[on]).max() / g.base_mva),
            "dQf_pu": float(np.abs(res["branch"][on, 14] - r.Sf_mva.imag[on]).max() / g.base_mva)}

def e0(config, ctx) -> ExpOutput:
    tol = config["params"]["tol_pu"]; parts, payload = [], {"tolerance_pu": tol}
    # (1) hand-solved / analytic suites (U1, U2, U3, U4, U5, U6, U9, U10, U11) executed by pytest
    xml = Path(ctx.exp_dir("E0")) / "hand_solved_junit.xml"
    files = ["tests/unit/test_dc.py", "tests/unit/test_ac.py", "tests/unit/test_cascade_known.py", "tests/unit/test_cascade_invariants.py",
             "tests/unit/test_dc_sensitivities.py", "tests/unit/test_security.py"]
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", *files], cwd=ROOT, capture_output=True, text=True)
    import xml.etree.ElementTree as ET
    cases = [{"name": f"{c.get('classname')}::{c.get('name')}", "outcome": "failed" if c.find("failure") is not None or c.find("error") is not None
              else ("skipped" if c.find("skipped") is not None else "passed")} for c in ET.parse(xml).getroot().iter("testcase")]
    ok = p.returncode == 0 and all(c["outcome"] == "passed" for c in cases)
    payload["hand_solved"] = {"files": files, "n": len(cases), "passed": sum(c["outcome"] == "passed" for c in cases), "cases": cases, "pass": ok}
    parts.append(Part("hand_solved_toy_grids_U1_U2_U9_U11", "EXECUTED", "NO_GRID_DATA", "HAND_SOLVED"))
    # (2) independent reference solver on the official cases: base AC, every non-bridge N-1 AC, DC (tap-neglected and MATPOWER convention)
    from pypower.rundcpf import rundcpf
    from pypower.ppoption import ppoption
    payload["reference"] = {}
    for grid in GRIDS:
        g = load_grid(grid); ppc = _pypower_case(grid); res, okr = _runpf(ppc); r = solve_ac(g, tol=1e-12)
        base = dict(_ac_compare(g, r, res, g.br_status), converged_both=bool(okr and r.converged))
        n1, worst, nonconv = [], {"dVm": 0.0, "dVa_rad": 0.0, "dPf_pu": 0.0, "dQf_pu": 0.0}, []
        for l in sorted(set(range(g.n_branch)) - set(bridges(g))):
            s = g.br_status.copy(); s[l] = 0; q = {**ppc, "branch": ppc["branch"].copy()}; q["branch"][l, 10] = 0
            rr, okk = _runpf(q); mine = solve_ac(g, s, tol=1e-12)
            if not (okk and mine.converged): nonconv.append({"branch": l, "pypower": bool(okk), "ours": bool(mine.converged)}); continue
            c = _ac_compare(g, mine, rr, s); worst = {k: max(worst[k], c[k]) for k in worst}; n1.append(l)
        # DC: ours neglects taps and shifts (B' = A^T diag(1/x) A, V2 6.1). Compare with PYPOWER on (a) a tap/shift-neglected copy, (b) the case as is.
        pin = np.zeros(g.n_bus); np.add.at(pin, g.gen_bus[g.gen_status > 0], g.gen_Pg[g.gen_status > 0]); pin -= g.Pd
        mine_dc = dc_power_flow(g, pin)
        def dcrun(c):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore"); return rundcpf(c, ppoption(VERBOSE=0, OUT_ALL=0))[0]
        q = {**ppc, "branch": ppc["branch"].copy()}; q["branch"][:, 8] = 0; q["branch"][:, 9] = 0
        a, b = dcrun(q), dcrun(ppc)
        dc_neg = float(np.abs(a["branch"][:, 13] - mine_dc.flow_mw).max() / g.base_mva); dc_mp = float(np.abs(b["branch"][:, 13] - mine_dc.flow_mw).max() / g.base_mva)
        # KCL / balance residuals: base DC and 300 random k=3 DC cascades (per-island balance log)
        kcl = float(np.abs(incidence(g).T @ mine_dc.flow_mw - pin)[np.arange(g.n_bus) != g.slack_bus].max() / g.base_mva)
        cfg = cfg_for(grid); bp = bp_cached(grid, cfg); eng = CascadeEngine(bp, cfg); rng = np.random.default_rng(0)
        L = g.n_branch; bal = 0.0; det_ok = True
        for _ in range(300):
            x = sorted(rng.choice(L, 3, replace=False).tolist()); c1 = eng.run(x, record_balance=True); c2 = eng.run(x)
            det_ok &= (c1.S == c2.S and c1.trips_per_round == c2.trips_per_round)
            for e in c1.balance_log:
                if not e["dead"]: bal = max(bal, abs(e["gen_mw"] - e["load_mw"]) / g.base_mva)
        passed = base["dVm"] < tol and base["dVa_rad"] < tol and worst["dVm"] < tol and worst["dVa_rad"] < tol and dc_neg < tol and kcl < tol and bal < tol and det_ok and not nonconv
        payload["reference"][grid] = {"reference_solver": "PYPOWER 5.1 runpf/rundcpf (MATPOWER port)", "base_ac": base, "n1_ac": {"n_outages": len(n1), "max_abs_diff": worst, "nonconverged": nonconv},
                                      "dc_vs_pypower_taps_shifts_neglected_pu": dc_neg, "dc_vs_pypower_matpower_convention_pu": dc_mp,
                                      "dc_convention_note": "V2 6.1 DC uses b=1/x (taps/phase shifts neglected); MATPOWER's DC uses b=1/(x*tap) plus shift injections. The second number is that convention difference, not an error.",
                                      "kcl_residual_pu": kcl, "island_balance_residual_pu_300_random_k3": bal, "deterministic_replay_300": bool(det_ok), "pass": bool(passed)}
        parts.append(Part(f"reference_and_conservation[{grid}]", "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    allpass = ok and all(v["pass"] for v in payload["reference"].values())
    payload["verdict"] = "PASS: twin matches hand-solved cases and the reference solver to tolerance" if allpass else "FAIL: V2 E0 says do not proceed; every later result is void"
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(GRIDS), criteria=[{"criterion": f"all flows match to {tol} p.u.; conservation residual < {tol}; cascade sequences match", "met": allpass}],
                     limitations=["Reference solver is PYPOWER, not pandapower (see specs.DEVIATIONS E0-reference).", "AC comparison is at the unstressed case-file operating point; the cascade's stressed base point uses the same solver."],
                     parameters={"tol_pu": tol})

# =============================================================================================== E1
def e1(config, ctx) -> ExpOutput:
    P = SP.E1_SAMPLES; parts, payload, k = [], {"protocol": P, "machine_specific": True}, P["k"]
    for grid in GRIDS:
        cfg = cfg_for(grid); bp = bp_cached(grid, cfg); eng = CascadeEngine(bp, cfg); rng = np.random.default_rng(1)
        try:
            tab = tables_for(ctx, grid, "dc", [k])
        except TableMissing as e:
            parts.append(Part(f"runtime[{grid}]", "NOT_RUN", reason=str(e), dataset=grid)); continue
        S = tab.all_severities(); sp = tab.space; top = np.flatnonzero(S >= np.quantile(S, 0.99)); top = top if len(top) else np.argsort(S)[-10:]
        sets = {"random": [tuple(sp.unrank(int(r))) for r in rng.choice(sp.N, P["random"], replace=False)],
                "high_severity": [tuple(sp.unrank(int(r))) for r in rng.choice(top, P["high_severity"], replace=len(top) < P["high_severity"])]}
        out = {}
        for fid in ("dc", "ac"):
            for kind, xs in sets.items():
                t, cls = [], []
                eng.run(list(xs[0]), mode=fid)                                       # warm-up (not timed)
                for x in xs:
                    t0 = time.perf_counter(); r = eng.run(list(x), mode=fid); t.append(time.perf_counter() - t0)
                    cls.append("islanding" if max(r.islands_per_round) > 1 else ("long_cascade" if r.rounds >= P["long_cascade_rounds"] else "other"))
                t = np.array(t) * 1e3; cls = np.array(cls)
                out[f"{fid}_{kind}"] = {"all_ms": qstats(t), **{c: qstats(t[cls == c]) for c in ("islanding", "long_cascade", "other")},
                                        "class_counts": {c: int((cls == c).sum()) for c in ("islanding", "long_cascade", "other")}}
        payload[grid] = out
        parts.append(Part(f"runtime[{grid}]", "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    from .framework import environment
    payload["t_c_ms_for_resource_model"] = {g: {"dc_mean_random": payload[g]["dc_random"]["all_ms"]["mean"], "ac_mean_random": payload[g]["ac_random"]["all_ms"]["mean"]}
                                            for g in GRIDS if g in payload}
    payload["v2_targets_hypotheses"] = {"dc_ms": 0.5, "ac_ms": 30}
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(GRIDS), seeds=[1],
                     limitations=["Single-process scalar Python (CascadeEngine.run), one evaluation at a time; timings are machine-specific.",
                                  "High-severity sets are drawn from the top 1% of the DC k=3 table, timed in both DC and AC."],
                     parameters={"k": k, "env": environment()})

# =============================================================================================== E2
def _nonmono(Sk, Skm1, sp_k, sp_km1, band=SP.BAND, chunk=200_000):
    """Fraction of (x subset y, |y| = |x|+1) pairs with S(y) < S(x) - band, and fraction of y with any such subset."""
    N = sp_k.N; viol_pairs = 0; any_y = 0; pairs = 0
    for s in range(0, N, chunk):
        e = min(s + chunk, N); Y = sp_k.unrank_batch(np.arange(s, e, dtype=np.int64)); k = Y.shape[1]; Sy = Sk[s:e]; anyv = np.zeros(e - s, bool)
        for i in range(k):
            X = np.delete(Y, i, axis=1); Sx = Skm1[sp_km1.rank_batch(X)] if k > 1 else np.zeros(e - s)
            v = Sy < Sx - band; viol_pairs += int(v.sum()); anyv |= v; pairs += e - s
        any_y += int(anyv.sum())
    return {"pairs": pairs, "violating_pairs": viol_pairs, "pair_fraction": viol_pairs / pairs, "sets_with_any_violation_fraction": any_y / N}

def e2(config, ctx) -> ExpOutput:
    parts, payload = [], {"tau": SP.TAU, "delta": SP.DELTA_CASCADE}; tau, dl, band = SP.TAU, SP.DELTA_CASCADE, SP.BAND
    for grid in GRIDS:
        for k in SP.PRE_KS["E2"][grid]:
            if ("E2", grid, k) in SP.COMPUTE_NOT_RUN:
                parts.append(Part(f"phenomenology[{grid},k={k}]", "NOT_RUN", reason="compute: " + SP.COMPUTE_NOT_RUN[("E2", grid, k)], dataset=grid)); continue
            try:
                tab = tables_for(ctx, grid, "dc", [k])
            except TableMissing as e:
                parts.append(Part(f"phenomenology[{grid},k={k}]", "NOT_RUN", reason=str(e), dataset=grid)); continue
            t = tab._tables[k]; A = t.arrays; S = np.asarray(A["S"]); S0 = np.asarray(A["S0"]); C = S - S0
            rounds = np.asarray(A["rounds"]); trips = np.asarray(A["n_trips"]); hi = S >= tau - band; cd = hi & (C >= dl - band)
            keff = k + trips; tot = S.sum()
            row = {"N": int(len(S)), "S_quantiles": {q: float(np.quantile(S, q)) for q in (0.5, 0.9, 0.99, 0.999, 1.0)}, "frac_S_gt_0": float((S > band).mean()),
                   "n_high_severity": int(hi.sum()), "frac_high_severity": float(hi.mean()), "n_cascade_driven_high": int(cd.sum()),
                   "cascade_driven_share_of_high": float(cd.sum() / hi.sum()) if hi.sum() else None,
                   "severity_share_from_isolation_S0": float(S0.sum() / tot) if tot > 0 else None, "severity_share_from_cascade_C": float(C.sum() / tot) if tot > 0 else None,
                   "C_stats_on_S_gt_0": qstats(C[S > band]), "rounds_all": qstats(rounds), "rounds_on_S_gt_0": qstats(rounds[S > band]), "rounds_on_high": qstats(rounds[hi]),
                   "trips_all": qstats(trips), "trips_on_high": qstats(trips[hi]), "keff_all": qstats(keff), "keff_on_high": qstats(keff[hi]),
                   "status_counts": {s: int((np.asarray(A["status"]) == i).sum()) for i, s in enumerate(("STABLE", "EXHAUSTED", "TOTAL_LOSS"))},
                   "Smax": float(S.max()), "histogram": np.histogram(S, bins=40, range=(0, 1))[0].tolist()}
            if k >= 2:
                row["non_monotonicity"] = _nonmono(S, np.asarray(tab._tables[k - 1].arrays["S"]), tab.space, tab.with_k(k - 1).space)
            payload[f"{grid}_k{k}"] = row
            parts.append(Part(f"phenomenology[{grid},k={k}]", "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    # measured R / keff summaries for the resource model (V2 16.5: R and keff from E2)
    payload["resource_inputs"] = {key: {"R_p50": v["rounds_on_S_gt_0"]["median"] if v["rounds_on_S_gt_0"] else None, "R_p95": v["rounds_on_S_gt_0"]["p95"] if v["rounds_on_S_gt_0"] else None,
                                        "R_max": v["rounds_all"]["max"], "keff_p50": v["keff_on_high"]["median"] if v["keff_on_high"] else None,
                                        "keff_p95": v["keff_on_high"]["p95"] if v["keff_on_high"] else None, "keff_max": v["keff_all"]["max"]}
                                  for key, v in payload.items() if isinstance(v, dict) and "rounds_all" in v}
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(GRIDS),
                     limitations=["DC fidelity tables (V2 E2).", "rounds = solved power-flow rounds; keff = k + total trips (outage-set size at termination)."],
                     parameters={"tau": tau, "delta": dl})

# =============================================================================================== E3
def _agreement(Sdc, Sac, tau=SP.TAU, band=SP.BAND):
    pd, pa = Sdc >= tau - band, Sac >= tau - band; tp = int((pd & pa).sum()); fp = int((pd & ~pa).sum()); fn = int((~pd & pa).sum())
    prec = tp / (tp + fp) if tp + fp else None; rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    out = {"N": int(len(Sdc)), "ac_positives": int(pa.sum()), "dc_positives": int(pd.sum()), "tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec, "f1": f1,
           "false_negative_rate": (fn / (tp + fn)) if tp + fn else None, "spearman": spearman(Sdc, Sac), "S_error": qstats(np.abs(Sdc - Sac)),
           "S_error_signed_mean": float((Sdc - Sac).mean())}
    for T in (10, 100):
        if T <= len(Sdc) and np.sort(Sac)[-T] > band:
            ed, ea = tie_expanded_topT(Sdc, T), tie_expanded_topT(Sac, T)
            out[f"top{T}"] = {"overlap_share_of_ac": len(set(ed) & set(ea)) / len(ea), "jaccard": jaccard(ed, ea), "sizes": [int(len(ed)), int(len(ea))]}
        else:
            out[f"top{T}"] = {"informative": False}
    return out

def _verdict(a):
    r, o = a["recall"], a.get("top10", {}).get("overlap_share_of_ac")
    if r is None or o is None: return {"verdict": "NOT EVALUABLE (no AC positives or uninformative top-10)", "recall": r, "top10_overlap": o}
    met = r >= SP.E3_RULE["recall_at_tau_min"] and o >= SP.E3_RULE["top10_overlap_min"]
    return {"verdict": SP.E3_RULE["verdict_if_met"] if met else SP.E3_RULE["verdict_if_not"], "met": bool(met), "recall": r, "top10_overlap": o}

def e3(config, ctx) -> ExpOutput:
    parts, payload = [], {"rule": SP.E3_RULE, "E3a": {}, "E3b": {}, "E3c": {}}
    for grid in GRIDS:                                                            # ---- E3a exhaustive
        for k in SP.PRE_KS["E3a"][grid]:
            name = f"E3a[{grid},k={k}]"
            if ("E3a", grid, k) in SP.COMPUTE_NOT_RUN:
                parts.append(Part(name, "NOT_RUN", reason="compute: " + SP.COMPUTE_NOT_RUN[("E3a", grid, k)], dataset=grid)); continue
            try:
                dc, ac = tables_for(ctx, grid, "dc", [k]), tables_for(ctx, grid, "ac", [k])
            except TableMissing as e:
                parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
            Sd, Sa = dc.all_severities(), ac.all_severities(); a = _agreement(Sd, Sa)
            a["ac_flags"] = {"nonconv_or_ladder": int((np.asarray(ac._tables[k].arrays["flags"]) & 1).sum()), "ladder_used": int((np.asarray(ac._tables[k].arrays["ladder"]) >= 0).sum())}
            a["decision"] = _verdict(a); a["scatter_sample"] = _scatter(Sd, Sa)
            payload["E3a"][f"{grid}_k{k}"] = a; parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    # ---- E3b: pre-registered (IEEE-118 k=4) NOT_RUN; supplementary stratified sample at k=3
    parts.append(Part("E3b[ieee118,k=4]", "NOT_RUN", reason="compute: " + SP.COMPUTE_NOT_RUN[("E3b", "ieee118", 4)], dataset="ieee118"))
    try:
        dc = tables_for(ctx, "ieee118", "dc", [3]); Sd = dc.all_severities(); rng = np.random.default_rng(7); per = config["params"]["e3b_per_stratum"]
        pos = np.flatnonzero(Sd > SP.BAND); edges = np.quantile(Sd[pos], np.linspace(0, 1, 11)); strata = {"S_dc=0": np.flatnonzero(Sd <= SP.BAND)}
        for i in range(10):
            sel = pos[(Sd[pos] >= edges[i]) & ((Sd[pos] < edges[i + 1]) if i < 9 else (Sd[pos] <= edges[i + 1]))]; strata[f"decile_{i + 1}"] = sel
        cfg = cfg_for("ieee118"); aco = make_oracle("ac", 3, cfg, bp=bp_cached("ieee118", cfg), use_cache=False); rows = {}; allD, allA, allW = [], [], []
        for nm, idx in strata.items():
            pick = rng.choice(idx, min(per, len(idx)), replace=False); X = dc.space.unrank_batch(pick)
            sa = np.array([aco.severity(tuple(int(v) for v in x)) for x in X]); sd = Sd[pick]
            pa = sa >= SP.TAU - SP.BAND; pdd = sd >= SP.TAU - SP.BAND
            rows[nm] = {"stratum_size": int(len(idx)), "sampled": int(len(pick)), "ac_positive": int(pa.sum()), "dc_positive": int(pdd.sum()),
                        "recall_in_stratum": (float((pa & pdd).sum() / pa.sum()) if pa.sum() else None), "mean_abs_S_error": float(np.abs(sd - sa).mean())}
            allD += sd.tolist(); allA += sa.tolist(); allW += [len(idx) / len(pick)] * len(pick)
        D, Aa, W = np.array(allD), np.array(allA), np.array(allW); pa = Aa >= SP.TAU - SP.BAND; pdd = D >= SP.TAU - SP.BAND
        w_rec = float((W * (pa & pdd)).sum() / (W * pa).sum()) if pa.any() else None
        payload["E3b"]["ieee118_k3_SUPPLEMENTARY"] = {"strata": rows, "weighted_recall_estimate": w_rec, "weighted_ac_positive_rate": float((W * pa).sum() / W.sum()),
                                                     "note": "SUPPLEMENTARY (k=3, not the pre-registered k=4); stratum weights = stratum size / sample size"}
        parts.append(Part("E3b_supplementary[ieee118,k=3]", "EXECUTED", data_status_for("ieee118"), "MEASURED", dataset="ieee118"))
    except TableMissing as e:
        parts.append(Part("E3b_supplementary[ieee118,k=3]", "NOT_RUN", reason=str(e), dataset="ieee118"))
    # ---- E3c decomposition: (i) common ratings (=E3a), (ii) per-engine DC ratings (dc_basis=dc_flow), (iii) AC ladder disabled (S_total)
    for grid, ks in (("ieee14", [2, 3, 4]), ("ieee30", [2, 3]), ("ieee118", [2])):
        for k in ks:
            name = f"E3c[{grid},k={k}]"
            try:
                dc = tables_for(ctx, grid, "dc", [k]); ac = tables_for(ctx, grid, "ac", [k])
                dc2 = tables_for(ctx, grid, "dc", [k], cfg=cfg_for(grid, {"rating": {"dc_basis": "dc_flow"}}))
            except TableMissing as e:
                parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
            Sd, Sa, Sd2 = dc.all_severities(), ac.all_severities(), dc2.all_severities(); St = np.asarray(ac._tables[k].arrays["S_total"]); St = np.where(np.isnan(St), Sa, St)
            payload["E3c"][f"{grid}_k{k}"] = {"i_common_ratings": _agreement(Sd, Sa), "ii_per_engine_dc_ratings": _agreement(Sd2, Sa),
                                              "iii_ac_ladder_disabled_vs_dc": _agreement(Sd, St), "ladder_effect_ac_vs_ac_total": _agreement(Sa, St),
                                              "rating_effect_dc_vs_dc_per_engine": _agreement(Sd, Sd2)}
            parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    ev = [v["decision"] for v in payload["E3a"].values() if v["decision"].get("met") is not None]
    payload["overall"] = {"n_evaluable": len(ev), "n_trustworthy": sum(d["met"] for d in ev),
                          "F2_recall_below_threshold_any": any(d["recall"] < SP.F2["recall_min"] for d in ev), "min_recall": min((d["recall"] for d in ev), default=None)}
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(GRIDS), seeds=[7], criteria=[SP.E3_RULE],
                     limitations=["AC severities are S_ladder (V2 8.6); E3c(iii) uses S_total (failed islands fully lost).",
                                  "Thresholds fixed in doomsday/experiments/specs.py before execution."],
                     parameters={"tau": SP.TAU, "e3b_per_stratum": config["params"]["e3b_per_stratum"]})

def _scatter(Sd, Sa, n=4000, seed=3):
    idx = np.random.default_rng(seed).choice(len(Sd), min(n, len(Sd)), replace=False)
    return {"dc": np.round(Sd[idx], 5).tolist(), "ac": np.round(Sa[idx], 5).tolist()}
