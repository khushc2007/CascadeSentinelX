"""Transparent oracle-call accounting for Tier B (V2 12.2 / 12.3).
QUANTUM oracle calls (conservative): an attempt with j Grover iterations then a measurement costs j+1 (j iterations + one marking check).
CLASSICAL verifications: after each measurement the outcome is checked with one classical evaluation; reported separately.
table_construction_evals: building the predicate table needs N classical evaluations -- Tier B emulates dynamics, not realisability;
these are NEVER part of the quantum count and must be reported next to it."""
from __future__ import annotations

class QuantumCounter:
    def __init__(self, table_construction_evals: int = 0):
        self.quantum_oracle_calls = 0; self.grover_iterations = 0; self.attempts = 0; self.measurements = 0
        self.verifications = 0; self._unique: set = set(); self.table_construction_evals = int(table_construction_evals); self.log: list = []
    def attempt(self, j: int):
        self.attempts += 1; self.measurements += 1; self.grover_iterations += j; self.quantum_oracle_calls += j + 1
    def verify(self, x: int):
        self.verifications += 1; self._unique.add(int(x))
    @property
    def unique_verifications(self) -> int: return len(self._unique)
    @property
    def total_conservative(self) -> int: return self.quantum_oracle_calls + self.verifications
    def to_dict(self) -> dict:
        return {"quantum_oracle_calls": self.quantum_oracle_calls, "grover_iterations": self.grover_iterations, "attempts": self.attempts,
                "measurements": self.measurements, "classical_verifications": self.verifications, "unique_verifications": self.unique_verifications,
                "total_conservative_quantum_plus_verifications": self.total_conservative, "table_construction_evals": self.table_construction_evals}
