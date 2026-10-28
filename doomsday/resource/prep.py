"""Dicke-state preparation cost, TWO SEPARATE scenarios (never presented as equivalent):
 (A) 'v2_assumed'  : V2 11.3 theoretical cost C_D = k*L*c_rot Toffoli-equivalents (Baertschi-Eidenbenz O(kL)). ASSUMPTION: the BE construction
                     has NOT been reproduced in this repository.
 (B) 'tree_counted': operation counts of the construction that IS implemented (explicit-amplitude binary tree of multiplexed RY rotations,
                     doomsday/qsearch/dicke.py), obtained from an exact analytic count verified against the real circuit for all n<=10.
                     Its Toffoli-equivalent conversion (2*(c-1)*overhead + c_rot per c-controlled rotation) is an ESTIMATE made here, not from V2.
This module imports nothing from gridtwin/oracle/qsearch (resource decoupling, V2 20.1)."""
from __future__ import annotations
from math import comb

def dicke_tree_op_counts(n: int, k: int) -> dict:
    """Exact number of c-controlled RY ops in the tree circuit for |D_k^n>, keyed by control count c = n-1-q.
    Level q (rotated qubit) with prefix weight w (ones among the already-fixed higher qubits, prefix length l=n-1-q): an op exists iff
    P(bit q = 1 | prefix) > 0, i.e. 1 <= k-w <= q+1; the number of such prefixes is C(l, w). (Verified against the circuit in tests.)"""
    if not 0 <= k <= n: raise ValueError("need 0 <= k <= n")
    out: dict = {}
    for q in range(n - 1, -1, -1):
        l = n - 1 - q; cnt = sum(comb(l, w) for w in range(0, k + 1) if 1 <= k - w <= q + 1)
        if cnt: out[l] = cnt
    return out

def dicke_prep_cost_v2(L: int, k: int, c_rot: float) -> float:
    """SCENARIO A (ASSUMPTION): C_D = k * L * c_rot Toffoli-equivalents (V2 11.3). Not supported by the implemented circuit."""
    return float(k * L * c_rot)

def tree_toffoli_equivalents(counts: dict, c_rot: float, and_overhead: float = 2.0) -> float:
    """SCENARIO B conversion (ESTIMATE): a c-controlled RY = AND-ladder compute/uncompute 2*(c-1) Toffolis (x and_overhead/2 scaling via parameter)
    + one rotation of cost c_rot Toffoli-equivalents. Value-0 controls need X gates (Clifford, free)."""
    return float(sum(m * (and_overhead * max(c - 1, 0) + c_rot) for c, m in counts.items()))

def dicke_prep_cost_tree(L: int, k: int, c_rot: float, and_overhead: float = 2.0) -> dict:
    counts = dicke_tree_op_counts(L, k); total = sum(counts.values())
    return {"op_counts_by_controls": {str(c): m for c, m in sorted(counts.items())}, "n_rotations": int(total),
            "max_controls": max(counts) if counts else 0, "toffoli_equivalents": tree_toffoli_equivalents(counts, c_rot, and_overhead),
            "ancillas_for_and_ladder": max((max(counts) - 1) if counts else 0, 0)}


# ---- (Phase 8/11) scenario C: 'be_counted' -- the Baertschi-Eidenbenz circuit, reconstructed and numerically verified in Phase 8 ----------
def be_block_count(L: int, k: int) -> int:
    """(L-k)k + k(k-1)/2 split-and-cyclic-shift blocks; first-type blocks have a 1-control RY, the others a 2-control RY (both 2 CX)."""
    return 0 if k in (0, L) else (L - k) * k + k * (k - 1) // 2

def dicke_prep_cost_be(L: int, k: int, c_rot: float, and_overhead: float = 2.0) -> dict:
    """Toffoli-equivalents of the VERIFIED BE construction: per block one rotation (c_rot) plus, for 2-control blocks, an AND compute/uncompute
    (and_overhead Toffolis). Blocks with one control: one per SCS (L-1 of them in total); the rest have two controls. Conversion is an ESTIMATE."""
    nb = be_block_count(L, k); one = (L - k) + max(k - 1, 0) if 0 < k < L else 0; two = nb - one
    return {"blocks": nb, "one_control_rotations": one, "two_control_rotations": two, "toffoli_equivalents": float(one * c_rot + two * (c_rot + and_overhead)),
            "status": "construction VERIFIED numerically (n <= 10, tests/quantum/test_be_dicke.py); Toffoli-equivalent conversion is an ESTIMATE"}
