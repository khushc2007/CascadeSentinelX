"""M is table-derived (Tier B) or modelled (Tier C); quantum counting itself is not implemented."""
from __future__ import annotations
from math import pi, sqrt
from .predicate import PredicateTable

def marked_count(pt: PredicateTable, tau: float) -> int: return pt.marked_ge(tau).M
def expected_grover_calls(N: int, M: int) -> float: return (pi / 4) * sqrt(N / M) if M else float("inf")
