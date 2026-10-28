"""kappa_cal = (synthesized count)/(formula count) per primitive. UNAVAILABLE: it requires the A2 micro-oracle (synthesized reversible circuit with
counted Toffolis), which is not implemented. This module exists so that the model cannot be mislabelled: it always reports calibrated=False."""
from __future__ import annotations

def status() -> dict:
    return {"calibrated": False, "kappa_cal": None,
            "reason": "A2 micro-oracle (E14) not implemented: no synthesized Toffoli counts exist, so no formula has been calibrated against a circuit",
            "consequence": "all component counts are analytical estimates from printed V2 formulas; uncertainty is NOT bounded by calibration"}


# ---- (Phase 11) per-primitive kappa_cal from the A2 micro-oracle (E14) ------------------------------------------------------------------
# Mapping from V2 16.2 oracle components to the A2 primitive that calibrates them. small_inverse has NO A2 counterpart (A2 uses a per-topology
# sensitivity QROM instead): it keeps kappa = 1 and is flagged UNCALIBRATED. full_gaussian_elimination is b^2-multiplication dominated: the
# multiplier kappa is EXTRAPOLATED to it (flagged). Default everywhere remains calibrated=False unless a kappa dict is passed explicitly.
COMPONENT_TO_PRIMITIVE = {"island_detection": "island_detection", "rank_K_flow_update": "multiplier_flow_update",
                          "injection_update_PTDF_dP": "multiplier_flow_update", "comparators_trip_update": "comparators_trip",
                          "served_load_accumulation": "served_load_accumulation", "phi_qrom_lookups": "qrom_sensitivity_lookup",
                          "small_inverse": None, "full_gaussian_elimination": "multiplier_flow_update"}
EXTRAPOLATED = {"full_gaussian_elimination"}

def kappa_from_e14(result: dict) -> dict:
    """Extract {primitive: kappa} from an E14 result.json payload (results/phase7/E14/result.json)."""
    cal = result["payload"]["calibration"]
    return {k: v["kappa_cal"] for k, v in cal.items() if isinstance(v, dict) and v.get("kappa_cal") is not None}

def apply(components: dict, kappa: dict | None) -> tuple[dict, dict]:
    """Scale each oracle component by its primitive's kappa. Returns (scaled components, provenance per component)."""
    if not kappa: return dict(components), {c: "uncalibrated (V2 formula)" for c in components}
    out, prov = {}, {}
    for c, v in components.items():
        prim = COMPONENT_TO_PRIMITIVE.get(c)
        if prim is None or prim not in kappa:
            out[c] = v; prov[c] = "UNCALIBRATED (no A2 counterpart; kappa = 1)"
        else:
            out[c] = v * kappa[prim]; prov[c] = f"kappa_cal({prim}) = {kappa[prim]:.3g}" + (" EXTRAPOLATED" if c in EXTRAPOLATED else "")
    return out, prov

def calibrated_status(kappa: dict, source: str) -> dict:
    return {"calibrated": "partial", "kappa_cal": dict(kappa), "source": source,
            "reason": "kappa_cal measured on the A2 toy micro-oracle (textbook reversible synthesis: ripple-carry adders, shift-and-add multipliers); "
                      "small_inverse uncalibrated; full_gaussian_elimination extrapolated",
            "consequence": "scaled V2 formulas; still an ESTIMATE of a never-synthesized IEEE-scale circuit"}
