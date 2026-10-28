"""Configuration system: YAML -> validated nested dataclasses, plus deterministic config hash."""
from __future__ import annotations
import copy, dataclasses, hashlib, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "configs" / "default.yaml"

@dataclass
class RatingCfg:
    # family "proportional" = V2 5.3 baseline (fails the V2 5.2-step-6 N-1 requirement on IEEE-14, see docs/RATING_EXTENSION.md)
    # family "n1_covering"  = IMPLEMENTATION/CALIBRATION EXTENSION, not V2 5.3 (default)
    family: str = "n1_covering"
    headroom_h: float = 0.25
    floor_frac: float = 0.05
    n1_margin_m: float = 0.05
    # (Phase 7, E11/E3c) extra families: voltage_class (uniform rating per base-kV class), case_file (MATPOWER RATE_A);
    # perturb_frac > 0 multiplies every rating by U(1-p, 1+p) drawn with perturb_seed; dc_basis selects the DC rating base flow
    perturb_frac: float = 0.0
    perturb_seed: int = 0
    dc_basis: str = "ac_active"

@dataclass
class CascadeCfg:
    trip_factor: float = 1.0
    trip_policy: str = "all_overloaded"
    max_rounds: int = 30
    mode_default: str = "dc"
    ladder_step: float = 0.05
    redispatch: str = "up_and_down"

@dataclass
class SeverityCfg:
    tau: float = 0.20
    delta_cascade: float = 0.10

@dataclass
class QuantumCfg:
    encoding: str = "binary_dicke"
    bbht_lambda: float = 1.2
    seeds: int = 200
    patience: int = 3
    y0: float = 0.0

@dataclass
class ResourceCfg:
    b: int = 16
    R: int = 4
    k_eff: str = "3k"
    t_toffoli_us: float = 10.0
    c_q: float = 4.0
    t_classical_ms: dict = field(default_factory=lambda: {"dc": 0.5, "ac": 10})
    cores: list = field(default_factory=lambda: [1, 1000])

@dataclass
class NumericsCfg:
    ac_tol_pu: float = 1e-8
    ac_max_iter: int = 30
    overload_tol: float = 1e-9
    tie_band: float = 1e-9
    voltage_band: list = field(default_factory=lambda: [0.90, 1.10])
    float_dtype: str = "float64"
    fixed_point_bits: int | None = None   # (Phase 7, E12/V2 17.1) Q-format DC flow emulation; None = float64 (default)

@dataclass
class Config:
    grid: str = "ieee14"
    k: int = 3
    rating: RatingCfg = field(default_factory=RatingCfg)
    stress_lambda: float = 1.10
    cascade: CascadeCfg = field(default_factory=CascadeCfg)
    severity: SeverityCfg = field(default_factory=SeverityCfg)
    quantum: QuantumCfg = field(default_factory=QuantumCfg)
    resource: ResourceCfg = field(default_factory=ResourceCfg)
    numerics: NumericsCfg = field(default_factory=NumericsCfg)

RATING_FAMILIES = {"proportional", "n1_covering", "voltage_class", "case_file"}

class ConfigError(ValueError):
    pass

def _build(cls, data: dict, path: str = ""):
    if not isinstance(data, dict):
        raise ConfigError(f"{path or 'config'}: expected a mapping, got {type(data).__name__}")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = set(data) - set(fields)
    if unknown:
        raise ConfigError(f"{path or 'config'}: unknown keys {sorted(unknown)}")
    kwargs = {}
    for name, val in data.items():
        f = fields[name]
        default = f.default if f.default is not dataclasses.MISSING else f.default_factory()
        if dataclasses.is_dataclass(default):
            kwargs[name] = _build(type(default), val, f"{path}.{name}".lstrip("."))
        else:
            kwargs[name] = val
    return cls(**kwargs)

def _validate(c: Config) -> None:
    def need(cond, msg):
        if not cond:
            raise ConfigError(msg)
    need(c.k >= 1, "k must be >= 1")
    need(c.stress_lambda >= 1.0, "stress_lambda must be >= 1 (V2 5.2)")
    need(c.rating.headroom_h > 0, "rating.headroom_h must be > 0")
    need(0 <= c.rating.floor_frac < 1, "rating.floor_frac must be in [0,1)")
    need(c.rating.family in RATING_FAMILIES, f"rating.family must be one of {sorted(RATING_FAMILIES)}")
    need(0 <= c.rating.perturb_frac < 1, "rating.perturb_frac must be in [0,1)")
    need(isinstance(c.rating.perturb_seed, int), "rating.perturb_seed must be an int")
    need(c.rating.dc_basis in {"ac_active", "dc_flow"}, "rating.dc_basis must be 'ac_active' (V2 5.3) or 'dc_flow' (E3c per-engine)")
    fpb = c.numerics.fixed_point_bits
    need(fpb is None or (isinstance(fpb, int) and 6 <= fpb <= 64), "numerics.fixed_point_bits must be None or an int in [6, 64]")
    need(c.rating.n1_margin_m >= 0, "rating.n1_margin_m must be >= 0")
    need(c.cascade.trip_policy in {"all_overloaded", "most_overloaded_first"}, "bad cascade.trip_policy")
    need(c.cascade.max_rounds >= 1, "cascade.max_rounds must be >= 1")
    need(c.cascade.redispatch in {"up_and_down", "no_upward"}, "bad cascade.redispatch")
    need(c.numerics.ac_tol_pu > 0 and c.numerics.ac_max_iter >= 1, "bad AC tolerance/iterations")
    need(c.numerics.overload_tol >= 0 and c.numerics.tie_band >= 0, "tolerances must be >= 0")
    vb = c.numerics.voltage_band
    need(len(vb) == 2 and 0 < vb[0] < vb[1], "numerics.voltage_band must be [lo, hi]")
    need(c.numerics.float_dtype == "float64", "V2 8.8 requires float64 throughout")

def config_to_dict(c: Config) -> dict:
    return dataclasses.asdict(c)

def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out

def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    """Load defaults (configs/default.yaml), optionally a user YAML, then overrides; validate."""
    data = config_to_dict(Config())
    for p in ([DEFAULT_PATH] if DEFAULT_PATH.exists() else []) + ([Path(path)] if path else []):
        with open(p) as fh:
            data = _merge(data, yaml.safe_load(fh) or {})
    if overrides:
        data = _merge(data, overrides)
    cfg = _build(Config, data)
    _validate(cfg)
    return cfg

def config_hash(cfg: Config | dict) -> str:
    """Deterministic SHA-256 of the canonical JSON form (sorted keys, fixed separators)."""
    d = config_to_dict(cfg) if isinstance(cfg, Config) else cfg
    blob = json.dumps(d, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()
