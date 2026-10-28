"""Aer execution wrapper for the toy Grover circuits (Tier A1). EXECUTION STATUS is explicit and conservative:
  NOT_RUN             qiskit / qiskit-aer unavailable (reason recorded) -- the state in the authoring sandbox
  EXECUTED_VERIFIED   a real Aer run whose measured P(marked) agrees with the NumPy statevector simulation within the stated sigma band for EVERY r
  EXECUTED_MISMATCH   a real Aer run that disagrees (reported, never hidden)
  ERROR               unexpected failure (message recorded)
A status can only be EXECUTED_* if Qiskit actually ran. Nothing here is hardware (IBM device runs, E13, are not implemented)."""
from __future__ import annotations
import math, platform
import numpy as np
from .circuits import grover_circuit
from .qiskit_export import to_qiskit
from .toy import ToyProblem, circuit_probabilities

def qiskit_available():
    try:
        import qiskit, qiskit_aer                      # noqa: F401
        return True, {"qiskit": qiskit.__version__, "qiskit_aer": qiskit_aer.__version__, "python": platform.python_version()}
    except Exception as e:                             # ImportError or broken install
        return False, {"reason": f"{type(e).__name__}: {e}"}

def wilson(k: int, n: int, z: float = 1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)

def compare_to_numpy(n_marked_counts: int, shots: int, p_expected: float, z: float = 4.0) -> dict:
    sig = math.sqrt(max(p_expected * (1 - p_expected), 1e-12) / shots); meas = n_marked_counts / shots
    return {"measured": meas, "expected": p_expected, "sigma": sig, "z_score": (meas - p_expected) / sig, "ok": abs(meas - p_expected) <= z * sig + 1.0 / shots}

def run_toy_on_aer(toy: ToyProblem, rmax: int = 6, shots: int = 4096, seed: int = 0, fake_backend: str | None = None, prep: str = "tree") -> dict:
    ok, env = qiskit_available()
    base = {"toy": {"m": toy.m, "k": toy.k, "N": toy.N, "M": toy.M, "candidates": list(toy.candidates)}, "shots": shots, "rmax": rmax,
            "mode": "ideal" if fake_backend is None else f"noise-model from fake backend {fake_backend!r}", "dicke_prep": prep, "environment": env}
    if not ok: return {**base, "status": "NOT_RUN", "reason": "qiskit/qiskit-aer unavailable in this environment; no Aer execution took place"}
    try:
        from qiskit import transpile
        from qiskit_aer import AerSimulator
        ref = circuit_probabilities(toy, rmax)["p_marked"]; rows = []; marked = set(toy.marked_masks)
        if fake_backend is None: sim, tkw = AerSimulator(), {"basis_gates": ["u", "cx"]}
        else:
            from qiskit_aer.noise import NoiseModel
            from qiskit_ibm_runtime import fake_provider
            be = getattr(fake_provider, fake_backend)(); sim = AerSimulator(noise_model=NoiseModel.from_backend(be)); tkw = {"backend": be}
        for r in range(rmax + 1):
            qc = to_qiskit(grover_circuit(toy.m, toy.k, toy.marked_masks, r, prep=prep)); qc.measure_all()
            tq = transpile(qc, sim if fake_backend is None else tkw["backend"], optimization_level=3, seed_transpiler=seed, **({"basis_gates": tkw["basis_gates"]} if fake_backend is None else {}))
            counts = sim.run(tq, shots=shots, seed_simulator=seed).result().get_counts()
            hit = sum(c for b, c in counts.items() if int(b.replace(" ", ""), 2) in marked)
            ops = tq.count_ops(); lo, hi = wilson(hit, shots)
            rows.append({"r": r, "marked_counts": hit, "p_measured": hit / shots, "wilson95": [lo, hi], "p_numpy_ideal": float(ref[r]),
                         "compare": compare_to_numpy(hit, shots, float(ref[r])), "depth": tq.depth(), "two_qubit_gates": int(sum(v for g, v in ops.items() if g in ("cx", "ecr", "cz")))})
        best = max(rows, key=lambda x: x["p_measured"])
        out = {**base, "rows": rows, "best_r_measured": best["r"], "best_r_numpy_ideal": int(np.argmax(ref))}
        if fake_backend is None:
            out["status"] = "EXECUTED_VERIFIED" if all(x["compare"]["ok"] for x in rows) else "EXECUTED_MISMATCH"
        else:
            out["status"] = "EXECUTED"                                   # noisy runs are not expected to match the ideal: reported as a finding
            out["note"] = "noise lowers the peak and moves r* earlier (V2 E5 hypothesis); no pass/fail applies"
        return out
    except Exception as e:
        return {**base, "status": "ERROR", "reason": f"{type(e).__name__}: {e}"}


def aer_statevector_p_marked(toy: ToyProblem, rmax: int, prep: str = "tree", seed: int = 0) -> dict:
    """(Phase 8, E4 / Test Q4) Exact Aer statevector of the TRANSPILED circuit (basis u, cx) for r = 0..rmax: P(marked) per r and the
    probability outside the weight-k subspace. No sampling noise, so the comparison with Tier B is to ~1e-9, not a sigma band."""
    ok, env = qiskit_available()
    if not ok: return {"status": "NOT_RUN", "reason": env["reason"]}
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    sim = AerSimulator(method="statevector"); marked = list(toy.marked_masks); w = np.array([bin(b).count("1") == toy.k for b in range(1 << toy.m)]); rows = []
    for r in range(rmax + 1):
        qc = to_qiskit(grover_circuit(toy.m, toy.k, marked, r, prep=prep)); tq = transpile(qc, basis_gates=["u", "cx"], optimization_level=1, seed_transpiler=seed)
        tq.save_statevector(); sv = np.asarray(sim.run(tq).result().get_statevector()); p = np.abs(sv) ** 2
        ops = tq.count_ops(); rows.append({"r": r, "p_marked": float(p[marked].sum()), "leak_outside_weight_k": float(p[~w].sum()), "depth": tq.depth(), "cx": int(ops.get("cx", 0))})
    return {"status": "EXECUTED", "rows": rows, "environment": env, "prep": prep}
