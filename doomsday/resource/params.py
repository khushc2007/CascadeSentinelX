"""Model parameters with explicit PROVENANCE. Every value says where it comes from, so measured values, V2 placeholders, assumptions and
estimates can never be confused."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict

SRC_V2 = "V2 placeholder/default (design-stage; not measured)"
SRC_ASSUMPTION = "assumption made in this implementation"
SRC_MEASURED_EMU = "measured on IEEE-14 Tier B EMULATION (unverified grid data; ideal amplitude amplification; tiny N)"
SRC_INFORMAL = "informal diagnostic (NOT an E1 measurement)"
SRC_BACKSOLVED = "back-solved from a V2 printed figure"

@dataclass
class ModelParams:
    b: int = 16                      # fixed-point bits                       V2 App. A (to be set by E12; not run)
    R: int = 4                       # cascade rounds in the oracle            V2 placeholder (E2 not run at 118)
    k_eff_factor: float = 3.0        # keff = factor * k                       V2 placeholder 3k
    D: int = 20                      # graph diameter (island detection)       V2 illustration for IEEE-118
    c_lab: float = 19.0              # label-propagation constant              back-solved: 7e4 / (186*20)
    c_rot: float = 20.0              # Toffoli-eq per synthesized rotation     V2 11.3: 10-30
    and_overhead: float = 2.0        # tree prep: Toffolis per control (compute+uncompute)   ASSUMPTION
    t_toffoli_s: float = 10e-6       # logical Toffoli time                    V2 realistic 10 us (sweep 1-100)
    c_q: float = 4.0                 # Q = c_q*sqrt(N/M) oracle calls          V2 placeholder (E6: emulated measurement available for IEEE-14)
    t_classical_s: float = 0.5e-3    # classical time per evaluation (DC)      V2 placeholder (E1 not run)
    P: int = 1                       # classical cores
    Pq: int = 1                      # quantum processors
    kappa: float = 1.0               # classical evaluations = kappa * N^alpha
    alpha: float = 1.0               # exhaustive search: alpha = 1
    uncompute_factor: float = 2.0    # 2 = full Bennett (compute + uncompute); <2 only where measurement-based uncomputation is valid
    c_tail: float = 0.0              # certified-stop tail: + c_tail*sqrt(N) quantum calls (patience schedules); 0 = V2 model (not modelled)
    verif_per_qcall: float = 0.5     # classical verifications per quantum oracle call (measured 0.30-0.55 in IEEE-14 emulation)
    p_ratio: float = 0.1             # physical/threshold error ratio          V2 16.4
    logical_budget_eps: float = 0.1  # total logical failure budget            ASSUMPTION
    factory_routing_overhead: float = 0.5   # extra physical qubits for factories+routing (fraction)   ASSUMPTION (V2: not modelled in detail)
    provenance: dict = field(default_factory=lambda: {
        "b": SRC_V2, "R": SRC_V2, "k_eff_factor": SRC_V2, "D": SRC_V2, "c_lab": SRC_BACKSOLVED, "c_rot": SRC_V2, "and_overhead": SRC_ASSUMPTION,
        "t_toffoli_s": SRC_V2, "c_q": SRC_V2, "t_classical_s": SRC_V2, "P": SRC_V2, "Pq": SRC_V2, "kappa": SRC_V2, "alpha": SRC_V2,
        "uncompute_factor": SRC_V2, "c_tail": SRC_V2 + " (V2 has no stop-rule term)", "verif_per_qcall": SRC_MEASURED_EMU, "p_ratio": SRC_V2, "logical_budget_eps": SRC_ASSUMPTION,
        "factory_routing_overhead": SRC_ASSUMPTION})
    def with_(self, source: str | None = None, **kw) -> "ModelParams":
        d = asdict(self); prov = dict(d.pop("provenance"))
        for k, v in kw.items():
            if k not in d: raise KeyError(k)
            d[k] = v; prov[k] = source or SRC_ASSUMPTION + " (override)"
        return ModelParams(**d, provenance=prov)
    def to_dict(self) -> dict: return asdict(self)
    def keff(self, k: int) -> int: return int(round(self.k_eff_factor * k))

def from_config_resource(resource_cfg: dict) -> ModelParams:
    """Build from the `resource:` section of configs/default.yaml (a plain dict; no config import needed)."""
    kw = {}
    if "b" in resource_cfg: kw["b"] = int(resource_cfg["b"])
    if "R" in resource_cfg: kw["R"] = int(resource_cfg["R"])
    if "t_toffoli_us" in resource_cfg: kw["t_toffoli_s"] = resource_cfg["t_toffoli_us"] * 1e-6
    if "c_q" in resource_cfg: kw["c_q"] = float(resource_cfg["c_q"])
    if "t_classical_ms" in resource_cfg: kw["t_classical_s"] = resource_cfg["t_classical_ms"]["dc"] * 1e-3
    ke = str(resource_cfg.get("k_eff", "3k"))
    if ke.endswith("k"): kw["k_eff_factor"] = float(ke[:-1] or 1)
    return ModelParams().with_(source=SRC_V2 + " (configs/default.yaml)", **kw)
