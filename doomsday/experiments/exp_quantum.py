"""Phase 8: E4 (oracle and circuit equivalence), E5 (Grover dynamics on Aer, ideal and noise-modelled), E13 (IBM hardware, OPTIONAL).
Toy problems use the IEEE-14 DC oracle on a fixed candidate shortlist (branches 0..m-1); the marked set is computed classically and compiled
into the phase oracle (a lookup). Nothing here demonstrates a speedup; Aer is a classical simulator; hardware is only claimed with job IDs."""
from __future__ import annotations
import os
from math import comb
import numpy as np
from ..oracle.factory import make_oracle
from ..qsearch.aer_runner import aer_statevector_p_marked, qiskit_available, run_toy_on_aer
from ..qsearch.circuits import phase_oracle, reflection_about_dicke
from ..qsearch.dicke import be_block_count, be_dicke_circuit, dicke_state, dicke_tree_circuit
from ..qsearch.emulation import MarkedSet, optimal_r, p_closed
from ..qsearch.statevec import run, unitary
from ..qsearch.toy import build_toy, circuit_probabilities
from .common import bp_cached, cfg_for, tables_for
from .framework import ExpOutput, Part, data_status_for

TOYS = ((6, 2), (8, 3))

def _toy(m, k):
    cfg = cfg_for("ieee14"); bp = bp_cached("ieee14", cfg); return build_toy(make_oracle("dc", k, cfg, bp=bp, use_cache=False), range(m)), cfg, bp

def e4(config, ctx) -> ExpOutput:
    parts, payload = [], {}
    # (1) Dicke fidelity, both constructions, all 0 <= k <= n <= 10 (Q1)
    rows = {}
    for prep, f in (("tree", dicke_tree_circuit), ("be", be_dicke_circuit)):
        worst, leak = 0.0, 0.0
        for n in range(1, 11):
            w = np.array([bin(b).count("1") for b in range(1 << n)])
            for k in range(n + 1):
                st = run(f(n, k)); worst = max(worst, 1 - abs(np.vdot(dicke_state(n, k), st)) ** 2); leak = max(leak, float(np.sum(np.abs(st[w != k]) ** 2)))
        rows[prep] = {"max_infidelity": worst, "max_leak_outside_weight_k": leak, "pass": worst <= 1e-10}
    rows["be_blocks_formula"] = "(n-k)k + k(k-1)/2"; rows["be_blocks_ieee118_k3"] = be_block_count(186, 3)
    payload["Q1_dicke_fidelity_n_le_10"] = rows; parts.append(Part("Q1_dicke_fidelity", "EXECUTED", kind="NUMPY_STATEVECTOR"))
    # (2) reflection operator on the weight-k subspace, L <= 8 (Q2)
    ref = {}
    for prep in ("tree", "be"):
        err = 0.0
        for n in range(2, 9):
            for k in range(1, n):
                U = unitary(reflection_about_dicke(n, k, prep)); D = dicke_state(n, k); idx = [b for b in range(1 << n) if bin(b).count("1") == k]
                T = np.eye(1 << n) - 2 * np.outer(D, D); err = max(err, float(np.abs(U[np.ix_(idx, idx)] - T[np.ix_(idx, idx)]).max()))
        ref[prep] = {"max_abs_error_vs_I_minus_2DD": err, "pass": err < 1e-10, "note": "circuit implements I-2|D><D| = -(2|D><D|-I): global sign vs V2's R_D"}
    payload["Q2_reflection"] = ref; parts.append(Part("Q2_reflection", "EXECUTED", kind="NUMPY_STATEVECTOR"))
    # (3) phase-oracle diagonal = mask (Q3) and (4) the O1 equivalence chain on the real toys
    q3, o1, q4 = {}, {}, {}
    for m, k in TOYS:
        toy, cfg, bp = _toy(m, k); key = f"m{m}_k{k}"
        U = unitary(phase_oracle(m, k, toy.marked_masks)); d = np.diag(U); off = float(np.abs(U - np.diag(d)).max())
        want = np.ones(1 << m); want[toy.marked_masks] = -1
        q3[key] = {"N": toy.N, "M": toy.M, "max_offdiag": off, "max_diag_error": float(np.abs(d - want).max()), "pass": off < 1e-12 and np.abs(d - want).max() < 1e-12}
        o_dc = make_oracle("dc", k, cfg, bp=bp, use_cache=False); X = np.array(toy.global_sets, dtype=np.int64)
        s_batch = o_dc.severity_batch(X); s_scalar = np.array([make_oracle("dc", k, cfg, bp=bp, use_cache=False).severity(tuple(x)) for x in X])
        tab = tables_for(ctx, "ieee14", "dc", [k]); s_table = tab.severity_batch(X)
        mask_circuit = np.array([d[mk] < 0 for mk in toy.masks]); mask_tierB = np.isin(np.arange(toy.N), MarkedSet(toy.N, np.flatnonzero(toy.marked_mask_bool())).ranks)
        mask_pred = s_batch >= s_batch.max() - 1e-9
        o1[key] = {"dc_batched_eq_dc_scalar": bool(np.array_equal(s_batch, s_scalar)), "dc_eq_truth_table": bool(np.array_equal(s_batch, s_table)),
                   "tierA_circuit_mask_eq_predicate": bool(np.array_equal(mask_circuit, mask_pred)), "tierB_mask_eq_predicate": bool(np.array_equal(mask_tierB, mask_pred)),
                   "micro_oracle": "see E14 (A2) -- separate toy predicate; chain link reported there"}
        # (4) Aer statevector vs Tier B for every r (Q4), both preparations
        rmax = 2 * optimal_r(toy.N, toy.M) + 2; tb = p_closed(np.arange(rmax + 1), toy.N, toy.M); npy = circuit_probabilities(toy, rmax)["p_marked"]
        q4[key] = {"rmax": rmax, "numpy_vs_tierB_max_abs": float(np.abs(npy - tb).max())}
        for prep in ("tree", "be"):
            a = aer_statevector_p_marked(toy, rmax, prep)
            if a["status"] != "EXECUTED": q4[key][prep] = a; continue
            pa = np.array([r["p_marked"] for r in a["rows"]])
            q4[key][prep] = {"aer_vs_tierB_max_abs": float(np.abs(pa - tb).max()), "max_leak": max(r["leak_outside_weight_k"] for r in a["rows"]),
                             "depth_per_r": [r["depth"] for r in a["rows"]], "cx_per_r": [r["cx"] for r in a["rows"]], "pass": float(np.abs(pa - tb).max()) <= 1e-9,
                             "environment": a["environment"]}
    payload["Q3_phase_oracle_diagonal"] = q3; payload["O1_equivalence_chain_toys"] = o1; payload["Q4_aer_statevector_vs_tierB"] = q4
    parts.append(Part("Q3_O1_toys_ieee14", "EXECUTED", data_status_for("ieee14"), "NUMPY_STATEVECTOR", dataset="ieee14"))
    ok, env = qiskit_available()
    parts.append(Part("Q4_aer_vs_tierB", "EXECUTED" if ok else "NOT_RUN", data_status_for("ieee14") if ok else "NO_GRID_DATA", "AER_SIMULATED" if ok else "NONE",
                      reason="" if ok else env.get("reason", "qiskit unavailable"), dataset="ieee14"))
    # (5) micro-oracle exhaustive check (Q6): implemented in Phase 11 (E14); referenced here
    try:
        from ..qsearch.microoracle import exhaustive_check_summary
        payload["Q6_micro_oracle"] = exhaustive_check_summary(); parts.append(Part("Q6_micro_oracle_exhaustive", "EXECUTED", kind="SYNTHESIZED"))
    except ImportError as e:
        parts.append(Part("Q6_micro_oracle_exhaustive", "NOT_IMPLEMENTED", reason=f"A2 micro-oracle module unavailable: {e}"))
    allpass = all(v["pass"] for v in rows.values() if isinstance(v, dict)) and all(v["pass"] for v in ref.values()) and all(v["pass"] for v in q3.values()) \
        and all(isinstance(v.get(p), dict) and v[p].get("pass") for v in q4.values() for p in ("tree", "be"))
    payload["verdict"] = "PASS" if allpass else "FAIL: circuit bug; Tier A claims withdrawn (V2 E4)"
    return ExpOutput(parts=parts, payload=payload, datasets_used=["ieee14"], criteria=[{"criterion": "Dicke F >= 1-1e-10; Aer vs Tier B within 1e-9 for all r", "met": allpass}],
                     limitations=["Toys use candidate branches 0..m-1 of IEEE-14 (a fixed shortlist, never evidence of scaling).",
                                  "The phase oracle is a compiled lookup of a classically computed marked set (Tier A1)."], parameters={"toys": TOYS})

def e5(config, ctx) -> ExpOutput:
    shots = config["params"]["shots"]; parts, payload = [], {"shots_ideal": shots}
    ok, env = qiskit_available()
    if not ok:
        return ExpOutput(parts=[Part("aer", "NOT_RUN", reason=env.get("reason", "qiskit unavailable"))], payload=payload)
    noisy_shots = max(2000, shots // 5); payload["shots_noisy"] = noisy_shots; payload["noise_backend"] = "FakeSherbrooke (qiskit-ibm-runtime fake provider; device snapshot noise model)"
    for m, k in TOYS:
        toy, _, _ = _toy(m, k); rmax = 2 * optimal_r(toy.N, toy.M) + 2; key = f"m{m}_k{k}"
        res = {"N": toy.N, "M": toy.M, "r_star_theory": optimal_r(toy.N, toy.M), "p_theory": p_closed(np.arange(rmax + 1), toy.N, toy.M).tolist()}
        res["ideal_tree"] = run_toy_on_aer(toy, rmax, shots, seed=0, prep="tree")
        res["ideal_be"] = run_toy_on_aer(toy, rmax, shots, seed=0, prep="be")
        for prep in ("be", "tree"):
            res[f"noisy_{prep}"] = run_toy_on_aer(toy, rmax, noisy_shots, seed=0, fake_backend="FakeSherbrooke", prep=prep)
        for lab in ("noisy_be", "noisy_tree"):
            rr = res[lab].get("rows")
            if rr:
                peak = max(rr, key=lambda x: x["p_measured"])
                res[lab]["summary"] = {"peak_p": peak["p_measured"], "r_at_peak": peak["r"], "ideal_peak_p": max(res["p_theory"]), "random_guess_p": toy.M / toy.N,
                                       "amplifies_above_uniform": peak["p_measured"] > toy.M / toy.N + 4 * np.sqrt(toy.M / toy.N * (1 - toy.M / toy.N) / noisy_shots)}
        payload[key] = res
        st = [res[x]["status"] for x in ("ideal_tree", "ideal_be", "noisy_be", "noisy_tree")]
        parts.append(Part(f"aer_ideal_and_noisy[{key}]", "EXECUTED" if all(s.startswith("EXECUTED") for s in st) else "FAILED" if "ERROR" in st else "NOT_RUN",
                          data_status_for("ieee14"), "AER_SIMULATED", reason="" if all(s.startswith("EXECUTED") for s in st) else str(st), dataset="ieee14"))
    return ExpOutput(parts=parts, payload=payload, datasets_used=["ieee14"], seeds=[0],
                     limitations=["Aer is a classical simulator; the noisy runs use a fake-backend noise model (device snapshot), not a device.",
                                  "Ideal runs pass only if every r agrees with the NumPy statevector within 4 sigma (EXECUTED_VERIFIED)."],
                     parameters={"toys": TOYS, "shots": shots, "noisy_shots": noisy_shots})

def e13(config, ctx) -> ExpOutput:
    tok = any(os.environ.get(v) for v in ("QISKIT_IBM_TOKEN", "IBM_QUANTUM_TOKEN", "QISKIT_IBM_RUNTIME_API_TOKEN"))
    reason = ("no IBM Quantum credentials are configured in this environment (QISKIT_IBM_TOKEN unset), so no device job was submitted; "
              "E13 is OPTIONAL in V2 and is reported as NOT_RUN. A run needs an IBM Quantum account (QISKIT_IBM_TOKEN) and qiskit-ibm-runtime; device "
              "submission is not automated in this pipeline") if not tok else \
             "credentials present but hardware submission is not automated in this pipeline; any device run must be added with its job IDs"
    return ExpOutput(parts=[Part("ibm_device_A1_toy", "NOT_RUN", reason=reason)], payload={"hardware_claimed": False, "job_ids": []},
                     limitations=["No hardware result exists or is claimed."])
