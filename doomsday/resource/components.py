"""Toffoli-count components of the coherent cascade oracle (V2 16.2). b-bit fixed point; Toffoli count treated as serial depth (conservative).
[ESTIMATED] formulas, not synthesized circuit counts. Scenario -> blocks (V2 16.3):
 optimistic : island detection + rank-|K| flow update + small inverse + Phi QROM + comparators + served load (NO injection update)
 realistic  : optimistic + injection update (PTDF * dP, L*B*b^2)
 pessimistic: island + QROM + injection update + comparators + served + FULL Gaussian elimination (replaces flow update and small inverse)"""
from __future__ import annotations
from math import ceil, log2

SCENARIOS = ("optimistic", "realistic", "pessimistic")

def round_components(L: int, B: int, keff: int, b: int, D: int, c_lab: float, scenario: str) -> dict:
    if scenario not in SCENARIOS: raise ValueError(f"scenario must be one of {SCENARIOS}")
    m = keff
    comp = {"island_detection": c_lab * L * D, "phi_qrom_lookups": float(m * L), "comparators_trip_update": float(L * b), "served_load_accumulation": float(B * b)}
    if scenario in ("optimistic", "realistic"):
        comp["rank_K_flow_update"] = float(L * m * b * b); comp["small_inverse"] = m ** 3 * b * b / 3.0
    if scenario in ("realistic", "pessimistic"):
        comp["injection_update_PTDF_dP"] = float(L * B * b * b)
    if scenario == "pessimistic":
        comp["full_gaussian_elimination"] = B ** 3 * b * b / 3.0
    return comp

def round_cost(*a, **kw) -> float: return float(sum(round_components(*a, **kw).values()))

def once_only_cost(L: int, k: int, b: int) -> float:
    """unranking/conversion + severity + threshold ~ O(k L log L + b) (V2: ~5e3 for IEEE-118, k=3)."""
    return float(k * L * ceil(log2(max(L, 2))) + b)

def oracle_compute_cost(L: int, B: int, k: int, R: int, keff: int, b: int, D: int, c_lab: float, scenario: str) -> float:
    """E_f: one compute of the oracle f."""
    return R * round_cost(L, B, keff, b, D, c_lab, scenario) + once_only_cost(L, k, b)

def grover_iteration_cost(E_f: float, C_D: float, L: int, uncompute_factor: float = 2.0) -> dict:
    """G = (2 E_f) + 2 C_D + C_refl. 2 E_f = compute + uncompute (Bennett); 2 C_D = U and U^dagger inside the reflection; C_refl ~ L (multi-controlled Z)."""
    parts = {"oracle_compute_and_uncompute": uncompute_factor * E_f, "dicke_prep_U_and_Udagger": 2.0 * C_D, "reflection_multicontrolled_Z": float(L)}
    return {"G": float(sum(parts.values())), "parts": parts}
