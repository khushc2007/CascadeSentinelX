"""Export of simulator circuits to Qiskit. Qiskit is imported LAZILY; nothing here has been executed against Qiskit in the authoring sandbox
(qiskit is not installed there). The op->gate mapping is unit-tested against a RecordingBuilder only. UNVERIFIED against Qiskit semantics:
(i) ctrl_state integer ordering (assumed: bit i <-> i-th control qubit in the list), (ii) qubit/bit ordering of measured bitstrings
(assumed little-endian: qubit 0 = rightmost character)."""
from __future__ import annotations
from .statevec import Circuit

class RecordingBuilder:
    """API-compatible recorder used to test the exporter without Qiskit."""
    def __init__(self, n): self.n, self.calls = n, []
    def x(self, q): self.calls.append(("x", q))
    def h(self, q): self.calls.append(("h", q))
    def ry(self, q, theta): self.calls.append(("ry", q, theta))
    def cx(self, c, t): self.calls.append(("cx", c, t))
    def mcry(self, controls, target, theta, ctrl_state): self.calls.append(("mcry", tuple(controls), target, theta, ctrl_state))
    def mcz(self, qubits): self.calls.append(("mcz", tuple(qubits)))
    def finish(self): return self.calls

class QiskitBuilder:
    def __init__(self, n):
        from qiskit import QuantumCircuit            # lazy; raises ImportError if absent
        self.qc = QuantumCircuit(n)
    def x(self, q): self.qc.x(q)
    def h(self, q): self.qc.h(q)
    def ry(self, q, theta): self.qc.ry(theta, q)
    def cx(self, c, t): self.qc.cx(c, t)
    def mcry(self, controls, target, theta, ctrl_state):
        from qiskit.circuit.library import RYGate
        self.qc.append(RYGate(theta).control(len(controls), ctrl_state=ctrl_state, annotated=False), list(controls) + [target])
    def mcz(self, qubits):
        from qiskit.circuit.library import ZGate
        qs = list(qubits)
        if len(qs) == 1: self.qc.z(qs[0])
        else: self.qc.append(ZGate().control(len(qs) - 1, annotated=False), qs)
    def finish(self): return self.qc

def export(circ: Circuit, builder):
    for o in circ.ops:
        if o.name == "x": builder.x(o.qubits[0])
        elif o.name == "h": builder.h(o.qubits[0])
        elif o.name == "ry": builder.ry(o.qubits[0], o.theta)
        elif o.name == "cx": builder.cx(*o.qubits)
        elif o.name == "mcry":
            ctrls = [q for q, _ in o.controls]; cs = sum(v << i for i, (_, v) in enumerate(o.controls))
            builder.mcry(ctrls, o.qubits[0], o.theta, cs)
        elif o.name == "mcz": builder.mcz(o.qubits)
        else: raise ValueError(o.name)
    return builder.finish()

def to_qiskit(circ: Circuit):
    return export(circ, QiskitBuilder(circ.n))
