"""Internal Grid representation (V2 5.1). The engine never touches a third-party grid object."""
from __future__ import annotations
from dataclasses import dataclass, replace
import numpy as np

PQ, PV, SLACK = 1, 2, 3

@dataclass(frozen=True)
class Grid:
    name: str
    base_mva: float
    source: dict
    # bus table (0-based internal index; bus_id keeps the case-file id)
    bus_id: np.ndarray
    bus_type: np.ndarray
    Pd: np.ndarray        # MW
    Qd: np.ndarray        # MVAr
    Gs: np.ndarray        # MW at V=1
    Bs: np.ndarray        # MVAr at V=1
    Vmin: np.ndarray
    Vmax: np.ndarray
    # branch table (order fixed by the case file; every branch is one decision bit)
    br_from: np.ndarray
    br_to: np.ndarray
    r: np.ndarray         # p.u.
    x: np.ndarray
    b: np.ndarray         # total line charging, p.u.
    tap: np.ndarray       # effective ratio (1.0 for plain lines)
    shift: np.ndarray     # rad
    br_status: np.ndarray # 1 in service
    br_is_transformer: np.ndarray
    rate_a_case: np.ndarray  # MVA from the case file (0 = none)
    rating_ac: np.ndarray    # MVA, NaN until synthesised
    rating_dc: np.ndarray    # MW,  NaN until synthesised
    # generator table
    gen_bus: np.ndarray
    gen_Pg: np.ndarray
    gen_Qg: np.ndarray
    gen_Pmax: np.ndarray
    gen_Pmin: np.ndarray
    gen_Qmax: np.ndarray
    gen_Qmin: np.ndarray
    gen_Vset: np.ndarray
    gen_status: np.ndarray
    load_scale: float = 1.0
    bus_base_kv: np.ndarray | None = None   # (Phase 7) MATPOWER BASE_KV; used only by rating.family=voltage_class

    @property
    def n_bus(self) -> int: return len(self.bus_id)
    @property
    def n_branch(self) -> int: return len(self.br_from)
    @property
    def n_gen(self) -> int: return len(self.gen_bus)
    @property
    def slack_bus(self) -> int: return int(np.flatnonzero(self.bus_type == SLACK)[0])
    @property
    def total_load_mw(self) -> float: return float(self.Pd.sum())

    def with_(self, **changes) -> "Grid":
        return replace(self, **changes)

    def branch_label(self, l: int) -> str:
        return f"{int(self.bus_id[self.br_from[l]])}-{int(self.bus_id[self.br_to[l]])}"

    def bus_gen_pg_mw(self) -> np.ndarray:
        out = np.zeros(self.n_bus)
        np.add.at(out, self.gen_bus, np.where(self.gen_status > 0, self.gen_Pg, 0.0))
        return out

    def validate(self) -> None:
        nb, nl = self.n_bus, self.n_branch
        if np.count_nonzero(self.bus_type == SLACK) != 1:
            raise ValueError("grid must have exactly one slack bus")
        if np.any((self.br_from < 0) | (self.br_from >= nb) | (self.br_to < 0) | (self.br_to >= nb)):
            raise ValueError("branch endpoint out of range")
        if np.any(self.br_from == self.br_to):
            raise ValueError("self-loop branch")
        if np.any(self.x == 0):
            raise ValueError("zero-reactance branch (DC model needs x != 0)")
        for arr in (self.r, self.x, self.b, self.tap, self.br_status, self.rating_ac, self.rating_dc):
            if len(arr) != nl:
                raise ValueError("branch table length mismatch")
        if np.any((self.gen_bus < 0) | (self.gen_bus >= nb)):
            raise ValueError("generator bus out of range")
