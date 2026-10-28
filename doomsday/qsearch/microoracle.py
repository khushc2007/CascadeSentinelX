"""A2 micro-oracle (V2 13.4): a COHERENT reversible cascade oracle at toy scale, verified exhaustively, with per-primitive Toffoli counts that
calibrate the Tier C formulas (E14). Not a lookup of the marked set: the circuit computes island connectivity, DC flows (fixed-point
multiply-accumulate), overload comparisons, trip updates over R rounds, served load and the threshold, then kicks back the phase and
uncomputes everything (Bennett).

Instance (V2: '4-5-bus toy grid with 5-7 branches, b ~ 4-6-bit fixed point, R = 2'): 4 buses, 5 branches (ring 1-2-3-4-1 + chord 1-3),
slack generator at bus 1 with ample capacity, loads 1.0/1.0/0.5 p.u.; ratings = N-1 maximum |flow| rounded up to the 1/8 p.u. grid (base
case N-1 secure). Fixed point: Q(.,F=3), b = 6 bits signed; multiplications accumulate in 2b bits and truncate (floor) once.

DEVIATION FROM V2's Tier C block list (stated, not hidden): flows use a per-topology sensitivity QROM (H_s = PTDF of the slack island for
in-service status s, 2^L entries) times the gated load vector -- i.e. the 'injection update' L x B multiply -- instead of V2's base-Phi
rank-|K| update with a reversible small inverse. Therefore the SMALL-INVERSE primitive is NOT calibrated by A2. The per-topology QROM is only
viable at toy scale (2^L entries); at IEEE scale the design remains V2's (Tier C, never synthesized).
numpy only; no gridtwin import (qsearch boundary rule)."""
from __future__ import annotations
from functools import lru_cache
from math import floor
import numpy as np
from .reversible import RevCircuit, add_into, add_const, load_const, mul_acc_signed_unsigned, or_into, sign_of_plus_const, simulate

B_BUS = 4; SLACK = 0; F = 3; B_BITS = 6; R_ROUNDS = 2; TAU = 0.2
BRANCHES = ((0, 1, 0.1), (1, 2, 0.1), (2, 3, 0.1), (3, 0, 0.1), (0, 2, 0.2))
L = len(BRANCHES)
LOAD_PU = (0.0, 1.0, 1.0, 0.5)
D_ITER = B_BUS - 1                                                  # label-propagation iterations (>= graph diameter)

def loads_int(): return [int(round(v * (1 << F))) for v in LOAD_PU]
def total_int(): return sum(loads_int())
def threshold_int(): return int(floor((1 - TAU) * total_int()))      # flag = served <= threshold  <=>  S >= tau

def reach(s) -> np.ndarray:
    r = np.zeros(B_BUS, bool); r[SLACK] = True
    for _ in range(D_ITER):
        r2 = r.copy()
        for l, (u, v, _) in enumerate(BRANCHES):
            if s[l]: r2[v] |= r[u]; r2[u] |= r[v]
        r = r2
    return r

@lru_cache(maxsize=None)
def ptdf_island(s_tuple) -> np.ndarray:
    """PTDF (L x B) of the slack's island for status s (rows of branches outside the island are zero). DC: B'theta = P, slack reference."""
    s = np.array(s_tuple, bool); rc = reach(s); A = np.zeros((L, B_BUS))
    for l, (u, v, _) in enumerate(BRANCHES): A[l, u], A[l, v] = 1, -1
    bv = np.array([(1 / x) if (s[l] and rc[u] and rc[v]) else 0.0 for l, (u, v, x) in enumerate(BRANCHES)])
    keep = [b for b in range(B_BUS) if rc[b] and b != SLACK]; H = np.zeros((L, B_BUS))
    if keep:
        Bp = A.T @ (bv[:, None] * A); Bi = np.zeros((B_BUS, B_BUS)); Bi[np.ix_(keep, keep)] = np.linalg.inv(Bp[np.ix_(keep, keep)]); H = (bv[:, None] * A) @ Bi
    return H

def coef_int(s_tuple) -> np.ndarray:
    """Fixed-point coefficients c[l,b] = round(-PTDF[l,b] * 2^F): flow = sum_b c[l,b] * load_b (injection at a load bus is -load)."""
    return np.round(-ptdf_island(s_tuple) * (1 << F)).astype(int)

def flows_float(s) -> np.ndarray:
    return ptdf_island(tuple(bool(v) for v in s)) @ (-np.array(LOAD_PU) * reach(s))

def ratings_int() -> list:
    """N-1 secure: max over base and every single outage of |flow|, rounded UP to the 1/8 p.u. grid, +1 lsb margin."""
    m = np.zeros(L)
    for out in [None] + list(range(L)):
        s = np.ones(L, bool)
        if out is not None: s[out] = False
        m = np.maximum(m, np.abs(flows_float(s)))
    return [int(np.ceil(v * (1 << F) - 1e-9)) + 1 for v in m]

LOAD_BUSES = [b for b in range(B_BUS) if LOAD_PU[b] > 0]

def classical_oracle(x, R: int = R_ROUNDS) -> dict:
    """Exact integer semantics the circuit implements. x: initial outage bits (len L)."""
    s = np.array([not v for v in x]); Ri = ratings_int(); li = loads_int(); hist = []
    for _ in range(R):
        rc = reach(s); c = coef_int(tuple(bool(v) for v in s)); p = np.array([li[b] * int(rc[b]) for b in range(B_BUS)])
        acc = c @ p; f = acc >> F; trip = (f > np.array(Ri)) | (f < -np.array(Ri)); hist.append({"flows_int": f.tolist(), "trip": trip.astype(int).tolist()})
        s = s & ~trip
    served = int(sum(li[b] for b in range(B_BUS) if reach(s)[b]))
    return {"served_int": served, "S": 1 - served / total_int(), "flag": served <= threshold_int(), "final_status": s.astype(int).tolist(), "rounds": hist}

# ---- circuit -------------------------------------------------------------------------------------------------------------------------
def build(R: int = R_ROUNDS):
    """Returns (circuit, layout). Inputs: register 'x' (L outage bits) and 'out' (kickback target). Forward computes the flag; CX flag->out;
    then the exact inverse of the forward part (Bennett)."""
    c = RevCircuit(); x = c.register("x", L); out = c.register("out", 1)[0]; Ri = ratings_int(); li = loads_int(); w2 = 2 * B_BITS
    lay = {"status": [], "reach": [], "flows": []}
    with c.tag("status_init"):
        s = c.register("s0", L)
        for l in range(L): c.cx(x[l], s[l]); c.x(s[l])
    lay["status"].append(s)

    def island(sreg, name):
        with c.tag("island_detection"):
            r = c.register(f"{name}_r0", B_BUS); c.x(r[SLACK]); regs = [r]
            for t in range(D_ITER):
                nr = c.register(f"{name}_r{t + 1}", B_BUS)
                for v in range(B_BUS):
                    inc = [(l, (u if v == vv else vv)) for l, (u, vv, _) in enumerate(BRANCHES) if v in (u, vv)]
                    terms = c.borrow(len(inc))
                    for q, (l, nb) in zip(terms, inc): c.ccx(sreg[l], r[nb], q)
                    or_into(c, [r[v]] + terms, nr[v])
                    for q, (l, nb) in zip(terms, inc): c.ccx(sreg[l], r[nb], q)
                    c.release(terms)
                r = nr; regs.append(nr)
            return r
    for rd in range(R):
        rc = island(s, f"round{rd}"); lay["reach"].append(rc)
        with c.tag("load_gating"):
            p = {b: c.register(f"p{rd}_{b}", B_BITS) for b in LOAD_BUSES}
            for b in LOAD_BUSES: load_const(c, p[b], li[b], ctrl=rc[b])
        with c.tag("qrom_sensitivity_lookup"):
            coef = {(l, b): c.register(f"c{rd}_{l}_{b}", B_BITS) for l in range(L) for b in LOAD_BUSES}
            for addr in range(1 << L):
                flag = c.borrow(1)[0]; c.mcx(tuple((s[l], (addr >> l) & 1) for l in range(L)), flag)
                ci = coef_int(tuple(bool((addr >> l) & 1) for l in range(L)))
                for (l, b), reg in coef.items():
                    load_const(c, reg, int(ci[l, b]) % (1 << B_BITS), ctrl=flag)
                c.mcx(tuple((s[l], (addr >> l) & 1) for l in range(L)), flag); c.release([flag])
        with c.tag("multiplier_flow_update"):
            acc = {l: c.register(f"acc{rd}_{l}", w2) for l in range(L)}
            for l in range(L):
                for b in LOAD_BUSES: mul_acc_signed_unsigned(c, coef[(l, b)], p[b], acc[l])
        f = {l: acc[l][F:F + B_BITS] for l in range(L)}; lay["flows"].append(f)
        with c.tag("comparators_trip"):
            trip = c.register(f"trip{rd}", L)
            for l in range(L):
                s1, s2 = c.borrow(2)
                sign_of_plus_const(c, f[l], -(Ri[l] + 1), s1)                  # s1 = [f - R - 1 < 0]  -> f > R  <=>  not s1
                sign_of_plus_const(c, f[l], Ri[l], s2)                         # s2 = [f + R < 0]     -> f < -R
                c.x(trip[l]); c.mcx(((s1, 1), (s2, 0)), trip[l])                 # trip = 1 xor (s1 and not s2) = (not s1) or s2
                sign_of_plus_const(c, f[l], Ri[l], s2); sign_of_plus_const(c, f[l], -(Ri[l] + 1), s1); c.release([s1, s2])
        with c.tag("status_update"):
            ns = c.register(f"s{rd + 1}", L)
            for l in range(L): c.mcx(((s[l], 1), (trip[l], 0)), ns[l])
        s = ns; lay["status"].append(s)
    rc = island(s, "final"); lay["reach"].append(rc)
    with c.tag("served_load_accumulation"):
        wa = max(total_int().bit_length() + 1, 2); served = c.register("served", wa)
        for b in LOAD_BUSES: add_const(c, li[b], served, ctrl=rc[b])
    with c.tag("threshold"):
        flag = c.register("flag", 1)[0]; sign_of_plus_const(c, served, -(threshold_int() + 1), flag)   # served - T - 1 < 0  <=>  served <= T
    n_fwd = len(c.gates)
    with c.tag("phase_kickback"):
        c.cx(flag, out)
    fwd = c.gates[:n_fwd]
    for g in reversed(fwd): c.gates.append((g[0], g[1], "bennett_uncompute"))
    lay.update(x=x, out=out, flag=flag, served=served, n_forward_gates=n_fwd)
    return c, lay

def _bits(st, reg): return sum(int(st[q]) << i for i, q in enumerate(reg))
def _signed(v, w): return v - (1 << w) if v >> (w - 1) else v

def verify(c=None, lay=None) -> dict:
    """V2 13.4 (i)-(iv): exhaustive basis-state simulation on all 2^L inputs x (and both values of the kickback target)."""
    if c is None: c, lay = build()
    X = np.array([[(xi >> l) & 1 for l in range(L)] for xi in range(1 << L)] * 2, np.uint8); outb = np.repeat([0, 1], 1 << L)
    st0 = np.zeros((len(X), c.n), np.uint8); st0[:, lay["x"]] = X; st0[:, lay["out"]] = outb
    fwd = simulate(c.n, c.gates[:lay["n_forward_gates"]], st0)                       # forward only: intermediate registers
    fin = simulate(c.n, c.gates, st0)                                                # full circuit
    back = simulate(c.n, c.inverse_gates(), fin)                                     # inverse restores the input
    other = [q for q in range(c.n) if q not in set(lay["x"]) | {lay["out"]}]
    ok_flag = ok_mid = True; rows = []
    for i in range(1 << L):
        ref = classical_oracle(X[i]); flag = int(fwd[i, lay["flag"]]); ok_flag &= flag == int(ref["flag"])
        for rd in range(R_ROUNDS):
            fl = [_signed(_bits(fwd[i], lay["flows"][rd][l]), B_BITS) for l in range(L)]; ok_mid &= fl == ref["rounds"][rd]["flows_int"]
        ok_mid &= _bits(fwd[i], lay["served"]) == ref["served_int"]
        rows.append({"x": X[i].tolist(), "flag": flag, "served_int": ref["served_int"], "S": ref["S"]})
    kick = bool(np.all(fin[:, lay["out"]] == (outb ^ np.array([int(classical_oracle(X[i % (1 << L)])["flag"]) for i in range(len(X))]))))
    return {"n_inputs": int(len(X)), "flag_equals_classical_oracle": bool(ok_flag), "intermediate_flows_and_served_equal_classical": bool(ok_mid),
            "kickback_target_flips_iff_marked": kick, "ancillas_clean_after_uncompute": bool(np.all(fin[:, other] == 0)),
            "inputs_unchanged": bool(np.array_equal(fin[:, lay["x"]], X)), "inverse_restores_input": bool(np.array_equal(back, st0)),
            "n_marked": int(sum(r["flag"] for r in rows)), "rows": rows, "qubits": c.n, "peak_pool": len(c._pool)}

def exhaustive_check_summary() -> dict:
    c, lay = build(); v = verify(c, lay); cnt = c.counts()
    return {k: v[k] for k in v if k != "rows"} | {"toffoli_equiv_total": cnt["TOTAL"]["toffoli_equiv"], "gates_total": cnt["TOTAL"]["gates"],
                                                 "pass": all(v[k] for k in ("flag_equals_classical_oracle", "intermediate_flows_and_served_equal_classical",
                                                                            "kickback_target_flips_iff_marked", "ancillas_clean_after_uncompute",
                                                                            "inputs_unchanged", "inverse_restores_input"))}

# ---- calibration against V2 16.2 formulas ----------------------------------------------------------------------------------------------
C_LAB = 19.0
def formula_counts(R: int = R_ROUNDS) -> dict:
    """V2 16.2 formula Toffoli counts for THIS instance's primitive inventory (same number of primitive instances as the circuit)."""
    b, nB = B_BITS, len(LOAD_BUSES)
    return {"island_detection": (R + 1) * C_LAB * L * D_ITER,                   # c_lab * L * D per island computation
            "multiplier_flow_update": R * L * nB * b * b,                       # b^2 per b x b multiplication (L x B injection-update product)
            "comparators_trip": R * L * b,                                      # L * b per round
            "served_load_accumulation": B_BUS * b,                              # B * b per accumulation (one, final)
            "qrom_sensitivity_lookup": R * (1 << L),                            # ~1 Toffoli per QROM entry (V2: L per L-entry column lookup)
            "threshold": b}                                                     # one comparator (V2 'once only' term)

def calibration(R: int = R_ROUNDS) -> dict:
    c, _ = build(R); cnt = c.counts(); fc = formula_counts(R); out = {}
    for k, f in fc.items():
        m = cnt.get(k, {}).get("toffoli_equiv", 0); out[k] = {"synthesized_toffoli_equiv": m, "formula": f, "kappa_cal": (m / f) if f else None}
    fwd = sum(v["toffoli_equiv"] for k, v in cnt.items() if k not in ("TOTAL", "bennett_uncompute"))
    out["bennett_factor_measured"] = (fwd + cnt.get("bennett_uncompute", {}).get("toffoli_equiv", 0)) / fwd
    out["small_inverse"] = {"kappa_cal": None, "status": "NOT CALIBRATED: A2 has no reversible small inverse (see module docstring)"}
    out["_counts_by_primitive"] = cnt; out["_qubits"] = c.n
    return out

def primitive_scaling(bits=(4, 6, 8, 12, 16)) -> dict:
    """Standalone primitive circuits at several widths b: Toffoli-equivalents of one b x b signed*unsigned multiply-accumulate (2b-bit
    accumulator), one constant comparator on b bits, one b-bit adder; kappa vs the V2 formulas b^2, b, b."""
    rows = {}
    for b in bits:
        c = RevCircuit(); a = c.register("a", b); p = c.register("p", b); acc = c.register("acc", 2 * b); mul_acc_signed_unsigned(c, a, p, acc); tm = c.counts()["TOTAL"]["toffoli_equiv"]
        c = RevCircuit(); x = c.register("x", b); o = c.register("o", 1); sign_of_plus_const(c, x, 3, o[0]); tc = c.counts()["TOTAL"]["toffoli_equiv"]
        c = RevCircuit(); a = c.register("a", b); y = c.register("y", b); add_into(c, a, y); ta = c.counts()["TOTAL"]["toffoli_equiv"]
        rows[b] = {"multiply_acc": tm, "kappa_mult_vs_b2": tm / b ** 2, "comparator": tc, "kappa_cmp_vs_b": tc / b, "adder": ta, "kappa_add_vs_b": ta / b}
    return rows
