"""Reversible (classical-basis) circuit toolkit for the A2 micro-oracle (V2 13.4). Gates are multi-controlled X with optional negative controls
(X, CNOT, Toffoli, MCX). A reversible circuit permutes basis states, so exhaustive verification is a bit-level simulation on all inputs
(numpy, vectorised over inputs). Toffoli-equivalent cost convention: CCX = 1; MCX with c >= 3 controls = 2c - 3 (ladder with c - 2 clean
ancillas); X/CNOT = 0 (Clifford). Every gate is tagged with the primitive that emitted it, so counts are reported per primitive.

Ancillas come from a pool; a qubit is returned to the pool only by code that has restored it to |0>, and the exhaustive simulation checks
that EVERY non-input, non-output qubit ends in |0> (V2 13.4 verification (ii))."""
from __future__ import annotations
from contextlib import contextmanager
import numpy as np

def toffoli_equiv(n_controls: int) -> int:
    return 0 if n_controls < 2 else (1 if n_controls == 2 else 2 * n_controls - 3)

class RevCircuit:
    def __init__(self):
        self.n = 0; self.gates: list = []; self.regs: dict = {}; self._pool: list = []; self._tag = ["untagged"]; self.peak_pool = 0
    # ---- allocation ----------------------------------------------------------------------------------------------------------------
    def register(self, name: str, width: int) -> list:
        """Permanent named register (never pooled)."""
        q = list(range(self.n, self.n + width)); self.n += width; self.regs[name] = q; return q
    def borrow(self, width: int) -> list:
        out = []
        for _ in range(width):
            if self._pool: out.append(self._pool.pop())
            else: out.append(self.n); self.n += 1
        return out
    def release(self, qubits) -> None:
        """Caller guarantees the qubits are |0> again (verified globally by simulation)."""
        self._pool.extend(reversed(list(qubits)))
    @contextmanager
    def tag(self, name: str):
        self._tag.append(name)
        try: yield
        finally: self._tag.pop()
    # ---- gates ---------------------------------------------------------------------------------------------------------------------
    def mcx(self, controls, target: int) -> None:
        """controls: iterable of qubit (positive) or (qubit, polarity) with polarity 1 = control on |1>, 0 = control on |0>."""
        cs = tuple((c, 1) if isinstance(c, (int, np.integer)) else (int(c[0]), int(c[1])) for c in controls)
        if any(q == target for q, _ in cs) or len({q for q, _ in cs}) != len(cs): raise ValueError("control/target overlap or duplicate control")
        self.gates.append((cs, int(target), self._tag[-1]))
    def x(self, t): self.mcx((), t)
    def cx(self, c, t): self.mcx((c,), t)
    def ccx(self, a, b, t): self.mcx((a, b), t)
    # ---- analysis ------------------------------------------------------------------------------------------------------------------
    def inverse_gates(self, gates=None) -> list:
        return list(reversed(self.gates if gates is None else gates))           # every MCX is self-inverse
    def counts(self, gates=None) -> dict:
        out: dict = {}
        for cs, _, tg in (self.gates if gates is None else gates):
            d = out.setdefault(tg, {"gates": 0, "toffoli_equiv": 0, "by_n_controls": {}})
            d["gates"] += 1; d["toffoli_equiv"] += toffoli_equiv(len(cs)); d["by_n_controls"][len(cs)] = d["by_n_controls"].get(len(cs), 0) + 1
        out["TOTAL"] = {"gates": sum(v["gates"] for v in out.values()), "toffoli_equiv": sum(v["toffoli_equiv"] for v in out.values())}
        return out

def simulate(n: int, gates, states: np.ndarray) -> np.ndarray:
    """states: (n_inputs, n) uint8 bit matrix; returns the permuted states (copy)."""
    st = np.array(states, dtype=np.uint8, copy=True)
    if st.shape[1] < n: st = np.hstack([st, np.zeros((st.shape[0], n - st.shape[1]), np.uint8)])
    for cs, t, _ in gates:
        if not cs: st[:, t] ^= 1; continue
        m = np.ones(st.shape[0], bool)
        for q, pol in cs: m &= st[:, q] == pol
        st[m, t] ^= 1
    return st

# ---- arithmetic primitives (two's complement, little-endian bit lists) -----------------------------------------------------------------
def add_into(c: RevCircuit, a, b, ctrl=None) -> None:
    """b <- b + a (mod 2^len(b)); `a` is read-only and may contain repeated qubits (sign extension). len(a) == len(b).
    Vedral-Barenco-Ekert ripple-carry without the final carry-out; carries borrowed from the pool and restored."""
    n = len(b)
    if len(a) != n: raise ValueError("operand widths differ")
    if ctrl is not None:                                                      # controlled add = mask the operand with the control (n Toffolis),
        uniq = list(dict.fromkeys(a)); m = c.borrow(len(uniq)); mp = dict(zip(uniq, m))   # uncontrolled add, unmask (standard construction)
        for q in uniq: c.ccx(q, ctrl, mp[q])
        add_into(c, [mp[q] for q in a], b)
        for q in uniq: c.ccx(q, ctrl, mp[q])
        c.release(m); return
    C = lambda *qs: tuple(qs)
    if n == 1:
        c.mcx(C(a[0]), b[0]); return
    car = c.borrow(n - 1); cq = [None] + car                                  # cq[i] = carry into bit i (cq[0] = 0, implicit)
    def carry(i):                                                             # computes cq[i+1] from (cq[i], a_i, b_i); leaves b_i ^= a_i
        c.mcx(C(a[i], b[i]), cq[i + 1]); c.mcx(C(a[i]), b[i])
        if i > 0: c.mcx(C(cq[i], b[i]), cq[i + 1])
    def carry_dag(i):
        if i > 0: c.mcx(C(cq[i], b[i]), cq[i + 1])
        c.mcx(C(a[i]), b[i]); c.mcx(C(a[i], b[i]), cq[i + 1])
    def sumb(i):
        c.mcx(C(a[i]), b[i])
        if i > 0: c.mcx(C(cq[i]), b[i])
    for i in range(n - 1): carry(i)
    sumb(n - 1)
    for i in range(n - 2, -1, -1): carry_dag(i); sumb(i)
    c.release(car)

def load_const(c: RevCircuit, reg, value: int, ctrl=None) -> None:
    for i, q in enumerate(reg):
        if (value >> i) & 1:
            if ctrl is None: c.x(q)
            else: c.cx(ctrl, q)

def add_const(c: RevCircuit, value: int, b, ctrl=None) -> None:
    """b <- b + value (mod 2^len(b)), optionally controlled."""
    n = len(b); v = value % (1 << n); k = c.borrow(n); load_const(c, k, v); add_into(c, k, b, ctrl); load_const(c, k, v); c.release(k)

def mul_acc_signed_unsigned(c: RevCircuit, a, p, acc) -> None:
    """acc <- acc + a * p (mod 2^len(acc)); a signed (two's complement, sign = a[-1]), p unsigned; shift-and-add with controlled adders."""
    w = len(acc)
    for j in range(len(p)):
        opnd = [a[i - j] if i - j < len(a) else a[-1] for i in range(j, w)]   # sign-extended a, shifted by j
        add_into(c, opnd, acc[j:], ctrl=p[j])

def sign_of_plus_const(c: RevCircuit, x, K: int, out) -> None:
    """out ^= sign(x + K) for signed x (len w), computed in w+1 bits; all temporaries restored."""
    w = len(x) + 1; t = c.borrow(w)
    for i in range(w): c.cx(x[min(i, len(x) - 1)], t[i])                    # sign-extended copy
    add_const(c, K, t); c.cx(t[-1], out); add_const(c, -K, t)
    for i in range(w): c.cx(x[min(i, len(x) - 1)], t[i])
    c.release(t)

def or_into(c: RevCircuit, terms, out) -> None:
    """out ^= OR(terms) = NOT AND(NOT terms)."""
    if not terms: return
    c.mcx(tuple((q, 0) for q in terms), out); c.x(out)
