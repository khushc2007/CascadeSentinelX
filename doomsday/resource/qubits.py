"""Logical and physical qubit estimates (V2 16.4). [ESTIMATED], bound quality: factory footprint, routing, T-count vs Toffoli accounting and the
code-distance dependence on volume are NOT modelled in detail (V2). The physical estimate below uses an explicit simple surface-code model."""
from __future__ import annotations
from math import ceil, comb, log2

def logical_qubits(L: int, B: int, keff: int, b: int, R: int, scenario: str, search_register: int | None = None, workspace: int | None = None) -> dict:
    """Realistic (V2): in-service register + R retained flow/trip registers R*(L*b+L) + held Phi columns m*L*b + arithmetic workspace.
    Optimistic: Phi columns are streamed (not held). Pessimistic: also holds the dense B^2*b matrix."""
    sr = L if search_register is None else search_register                 # Dicke register = L qubits
    ws = 4 * b if workspace is None else workspace                         # ASSUMPTION: a few b-bit scratch registers
    parts = {"search_register": sr, "in_service_register": L, "retained_round_registers": R * (L * b + L), "arithmetic_workspace": ws}
    if scenario in ("realistic", "pessimistic"): parts["held_phi_columns"] = keff * L * b
    if scenario == "pessimistic": parts["dense_matrix"] = B * B * b
    return {"total": int(sum(parts.values())), "parts": {k: int(v) for k, v in parts.items()}}

def code_distance(volume: float, p_ratio: float = 0.1, eps: float = 0.1, prefactor: float = 0.1, spacetime_logical_qubits: float = 1.0) -> int:
    """Smallest odd d with  spacetime_logical_qubits * volume * prefactor * p_ratio^((d+1)/2) <= eps  (simple surface-code model; ESTIMATE)."""
    d = 3
    while spacetime_logical_qubits * volume * prefactor * p_ratio ** ((d + 1) / 2) > eps:
        d += 2
        if d > 201: raise ValueError("code distance > 201: model not meaningful")
    return d

def physical_qubits(n_logical: int, volume: float, p_ratio: float = 0.1, eps: float = 0.1, overhead: float = 0.5, conservative: bool = False) -> dict:
    """phys = n_logical * 2 d^2 * (1 + overhead). 'conservative' multiplies the failure volume by n_logical (every logical qubit idles every Toffoli step)."""
    d = code_distance(volume, p_ratio, eps, spacetime_logical_qubits=n_logical if conservative else 1.0)
    return {"code_distance": d, "physical_per_logical": 2 * d * d, "physical_total": float(n_logical * 2 * d * d * (1 + overhead)),
            "criterion": "volume*n_logical" if conservative else "volume (V2 convention)"}
