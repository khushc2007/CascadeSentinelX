from .cascade_oracle import CascadeOracle

class DCOracle(CascadeOracle):
    """Search predicate S_DC(x): DC quasi-steady-state cascade (V2 A6: the quantum predicate is the DC cascade)."""
    fidelity = "dc"
