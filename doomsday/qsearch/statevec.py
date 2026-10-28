"""Minimal NumPy statevector simulator + circuit representation for TOY verification (n <= ~14 qubits).
Convention (little-endian, like Qiskit): basis index b = sum_q x_q 2^q, i.e. qubit q is bit q of the index.
Gate set: x, h, ry(theta), cx, mcry(controls=[(qubit, required_value)], target, theta), mcz(qubits) (phase -1 on all-ones).
This is a CLASSICAL SIMULATION used to verify circuit logic; it is not an Aer/Qiskit run."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Op:
    name: str
    qubits: tuple            # x,h,ry: (t,); cx: (c,t); mcry: (target,) ; mcz: all qubits
    theta: float = 0.0
    controls: tuple = ()     # mcry only: ((qubit, value), ...)

class Circuit:
    def __init__(self, n: int, ops=None):
        self.n = int(n); self.ops: list = list(ops or [])
    def _chk(self, *qs):
        for q in qs:
            if not (isinstance(q, (int, np.integer)) and 0 <= q < self.n): raise ValueError(f"bad qubit {q!r} for n={self.n}")
        if len(set(qs)) != len(qs): raise ValueError(f"repeated qubit in {qs}")
    def x(self, q): self._chk(q); self.ops.append(Op("x", (int(q),))); return self
    def h(self, q): self._chk(q); self.ops.append(Op("h", (int(q),))); return self
    def ry(self, q, theta): self._chk(q); self.ops.append(Op("ry", (int(q),), float(theta))); return self
    def cx(self, c, t): self._chk(c, t); self.ops.append(Op("cx", (int(c), int(t)))); return self
    def mcry(self, controls, t, theta):
        cs = tuple((int(q), int(v)) for q, v in controls); self._chk(t, *[q for q, _ in cs])
        if any(v not in (0, 1) for _, v in cs): raise ValueError("control values must be 0/1")
        self.ops.append(Op("mcry", (int(t),), float(theta), cs)); return self
    def mcz(self, qubits): qs = tuple(int(q) for q in qubits); self._chk(*qs); self.ops.append(Op("mcz", qs)); return self
    def extend(self, other: "Circuit"):
        if other.n != self.n: raise ValueError("qubit-count mismatch")
        self.ops += other.ops; return self
    def inverse(self) -> "Circuit":
        inv = []
        for o in reversed(self.ops):
            inv.append(Op(o.name, o.qubits, -o.theta, o.controls) if o.name in ("ry", "mcry") else o)   # x,h,cx,mcz are self-inverse
        return Circuit(self.n, inv)
    def counts(self) -> dict:
        c: dict = {}
        for o in self.ops:
            key = o.name if o.name != "mcry" else f"mcry[{len(o.controls)}ctrl]"
            c[key] = c.get(key, 0) + 1
        c["total"] = len(self.ops); return c
    def __len__(self): return len(self.ops)

_IDX: dict = {}
def _idx(n):
    if n not in _IDX: _IDX[n] = np.arange(1 << n)
    return _IDX[n]

def apply_op(state: np.ndarray, n: int, o: Op) -> None:
    """In-place application of one op to a complex statevector of length 2**n."""
    idx = _idx(n)
    if o.name == "x":
        t = o.qubits[0]; i0 = idx[((idx >> t) & 1) == 0]; i1 = i0 | (1 << t); state[i0], state[i1] = state[i1].copy(), state[i0].copy()
    elif o.name == "h":
        t = o.qubits[0]; i0 = idx[((idx >> t) & 1) == 0]; i1 = i0 | (1 << t); a, b = state[i0].copy(), state[i1].copy()
        r = 1 / np.sqrt(2); state[i0] = r * (a + b); state[i1] = r * (a - b)
    elif o.name in ("ry", "mcry"):
        t = o.qubits[0]; m = ((idx >> t) & 1) == 0
        for q, v in o.controls: m &= ((idx >> q) & 1) == v
        i0 = idx[m]; i1 = i0 | (1 << t); a, b = state[i0].copy(), state[i1].copy(); c, s = np.cos(o.theta / 2), np.sin(o.theta / 2)
        state[i0] = c * a - s * b; state[i1] = s * a + c * b
    elif o.name == "cx":
        c, t = o.qubits; m = (((idx >> c) & 1) == 1) & (((idx >> t) & 1) == 0); i0 = idx[m]; i1 = i0 | (1 << t)
        state[i0], state[i1] = state[i1].copy(), state[i0].copy()
    elif o.name == "mcz":
        m = np.ones(1 << n, bool)
        for q in o.qubits: m &= ((idx >> q) & 1) == 1
        state[m] *= -1
    else:
        raise ValueError(f"unknown op {o.name}")

def run(circ: Circuit, state: np.ndarray | None = None) -> np.ndarray:
    st = np.zeros(1 << circ.n, dtype=complex) if state is None else np.array(state, dtype=complex)
    if state is None: st[0] = 1.0
    for o in circ.ops: apply_op(st, circ.n, o)
    return st

def basis_state(n: int, bits_one) -> np.ndarray:
    st = np.zeros(1 << n, dtype=complex); st[sum(1 << q for q in bits_one)] = 1.0; return st

def unitary(circ: Circuit) -> np.ndarray:
    """Full 2^n x 2^n matrix (columns = images of basis states). Practical for n <= 9."""
    if circ.n > 10: raise ValueError("unitary() is for toy sizes only")
    U = np.zeros((1 << circ.n, 1 << circ.n), dtype=complex)
    for b in range(1 << circ.n):
        st = np.zeros(1 << circ.n, dtype=complex); st[b] = 1; U[:, b] = run(circ, st)
    return U

def ascii_diagram(circ: Circuit, max_ops: int = 40) -> str:
    """Plain-text circuit diagram (qubit 0 on top): X, H, Ry(theta), '@'=control(1), 'o'=control(0), '+'=CNOT target, 'Z'=MCZ member."""
    cols = []
    for o in circ.ops[:max_ops]:
        col = ["-"] * circ.n; lab = {"x": "X", "h": "H", "ry": "Ry", "mcz": "Z"}.get(o.name)
        if o.name in ("x", "h", "ry"): col[o.qubits[0]] = lab
        elif o.name == "cx": col[o.qubits[0]] = "@"; col[o.qubits[1]] = "+"
        elif o.name == "mcry":
            for q, v in o.controls: col[q] = "@" if v else "o"
            col[o.qubits[0]] = "Ry"
        elif o.name == "mcz":
            for q in o.qubits: col[q] = "Z"
        cols.append(col)
    w = 3
    rows = [f"q{q}: " + "".join(c[q].center(w, "-") for c in cols) for q in range(circ.n)]
    tail = f"\n... ({len(circ.ops) - max_ops} more ops)" if len(circ.ops) > max_ops else ""
    return "\n".join(rows) + tail
