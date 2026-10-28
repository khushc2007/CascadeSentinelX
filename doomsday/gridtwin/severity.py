"""Severity metrics, V2 4.2 / 9: S, S0, C = S - S0, diagnostic A = S / max(S0, eps)."""
from __future__ import annotations

EPS_A = 0.01

def severity_metrics(served_mw_final: float, served_mw_round0: float, initial_load_mw: float):
    if initial_load_mw <= 0:
        raise ValueError("initial load must be positive")
    S = 1.0 - served_mw_final / initial_load_mw
    S0 = 1.0 - served_mw_round0 / initial_load_mw
    S, S0 = min(max(S, 0.0), 1.0), min(max(S0, 0.0), 1.0)    # clip float dust only (|x| ~ 1e-16)
    return dict(S=S, S0=S0, C=S - S0, A=S / max(S0, EPS_A))

def is_cascade_driven(S: float, C: float, tau: float, delta: float) -> bool:
    """High-severity (S >= tau) AND cascade-induced loss C >= delta (V2 4.3 problem E / 9.1)."""
    return S >= tau and C >= delta
