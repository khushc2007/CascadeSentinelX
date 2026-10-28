"""Phase 12: precomputed demo data (V2 20.3 'precomputed-first', 21). Everything here is READ from the truth tables (results/phase7/tables), the
cascade engine and the experiment results; nothing is invented. Every file carries `evidence` labels and dataset provenance.
  PYTHONPATH=. python scripts/build_demo_data.py   -> app/data/*.json"""
from __future__ import annotations
import json, math
from math import comb
from pathlib import Path
import networkx as nx
import numpy as np
from ..experiments.common import TableMissing, bp_cached, cfg_for, tables_for
from ..experiments.framework import Ctx, dataset_info
from ..gridtwin.cascade import CascadeEngine
from ..gridtwin.contingency import space_for_grid
from ..gridtwin.security import loading
from ..qsearch.dh_gas import dh_max
from ..qsearch.emulation import collapsed_trajectory, optimal_r
from ..qsearch.predicate import PredicateTable
from ..classical import classical_search

GRIDS = ("ieee14", "ieee30", "ieee118")
EV = {"MEASURED": "[MEASURED]", "EMULATED": "[EMULATED]", "MODELLED": "[MODELLED]", "PROPOSED": "[PROPOSED]"}
TAU, DELTA, BAND = 0.20, 0.10, 1e-9
KS = {"ieee14": (2, 3, 4), "ieee30": (2, 3, 4), "ieee118": (2, 3)}

def _prov(grid):
    d = dataset_info(grid); return {"dataset": grid, "provenance": d["provenance_status"], "matpower_commit": d["matpower_commit"], "file_sha256": d["file_sha256"]}

def layout(g) -> dict:
    G = nx.Graph(); G.add_nodes_from(range(g.n_bus)); G.add_edges_from((int(f), int(t)) for f, t in zip(g.br_from, g.br_to))
    pos = nx.kamada_kawai_layout(G); xy = np.array([pos[i] for i in range(g.n_bus)]); xy = (xy - xy.min(0)) / np.maximum(np.ptp(xy, 0), 1e-9)
    return {"x": np.round(xy[:, 0], 4).tolist(), "y": np.round(xy[:, 1], 4).tolist(), "method": "Kamada-Kawai (NetworkX), normalised; not geographic"}

def grid_json(grid) -> dict:
    cfg = cfg_for(grid); bp = bp_cached(grid, cfg); g = bp.grid; ldc = loading(bp, "dc")[0]; lac = loading(bp, "ac")[0]
    return {"id": grid, **_prov(grid), "n_bus": g.n_bus, "n_branch": g.n_branch, "slack_bus": int(g.bus_id[g.slack_bus]), "layout": layout(g),
            "buses": [{"i": i, "id": int(g.bus_id[i]), "load_mw": float(g.Pd[i]), "base_kv": float(g.bus_base_kv[i]) if g.bus_base_kv is not None else None,
                       "has_gen": bool(np.any((g.gen_bus == i) & (g.gen_status > 0)))} for i in range(g.n_bus)],
            "branches": [{"l": l, "from": int(g.br_from[l]), "to": int(g.br_to[l]), "rating_dc_mw": float(g.rating_dc[l]), "rating_ac_mva": float(g.rating_ac[l]),
                          "base_loading_dc": float(ldc[l]), "base_loading_ac": float(lac[l]), "transformer": bool(g.br_is_transformer[l])} for l in range(g.n_branch)],
            "total_load_mw": float(g.Pd.sum()), "rating_family": bp.rating_info.get("family"), "evidence": EV["MEASURED"] + " base operating point from the official case + synthetic ratings (V2 5.3 / extension)"}

def _cascade(grid, outage, mode):
    cfg = cfg_for(grid); eng = CascadeEngine(bp_cached(grid, cfg), cfg); r = eng.run(sorted(outage), mode=mode); d = r.to_dict(frames=True)
    d["grid"] = grid; d["metrics"]["cascade_driven"] = bool(r.S >= TAU - BAND and r.C >= DELTA - BAND); d["evidence"] = EV["MEASURED"] + f" cascade run ({mode.upper()}, quasi-steady-state model)"
    return d

def _complete(ctx, grid, fid, k) -> bool:
    from ..oracle.factory import make_oracle
    from ..oracle.table_oracle import table_dir_name
    cfg = cfg_for(grid); o = make_oracle(fid, k, cfg, bp=bp_cached(grid, cfg), use_cache=False)
    m = Path(ctx.tables_dir) / table_dir_name(grid, fid, k, o.namespace) / "meta.json"
    return m.exists() and json.loads(m.read_text()).get("complete", False)

def ranking(ctx, grid, k, T=20) -> dict | None:
    try: dc = tables_for(ctx, grid, "dc", [k])
    except TableMissing: return None
    S = dc.all_severities(); A = dc._tables[k].arrays; order = np.lexsort((np.arange(len(S)), -S))[:T]; sp = dc.space
    Sac = Stot = None
    if _complete(ctx, grid, "ac", k):                                  # only READ an existing exhaustive AC table; never build one for the demo
        ac = tables_for(ctx, grid, "ac", [k]); Sac = ac.all_severities(); Stot = np.asarray(ac._tables[k].arrays["S_total"])
    rows = []
    for r in order:
        S0 = float(A["S0"][r]); C = float(S[r] - S0)
        rows.append({"rank_index": int(r), "outage": list(map(int, sp.unrank(int(r)))), "S_dc": float(S[r]), "S0_dc": S0, "C_dc": C, "rounds_dc": int(A["rounds"][r]),
                     "cascade_driven": bool(S[r] >= TAU - BAND and C >= DELTA - BAND), "S_ac": None if Sac is None else float(Sac[r]),
                     "S_ac_total": None if Stot is None or np.isnan(Stot[r]) else float(Stot[r])})
    return {"grid": grid, "k": k, "N": int(sp.N), "Smax_dc": float(S.max()), "n_high_dc": int((S >= TAU - BAND).sum()), "rows": rows,
            "ac_available": Sac is not None, "evidence": EV["MEASURED"] + " exhaustive DC truth table" + ("; AC values from the exhaustive AC table" if Sac is not None else "; AC table not built for this (grid, k)")}

def examples(ctx, grid, k) -> dict:
    """Three cards (V2 21 step 3): benign (S = 0); isolation-only = the most severe set with S > 0 and NO cascade contribution (C = 0), since on some
    grids no isolation-only set reaches tau; cascade-driven = the most severe set with S >= tau and C >= delta. A missing category is null."""
    dc = tables_for(ctx, grid, "dc", [k]); S = dc.all_severities(); A = dc._tables[k].arrays; C = S - np.asarray(A["S0"]); sp = dc.space
    pick = lambda m: int(np.flatnonzero(m)[np.argmax(S[m])]) if m.any() else None
    cards = {"benign": int(np.flatnonzero(S <= BAND)[0]) if (S <= BAND).any() else None, "isolation_only": pick((S > BAND) & (np.abs(C) <= BAND)),
             "cascade_driven": pick((S >= TAU - BAND) & (C >= DELTA - BAND))}
    return {name: (None if r is None else {"outage": list(map(int, sp.unrank(r))), "dc": _cascade(grid, sp.unrank(r), "dc"),
                                            "ac": _cascade(grid, sp.unrank(r), "ac") if grid != "ieee118" or k <= 2 else None}) for name, r in cards.items()}

def search_log(ctx, grid, k, seed=0) -> dict:
    """V2 21 steps 8-10: Grover amplitude bars (top-20 states, marked = maximisers), P(success) curve, DH attempt log and classical race traces."""
    tab = tables_for(ctx, grid, "dc", [k]); pt = PredicateTable.from_oracle(tab); S = pt.S; N = pt.N; M = int((S >= pt.Smax - BAND).sum())
    r_opt = optimal_r(N, M); rmax = min(2 * r_opt + 2, 400); a, b, p = collapsed_trajectory(N, M, rmax); top = np.lexsort((np.arange(N), -S))[:20]
    stride = max(1, rmax // 60); rs = list(range(0, rmax + 1, stride))
    bars = {"states": [{"rank_index": int(i), "S": float(S[i]), "marked": bool(S[i] >= pt.Smax - BAND)} for i in top],
            "r": rs, "amplitude": [[float(a[r] if S[i] >= pt.Smax - BAND else b[r]) for i in top] for r in rs]}
    dh = dh_max(pt, np.random.default_rng(seed), record_log=True); log = dh["counter"].log; q = 0; race_dh = []
    for e in log:
        q += e["j"] + 1
        if e["success"]: race_dh.append([q, float(S[e["x"]])])
    race = {"durr_hoyer_tierB_quantum_calls": race_dh}
    for m, kw in (("random", {}), ("hillclimb", {"n_starts": 5}), ("sa", {}), ("brute", {})):
        rr = classical_search(tab, m, budget=None if m == "brute" else math.ceil(0.5 * N), seed=seed, grid=grid, **kw); race[f"{m}_unique_evaluations"] = rr.trace
    return {"grid": grid, "k": k, "N": N, "M_maximisers": M, "Smax": pt.Smax, "theta": float(np.arcsin(math.sqrt(M / N))), "r_star": r_opt,
            "p_success": [float(x) for x in p], "bars": bars, "race": race, "dh_attempts": [{"y": e["y"], "j": e["j"], "success": e["success"]} for e in log][:2000],
            "dh_discovery_quantum_calls": dh["discovery_quantum_calls"], "table_construction_evals": N,
            "evidence": {"bars_and_curve": EV["EMULATED"] + " Tier B exact classical emulation of ideal Grover (not a quantum runtime)",
                         "race": EV["EMULATED"] + " Durr-Hoyer (quantum oracle calls, emulated) vs " + EV["MEASURED"] + " classical unique evaluations; different cost units, not a wall-clock race"}}

def evidence_ledger(ctx) -> dict:
    out = {}
    for eid in [f"E{i}" for i in range(17)]:
        m = ctx.load_manifest(eid)
        out[eid] = {"status": m["status"], "label": m["evidence_label"], "name": m["name"], "data_status": m["data_status"], "generated_utc": m["generated_utc"],
                    "parts": [{"name": p["name"], "status": p["status"], "reason": p["reason"][:300]} for p in m["parts"]]} if m else {"status": "NOT_RUN", "label": "[NOT_RUN]"}
    return out

def crossover_inputs(ctx) -> dict:
    e15 = ctx.load_result("E15"); e14 = ctx.load_result("E14")
    sc = {k: v["params"] for k, v in e15["payload"]["scenarios"].items()} if e15 else None
    kap = None
    if e14: kap = {k: v["kappa_cal"] for k, v in e14["payload"]["calibration"].items() if isinstance(v, dict) and v.get("kappa_cal") is not None}
    pts = {g: {"L": L, "B": B, "N_by_k": {k: comb(L, k) for k in range(1, 9)}} for g, L, B in (("ieee14", 20, 14), ("ieee30", 41, 30), ("ieee118", 186, 118))}
    return {"scenario_params_measured": sc, "kappa_cal": kap, "grid_points": pts, "evidence": EV["MODELLED"] + " analytical resource model; JS port parity-tested against Python",
            "headline": e15["payload"]["headline"] if e15 else None}


# ---- Phase 13b (advanced demo): data for the in-browser DC cascade port, severity distributions and headline numbers ---------------------
def cascade_model(grid) -> dict:
    """Everything the JavaScript DC cascade port (app/js/core/cascade.js) needs, taken from the SAME engine object the truth tables use
    (stressed base point, lossless dispatch, synthetic DC ratings). Floats are written at full precision so parity can be tested to 1e-9."""
    cfg = cfg_for(grid); eng = CascadeEngine(bp_cached(grid, cfg), cfg); g = eng.g; cc, nm = cfg.cascade, cfg.numerics
    f = lambda a: [float(v) for v in a]; i = lambda a: [int(v) for v in a]
    return {"grid": grid, **_prov(grid), "base_mva": float(g.base_mva), "n_bus": g.n_bus, "n_branch": g.n_branch, "bus_id": i(g.bus_id), "Pd": f(g.Pd),
            "br_from": i(g.br_from), "br_to": i(g.br_to), "x": f(g.x), "br_status": i(g.br_status), "rating_dc": f(g.rating_dc),
            "gen_bus": i(g.gen_bus), "gen_status": i(g.gen_status), "gen_Pmax": f(g.gen_Pmax), "gen_Pmin": f(g.gen_Pmin), "pg0": f(eng.pg0),
            "key_rank": i(eng.key_rank), "initial_load_mw": eng.initial_load,
            "cascade": {"trip_factor": cc.trip_factor, "trip_policy": cc.trip_policy, "max_rounds": cc.max_rounds, "redispatch": cc.redispatch,
                        "overload_tol": nm.overload_tol, "fixed_point_bits": nm.fixed_point_bits},
            "severity": {"tau": TAU, "delta": DELTA},
            "evidence": "JavaScript port of the Python DC cascade engine (doomsday/gridtwin/cascade.py, mode='dc'); parity-tested in app/test/cascade.test.mjs"}

def severity_dist(ctx, grid, k, top=500, bins=1000) -> dict | None:
    """Severity distribution of an exhaustive DC table: exact top-`top` values (with outages) and a fixed-width histogram on [0, 1]."""
    try: dc = tables_for(ctx, grid, "dc", [k])
    except TableMissing: return None
    S = dc.all_severities(); sp = dc.space; order = np.lexsort((np.arange(len(S)), -S))[:top]
    h, _ = np.histogram(np.clip(S, 0, 1), bins=bins, range=(0.0, 1.0))
    return {"grid": grid, "k": k, "N": int(sp.N), "bins": bins, "hist": h.astype(int).tolist(), "n_zero": int((S <= BAND).sum()),
            "n_high": int((S >= TAU - BAND).sum()), "top": [[float(S[r]), list(map(int, sp.unrank(int(r))))] for r in order],
            "evidence": EV["MEASURED"] + " exhaustive DC truth table"}

def headline(ctx) -> dict:
    """Pitch numbers, each copied from an experiment result (nothing computed here except unit conversions)."""
    L = lambda e: (ctx.load_result(e) or {}).get("payload") or {}
    e1, e3, e5, e6, e7, e11, e12, e14, e15, e16 = (L(e) for e in ("E1", "E3", "E5", "E6", "E7", "E11", "E12", "E14", "E15", "E16"))
    out = {"evidence": "copied from results/phase7/<E>/result.json; see REPORT.md"}
    out["tc_ms_dc_median"] = {g: e1.get(g, {}).get("dc_random", {}).get("all_ms", {}).get("median") for g in GRIDS}
    out["tc_ms_dc_mean"] = {g: e1.get(g, {}).get("dc_random", {}).get("all_ms", {}).get("mean") for g in GRIDS}
    out["e7"] = {key: {"N": v["N"], "Smax": v["Smax"], "best_method": v["best_structured"]["method"] if v.get("best_structured") else None,
                       "best_mean_discovery": v["best_structured"]["mean_discovery"] if v.get("best_structured") else None,
                       "best_success_rate": v["best_structured"].get("success_rate") if v.get("best_structured") else None,
                       "quantum_calls_c_hat_sqrtN": v.get("c_hat_sqrtN"), "budget": v.get("budget")} for key, v in (e7.get("dc") or {}).items()}
    fit = (e6.get("loglog_fits") or {}).get("y0_zero", {}).get("all_tables") or {}
    out["e6"] = {"exponent": fit.get("exponent"), "coefficient": fit.get("coefficient"), "r2": fit.get("r2"), "points": fit.get("points")}
    if e15:
        h = e15["headline"]["IEEE118_k3_realistic_be_prep"]; a = e15["alpha_sensitivity_realistic"].get("measured_best_structured") or {}
        out["e15"] = {"ratio_realistic_ieee118_k3": h.get("ratio_Tq_over_Tc"), "Tq_s": h.get("Tq_s"), "Tc_s": h.get("Tc_s"), "statement": e15["headline"].get("statement"),
                      "alpha_measured": a.get("alpha"), "alpha_method": a.get("method"), "N_star_measured_alpha": None if a.get("N_star") in (None, math.inf) else a.get("N_star")}
    if e16:
        out["e16"] = {k: {"name": v.get("name"), "status": v.get("status"), "holds": v.get("holds")} for k, v in e16.items() if k in ("F1", "F2", "F3", "H-C1")}
    if e11: out["e11_median_top10_jaccard"] = e11.get("F3", {}).get("median_top10_jaccard")
    if e3: out["e3"] = {"n_trustworthy": e3.get("overall", {}).get("n_trustworthy"), "n_evaluable": e3.get("overall", {}).get("n_evaluable")}
    if e12: out["e12_min_bits"] = {k: v.get("min_passing_b") for k, v in e12.items() if isinstance(v, dict) and "min_passing_b" in v}
    if e14: out["e14"] = {"qubits": e14.get("qubits"), "toffoli_equiv_total": e14.get("toffoli_equiv_total"), "all_checks_pass": e14.get("all_checks_pass"),
                          "kappa": {k: v.get("kappa_cal") for k, v in (e14.get("calibration") or {}).items() if isinstance(v, dict)}}
    if e5: out["e5_noisy_m6_k2"] = (e5.get("m6_k2") or {}).get("noisy_be", {}).get("summary")
    return out

def build(out_dir="app/data", results_root="results/phase7", grids=GRIDS, log=print) -> dict:
    ctx = Ctx(results_root=Path(results_root)); out = Path(out_dir); out.mkdir(parents=True, exist_ok=True); index = {"grids": [], "files": []}
    def w(name, obj):
        (out / name).write_text(json.dumps(obj, separators=(",", ":"))); index["files"].append(name); log("wrote", name)
    for grid in grids:
        gj = grid_json(grid); w(f"grid_{grid}.json", gj); entry = {"id": grid, "n_bus": gj["n_bus"], "n_branch": gj["n_branch"], "provenance": gj["provenance"], "k": {}}
        for k in KS[grid]:
            rk = ranking(ctx, grid, k)
            if rk is None: entry["k"][k] = {"available": False}; continue
            w(f"ranking_{grid}_k{k}.json", rk); entry["k"][k] = {"available": True, "N": rk["N"], "Smax_dc": rk["Smax_dc"]}
            if k in (2, 3):
                w(f"examples_{grid}_k{k}.json", examples(ctx, grid, k))
                w(f"top_cascades_{grid}_k{k}.json", [{"dc": _cascade(grid, r["outage"], "dc"), "ac": _cascade(grid, r["outage"], "ac") if grid != "ieee118" else None} for r in rk["rows"][:10]])
                w(f"search_{grid}_k{k}.json", search_log(ctx, grid, k))
        index["grids"].append(entry)
        w(f"cascade_model_{grid}.json", cascade_model(grid))
        for k in KS[grid]:
            d = severity_dist(ctx, grid, k)
            if d is not None: w(f"dist_{grid}_k{k}.json", d)
    w("evidence.json", evidence_ledger(ctx)); w("crossover.json", crossover_inputs(ctx)); w("headline.json", headline(ctx))
    w("wall.json", {g: {str(k): comb(L, k) for k in range(1, 11)} for g, L in (("ieee14", 20), ("ieee30", 41), ("ieee118", 186))})
    (out / "index.json").write_text(json.dumps(index, indent=1)); return index
