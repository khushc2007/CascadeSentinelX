from .cascade_oracle import CascadeOracle

class ACOracle(CascadeOracle):
    """Verification oracle S_AC(x) (reports S_ladder; S_total, ladder flags in evaluate()). Never priced as a quantum oracle."""
    fidelity = "ac"
