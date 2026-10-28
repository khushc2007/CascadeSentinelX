"""E11: rating / trip / ladder robustness (V2 17, 18 E11). One factor at a time against the E11 baseline (specs.DEVIATIONS E11-baseline).
Every variant is a full DC truth table under its own oracle namespace (never reused across configurations). Variants whose data or base
point does not exist (e.g. case-file ratings on a case without RATE_A) are recorded as NOT APPLICABLE with the error, never substituted."""
from __future__ import annotations
import numpy as np
from ..gridtwin.base import BasePointError
from ..gridtwin.ratings import RatingDataError
from . import specs as SP
from .common import TableMissing, cfg_for, qstats, tables_for
from .framework import ExpOutput, Part, data_status_for
from .ranking_metrics import topT_stability

GRIDS = ("ieee14", "ieee30", "ieee118")

def variants(grid: str) -> list:
    """(factor, value, overrides) list, one factor at a time. The baseline value of each factor is skipped (it IS the baseline)."""
    E = SP.E11_MAIN; v = []
    for h in E["headroom_h"]:
        if h != 0.25: v.append(("headroom_h", h, {"rating": {"headroom_h": h}}))
    for lam in E["stress_lambda"]:
        if lam != 1.1: v.append(("stress_lambda", lam, {"stress_lambda": lam}))
    for t in E["trip_factor"]:
        if t != 1.0: v.append(("trip_factor", t, {"cascade": {"trip_factor": t}}))
    for f in E["families"]:
        if f != "n1_covering": v.append(("rating_family", f, {"rating": {"family": f}}))
    for p in E["trip_policy"]:
        if p != "all_overloaded": v.append(("trip_policy", p, {"cascade": {"trip_policy": p}}))
    for r in E["redispatch"]:
        if r != "up_and_down": v.append(("redispatch", r, {"cascade": {"redispatch": r}}))
    for m in E["max_rounds"]:
        if m != 30: v.append(("max_rounds", m, {"cascade": {"max_rounds": m}}))
    for d in range(SP.E11_PERTURB_DRAWS[grid]):
        v.append(("perturb_10pct", d, {"rating": {"perturb_frac": E["perturb_frac"], "perturb_seed": d}}))
    return v

def _profile(t, k) -> dict:
    A = t._tables[k].arrays; S = np.asarray(A["S"]); S0 = np.asarray(A["S0"]); band = SP.BAND
    hi = S >= SP.TAU - band; cd = hi & ((S - S0) >= SP.DELTA_CASCADE - band)
    return {"S": S, "n_high": int(hi.sum()), "frac_high": float(hi.mean()), "cascade_driven_frac_of_high": float(cd.sum() / hi.sum()) if hi.sum() else None,
            "Smax": float(S.max()), "rounds_p95": float(np.percentile(np.asarray(A["rounds"]), 95)),
            "exhausted": int((np.asarray(A["status"]) == 1).sum())}

def _cmp(base, var) -> dict:
    st = topT_stability(base["S"], var["S"])
    return {"spearman": st["spearman"], "top10_jaccard": st["top10"].get("tie_expanded_jaccard"), "top10_informative": st["top10"].get("informative"),
            "top100_jaccard": st["top100"].get("tie_expanded_jaccard") if st["top100"].get("feasible") else None,
            "n_high": var["n_high"], "frac_high": var["frac_high"], "cascade_driven_frac_of_high": var["cascade_driven_frac_of_high"], "Smax": var["Smax"],
            "rounds_p95": var["rounds_p95"], "exhausted": var["exhausted"], "detail": {kk: vv for kk, vv in st.items() if kk.startswith("top")}}

def e11(config, ctx) -> ExpOutput:
    parts, payload = [], {"baseline": "see specs.DEVIATIONS E11-baseline", "grid_k": SP.E11_GRID_K, "perturb_draws": SP.E11_PERTURB_DRAWS}
    fam_j = []
    for grid in GRIDS:
        k = SP.E11_GRID_K[grid]; name = f"robustness_dc[{grid},k={k}]"
        try:
            base = _profile(tables_for(ctx, grid, "dc", [k]), k)
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        g = {"k": k, "baseline": {kk: vv for kk, vv in base.items() if kk != "S"}, "variants": []}
        for factor, value, ov in variants(grid):
            row = {"factor": factor, "value": value}
            try:
                cfg = cfg_for(grid, ov); var = _profile(tables_for(ctx, grid, "dc", [k], cfg=cfg), k); row.update(_cmp(base, var)); row["status"] = "OK"
            except (RatingDataError, BasePointError) as e:
                row.update(status="NOT_APPLICABLE", error=f"{type(e).__name__}: {e}")
            g["variants"].append(row)
            if factor == "rating_family" and row["status"] == "OK" and row["top10_jaccard"] is not None:
                fam_j.append({"grid": grid, "family": value, "top10_jaccard": row["top10_jaccard"]})
        summ = {}
        for f in sorted({r["factor"] for r in g["variants"]}):
            ok = [r for r in g["variants"] if r["factor"] == f and r["status"] == "OK"]
            summ[f] = {"n_ok": len(ok), "n_not_applicable": sum(r["factor"] == f and r["status"] != "OK" for r in g["variants"]),
                       "top10_jaccard": qstats([r["top10_jaccard"] for r in ok if r["top10_jaccard"] is not None]),
                       "top100_jaccard": qstats([r["top100_jaccard"] for r in ok if r["top100_jaccard"] is not None]),
                       "spearman": qstats([r["spearman"] for r in ok if r["spearman"] == r["spearman"]])}
        g["summary_by_factor"] = summ; payload[grid] = g
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    # ---- AC ladder-step and AC tolerance (V2 17: 'Load-shedding ladder' main, 'AC tolerance' appendix)
    payload["ac"] = {}
    for grid, k in SP.E11_AC.items():
        name = f"robustness_ac_ladder_tol[{grid},k={k}]"
        try:
            base_t = tables_for(ctx, grid, "ac", [k]); A = base_t._tables[k].arrays; Sb = np.asarray(A["S"]); St = np.asarray(A["S_total"]); St = np.where(np.isnan(St), Sb, St)
        except TableMissing as e:
            parts.append(Part(name, "NOT_RUN", reason=str(e), dataset=grid)); continue
        rows = {"total_loss_vs_ladder_0.05": {**topT_stability(Sb, St), "interval_width": qstats(St - Sb), "sets_with_ladder": int((np.asarray(A["ladder"]) >= 0).sum())}}
        for step in SP.E11_APPENDIX["ladder_step"]:
            if step == 0.05: continue
            S2 = tables_for(ctx, grid, "ac", [k], cfg=cfg_for(grid, {"cascade": {"ladder_step": step}})).all_severities()
            rows[f"ladder_step_{step}"] = {**topT_stability(Sb, S2), "abs_S_shift": qstats(np.abs(S2 - Sb))}
        for tol in SP.E11_APPENDIX["ac_tol_pu"]:
            if tol == 1e-8: continue
            S2 = tables_for(ctx, grid, "ac", [k], cfg=cfg_for(grid, {"numerics": {"ac_tol_pu": tol}})).all_severities()
            rows[f"ac_tol_{tol:g}"] = {**topT_stability(Sb, S2), "abs_S_shift": qstats(np.abs(S2 - Sb)), "sets_changed": int((np.abs(S2 - Sb) > SP.BAND).sum())}
        payload["ac"][f"{grid}_k{k}"] = rows
        parts.append(Part(name, "EXECUTED", data_status_for(grid), "MEASURED", dataset=grid))
    med = float(np.median([f["top10_jaccard"] for f in fam_j])) if fam_j else None
    payload["F3"] = {**SP.F3, "pairs": fam_j, "median_top10_jaccard": med, "F3_met_findings_are_rating_artefacts": (med < SP.F3["jaccard_min"]) if med is not None else None}
    return ExpOutput(parts=parts, payload=payload, datasets_used=list(GRIDS), seeds=list(range(max(SP.E11_PERTURB_DRAWS.values()))), criteria=[SP.F3],
                     limitations=["One factor at a time around the E11 baseline (no interactions).", "IEEE-118 at k=2 with 10 perturbation draws (specs.DEVIATIONS E11-118).",
                                  "Top-T metrics are tie-expanded; uninformative when s_T is on the zero plateau (flagged per row)."],
                     parameters={"main": SP.E11_MAIN, "appendix": SP.E11_APPENDIX})
