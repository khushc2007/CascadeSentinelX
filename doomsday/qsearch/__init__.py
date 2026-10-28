"""Quantum-search components (V2 11-13). Depends ONLY on doomsday.oracle.interface.
EVIDENCE CLASSES in this package:
  statevec / dicke / circuits / toy  -> NumPy statevector SIMULATION of toy circuits (a classical program; not a quantum device, not Aer)
  emulation / grover / bbht / dh_gas -> Tier B EXACT CLASSICAL EMULATION of ideal amplitude amplification (not a quantum runtime)
  qiskit_export                      -> exporter; Aer execution status is recorded by scripts/aer_*.py (NOT RUN in the authoring sandbox)
Nothing here demonstrates quantum speedup or advantage."""
