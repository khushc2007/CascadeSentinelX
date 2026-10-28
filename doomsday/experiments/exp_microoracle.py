"""Phase 11, E14: A2 micro-oracle synthesis and calibration (V2 13.4, 18 E14). Exhaustive basis-state verification and per-primitive kappa_cal."""
from __future__ import annotations
import numpy as np
from ..gridtwin.cascade import CascadeEngine
from ..qsearch import microoracle as mo
from . import specs as SP
from .common import toy_base_point
from .framework import ExpOutput, Part

TOY_CASE = """mpc.baseMVA = 100;
mpc.bus = [ 1 3 0 0 0 0 1 1.0 0 0 1 1.1 0.9; 2 1 100 0 0 0 1 1.0 0 0 1 1.1 0.9; 3 1 100 0 0 0 1 1.0 0 0 1 1.1 0.9; 4 1 50 0 0 0 1 1.0 0 0 1 1.1 0.9; ];
mpc.gen = [ 1 250 0 300 -300 1.0 100 1 1000 0; ];
mpc.branch = [ 1 2 0 0.1 0 0 0 0 0 0 1; 2 3 0 0.1 0 0 0 0 0 0 1; 3 4 0 0.1 0 0 0 0 0 0 1; 4 1 0 0.1 0 0 0 0 0 0 1; 1 3 0 0.2 0 0 0 0 0 0 1; ];"""

def _float_engine_agreement() -> dict:
    """O1 chain link: the A2 fixed-point predicate vs the project's float64 DC cascade engine on the SAME toy grid and ratings."""
    from ..config import load_config
    rat_mw = np.array(mo.ratings_int(), float) / (1 << mo.F) * 100.0
    bp = toy_base_point(TOY_CASE, rat_mw, name="a2_toy")
    cfg = load_config(overrides={"cascade": {"max_rounds": mo.R_ROUNDS}}); eng = CascadeEngine(bp, cfg); rows = []; agree = 0
    for xi in range(1 << mo.L):
        x = [(xi >> l) & 1 for l in range(mo.L)]; out = [l for l in range(mo.L) if x[l]]
        Sf = eng.run(out, mode="dc").S if out else 0.0; ref = mo.classical_oracle(x)
        lab_f = Sf >= mo.TAU - 1e-9; agree += lab_f == ref["flag"]; rows.append({"x": x, "S_float_engine": Sf, "S_fixed_point_A2": ref["S"], "label_float": bool(lab_f), "label_A2": bool(ref["flag"])})
    return {"n": 1 << mo.L, "label_agreement": agree / (1 << mo.L), "rows": rows,
            "note": "differences come from b=6 fixed point (1/8 p.u. lsb) and the engine's round/termination semantics; the A2 circuit is EXACT against its own fixed-point predicate"}

def e14(config, ctx) -> ExpOutput:
    c, lay = mo.build(); v = mo.verify(c, lay); cal = mo.calibration(); scal = mo.primitive_scaling()
    ok = all(v[k] for k in ("flag_equals_classical_oracle", "intermediate_flows_and_served_equal_classical", "kickback_target_flips_iff_marked",
                            "ancillas_clean_after_uncompute", "inputs_unchanged", "inverse_restores_input"))
    kap = {k: d["kappa_cal"] for k, d in cal.items() if isinstance(d, dict) and d.get("kappa_cal") is not None}
    lo, hi = SP.E14_KAPPA_RANGE
    verdict = {k: ("within V2 expectation 0.5-2" if lo <= x <= hi else ("kappa >> 1: V2 formula UNDERESTIMATES this primitive (V2 E14 failure interpretation: oracle cost underestimated)"
               if x > hi else "kappa < 0.5: V2 formula OVERESTIMATES this primitive")) for k, x in kap.items()}
    payload = {"instance": {"buses": mo.B_BUS, "branches": mo.L, "bits": mo.B_BITS, "frac_bits": mo.F, "rounds": mo.R_ROUNDS, "tau": mo.TAU, "ratings_int": mo.ratings_int(),
                            "loads_int": mo.loads_int(), "threshold_served_int": mo.threshold_int(), "label_propagation_iterations": mo.D_ITER},
               "verification": {k: x for k, x in v.items() if k != "rows"}, "verification_rows": v["rows"], "all_checks_pass": ok,
               "qubits": c.n, "toffoli_equiv_total": c.counts()["TOTAL"]["toffoli_equiv"], "gates_total": c.counts()["TOTAL"]["gates"],
               "calibration": {k: x for k, x in cal.items() if not k.startswith("_")}, "counts_by_primitive": cal["_counts_by_primitive"],
               "kappa_verdicts": verdict, "primitive_scaling_vs_b": scal, "float_engine_agreement": _float_engine_agreement(),
               "full_grover_on_A2": f"NOT RUN: {c.n} qubits exceeds statevector reach (V2: <= ~30); A2 is validated through exhaustive basis simulation and the O1 chain",
               "synthesis_note": "textbook synthesis (VBE ripple-carry adders, masked controlled adds, shift-and-add multipliers, naive QROM, local uncompute "
                                 "inside comparators); kappa therefore calibrates THIS synthesis, an upper-end reference -- optimised arithmetic would lower it"}
    parts = [Part("A2_exhaustive_verification", "EXECUTED" if ok else "FAILED", kind="SYNTHESIZED", reason="" if ok else "a V2 13.4 check failed"),
             Part("kappa_calibration_per_primitive", "EXECUTED", kind="SYNTHESIZED"), Part("float_engine_O1_link", "EXECUTED", kind="HAND_SOLVED")]
    return ExpOutput(parts=parts, payload=payload, criteria=[{"criterion": f"kappa_cal within {SP.E14_KAPPA_RANGE}", "per_primitive": verdict}],
                     limitations=["Toy scale (4 buses, 5 branches, b=6, R=2); the per-topology QROM replaces V2's small inverse, which stays UNCALIBRATED.",
                                  "Toffoli-equivalent convention: CCX=1, MCX(c>=3)=2c-3; Clifford gates free."],
                     parameters={"bits": mo.B_BITS, "rounds": mo.R_ROUNDS})
