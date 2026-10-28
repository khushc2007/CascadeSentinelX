"""Dicke-state preparation, EXACT. Two constructions: (a) explicit-amplitude binary tree of multiplexed RY rotations (default, Phases 1-6);
(b) Phase 8: the Baertschi-Eidenbenz O(kn) split-and-cyclic-shift circuit, reconstructed and numerically verified (see below).
HISTORICAL NOTE (Phases 5-6, superseded by (b) in Phase 8):
DEVIATION FROM V2 (documented): V2 11.3 specifies the Baertschi-Eidenbenz O(kL)-gate construction. A reconstruction of its gate list from
memory failed numerical verification under 24+8 convention variants (see docs/QUANTUM_TIERS.md), so it is NOT used. V2 names this
explicit-amplitude preparation as the exact fallback for toy sizes. Its gate count is O(2^n) (reported by gate_counts), so V2's
resource-model term C_D ~ k*L*c_rot is NOT supported by this implementation."""
from __future__ import annotations
from math import comb
import numpy as np
from .statevec import Circuit

def dicke_state(n: int, k: int) -> np.ndarray:
    """Analytic |D_k^n> as a real vector in the little-endian basis (support: Hamming weight k)."""
    if not 0 <= k <= n: raise ValueError("need 0 <= k <= n")
    v = np.array([1.0 if bin(i).count("1") == k else 0.0 for i in range(1 << n)])
    return v / np.sqrt(comb(n, k))

def amplitude_tree_circuit(amps: np.ndarray, n: int) -> Circuit:
    """Circuit mapping |0...0> -> sum_b amps[b] |b> for REAL NON-NEGATIVE amps (unit norm). Qubits are fixed from the most significant
    (n-1) down to 0; qubit q is rotated by RY(2*atan2(sqrt(P1), sqrt(P0))) with controls on the already-fixed higher qubits (value-0
    controls are genuine 'open' controls). Branches with zero probability are skipped."""
    a = np.asarray(amps, dtype=float)
    if a.shape != (1 << n,) or np.any(a < -1e-15) or abs(np.linalg.norm(a) - 1) > 1e-10: raise ValueError("amps must be a unit-norm non-negative vector of length 2^n")
    p = a ** 2; c = Circuit(n)
    for q in range(n - 1, -1, -1):
        for prefix in range(1 << (n - 1 - q)):                         # value of qubits n-1..q+1
            lo = prefix << (q + 1)
            blk = p[lo: lo + (1 << (q + 1))]                           # indices sharing that prefix: bit q is the next-highest varying bit
            p0, p1 = blk[: 1 << q].sum(), blk[1 << q:].sum()
            if p0 + p1 < 1e-300: continue
            theta = 2 * np.arctan2(np.sqrt(p1), np.sqrt(p0))
            if abs(theta) < 1e-15: continue
            ctrls = [(qq, (prefix >> (qq - q - 1)) & 1) for qq in range(q + 1, n)]
            c.mcry(ctrls, q, theta)
    return c

def dicke_tree_circuit(n: int, k: int) -> Circuit:
    """|0^n> -> |D_k^n>."""
    return amplitude_tree_circuit(dicke_state(n, k), n)

def dicke_prep_from_reference(n: int, k: int) -> Circuit:
    """V2 convention: U |1^k 0^(n-k)> = |D_k^n>, with the k ones on qubits 0..k-1. U = Tree . X^{ref}."""
    c = Circuit(n)
    for q in range(k): c.x(q)
    return c.extend(dicke_tree_circuit(n, k))

def gate_counts(n: int, k: int) -> dict:
    return dicke_prep_from_reference(n, k).counts()


# ---- (Phase 8) Baertschi-Eidenbenz split-and-cyclic-shift construction, V2 11.3 -------------------------------------------------------
# Reconstructed in Phase 8 and VERIFIED NUMERICALLY (tests/quantum/test_be_dicke.py: infidelity <= 1e-14 for every 0 <= k <= n <= 10 against
# the analytic Dicke vector, support only on weight k). Gate structure (1-indexed qubits i = 1..n, mapped to circuit qubit n - i so that the
# reference |0^(n-k) 1^k> of the paper is V2's |1^k 0^(n-k)> with ones on qubits 0..k-1):
#   U_{n,k} = SCS_{2,1} ... SCS_{k,k-1} . SCS_{k+1,k} ... SCS_{n,k}      (SCS_{n,k} applied first)
#   SCS_{m,k}: block(2 qubits: m-1, m; angle 2 acos sqrt(1/m)) then for l = 2..k block(3 qubits: m-l, m-l+1, m; angle 2 acos sqrt(l/m)),
#   each block = CX(a -> m) . RY_a(angle | controls m [, m-l+1]) . CX(a -> m).
# Gate count: (n-k)k + k(k-1)/2 blocks, i.e. O(kn) -- the cost model's C_D ~ k L c_rot rests on THIS construction (V2 11.3).
from math import acos, sqrt as _sqrt

def _be_q(n, i): return n - i

def _scs(c: Circuit, n_tot: int, m: int, k: int) -> None:
    q = lambda i: _be_q(n_tot, i)
    c.cx(q(m - 1), q(m)); c.mcry([(q(m), 1)], q(m - 1), 2 * acos(_sqrt(1 / m))); c.cx(q(m - 1), q(m))
    for l in range(2, k + 1):
        c.cx(q(m - l), q(m)); c.mcry([(q(m), 1), (q(m - l + 1), 1)], q(m - l), 2 * acos(_sqrt(l / m))); c.cx(q(m - l), q(m))

def be_unitary_from_reference(n: int, k: int) -> Circuit:
    """U with U|1^k 0^(n-k)> = |D_k^n> (ones on qubits 0..k-1, V2 convention). No X gates: the reference must already be prepared."""
    if not 0 <= k <= n: raise ValueError("need 0 <= k <= n")
    c = Circuit(n)
    if k == 0 or k == n: return c
    for m in range(n, k, -1): _scs(c, n, m, k)
    for m in range(k, 1, -1): _scs(c, n, m, m - 1)
    return c

def be_dicke_circuit(n: int, k: int) -> Circuit:
    """|0^n> -> |D_k^n> with O(kn) gates: X on qubits 0..k-1, then U_{n,k}."""
    c = Circuit(n)
    for q in range(k): c.x(q)
    return c.extend(be_unitary_from_reference(n, k))

def be_block_count(n: int, k: int) -> int:
    """Number of SCS blocks (each 2 CX + 1 controlled RY with 1 or 2 controls): (n-k)k + k(k-1)/2 for 0 < k < n, else 0."""
    return 0 if k in (0, n) else (n - k) * k + k * (k - 1) // 2

def be_gate_counts(n: int, k: int) -> dict:
    return be_dicke_circuit(n, k).counts()
