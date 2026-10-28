"""Tier A1 circuits (toy): Dicke preparation, compiled phase oracle (lookup of a classically computed marked set), reflection about |D>,
Grover iteration. Conventions: qubit q <-> candidate branch q; x_q=1 iff branch q is OUT; k ones on qubits 0..k-1 in the reference state.
The circuit 'reflection' is I - 2|D><D| = -(2|D><D| - I): a global sign relative to V2's R_D; probabilities are identical."""
from __future__ import annotations
from .dicke import be_dicke_circuit, be_unitary_from_reference, dicke_prep_from_reference, dicke_tree_circuit
from .statevec import Circuit

def check_masks(n: int, k: int, masks) -> list:
    out = []
    for m in masks:
        if not isinstance(m, int) or not 0 <= m < (1 << n): raise ValueError(f"mask {m!r} out of range")
        if bin(m).count("1") != k: raise ValueError(f"mask {m:#b} has weight {bin(m).count('1')} != k={k}: only weight-k strings may be marked")
        out.append(m)
    if len(set(out)) != len(out): raise ValueError("duplicate marked masks")
    return sorted(out)

def phase_oracle(n: int, k: int, masks) -> Circuit:
    """For each marked x: X on the zero bits of x, multi-controlled Z on all qubits, X again (flips the sign of |x> only). Cost O(|M|*n)."""
    c = Circuit(n)
    for m in check_masks(n, k, masks):
        zeros = [q for q in range(n) if not (m >> q) & 1]
        for q in zeros: c.x(q)
        c.mcz(range(n))
        for q in zeros: c.x(q)
    return c

def reflection_about_dicke(n: int, k: int, prep: str = "tree") -> Circuit:
    """U (I - 2|ref><ref|) U^dagger = I - 2|D><D|, with U|ref> = |D>. prep='tree' (default): Tree^dagger . X^n . MCZ . X^n . Tree with
    ref = |0^n>. prep='be' (Phase 8): U = Baertschi-Eidenbenz unitary, ref = |1^k 0^(n-k)>: U^dagger . X_{k..n-1} . MCZ . X_{k..n-1} . U."""
    if prep == "be":
        U = be_unitary_from_reference(n, k); c = Circuit(n).extend(U.inverse())
        for q in range(k, n): c.x(q)
        c.mcz(range(n))
        for q in range(k, n): c.x(q)
        return c.extend(U)
    if prep != "tree": raise ValueError("prep must be 'tree' or 'be'")
    tree = dicke_tree_circuit(n, k); c = Circuit(n).extend(tree.inverse())
    for q in range(n): c.x(q)
    c.mcz(range(n))
    for q in range(n): c.x(q)
    return c.extend(tree)

def grover_iteration(n: int, k: int, masks, prep: str = "tree") -> Circuit:
    return phase_oracle(n, k, masks).extend(reflection_about_dicke(n, k, prep))

def grover_circuit(n: int, k: int, masks, r: int, prep: str = "tree") -> Circuit:
    if prep == "be":
        c = Circuit(n).extend(be_dicke_circuit(n, k))
        for _ in range(r): c.extend(grover_iteration(n, k, masks, "be"))
        return c
    c = Circuit(n).extend(dicke_tree_circuit(n, k))        # from |0^n> the tree alone prepares |D>; (X^ref . tree) is the |1^k 0^(n-k)> -> |D> unitary
    for _ in range(r): c.extend(grover_iteration(n, k, masks))
    return c
