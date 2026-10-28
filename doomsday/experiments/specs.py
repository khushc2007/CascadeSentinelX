"""E0-E16 registry (V2 18). Every pre-registered threshold and decision rule used by the experiment code lives HERE and was committed
to version control before any Phase 7 experiment was executed (see git history of this file). Changing a threshold after results exist
must be recorded in DEVIATIONS with a reason; experiment code reads thresholds only from this module.

Dataset roles:
  PRE   pre-registered by V2 (if unavailable or computationally infeasible -> that part is NOT_RUN, never substituted)
  SUPP  supplementary (added by the implementation; reported separately, never used to satisfy a PRE part)
"""
from __future__ import annotations

PRE, SUPP = "pre_registered", "supplementary"
REGISTERED_ON = "2026-10-23"

# ---- pre-registered decision rules (V2 10.1, 15.2, 18.1) ---------------------------------------------------------------------------
TAU = 0.20                         # V2 20.2 severity.tau
DELTA_CASCADE = 0.10               # V2 20.2 severity.delta_cascade
BAND = 1e-9                        # tie band (V2 12.3)
E3_RULE = {"recall_at_tau_min": 0.9, "top10_overlap_min": 0.5,
           "top10_overlap_definition": "|tie-expanded DC top-10 INTERSECT tie-expanded AC top-10| / |tie-expanded AC top-10| (share of AC's worst sets "
                                       "that DC also ranks in its top-10); label: DC positive = S_dc >= tau, AC positive = S_ac >= tau",
           "verdict_if_met": "DC screening trustworthy for this model", "verdict_if_not": "DC is a poor proxy here"}
F1 = {"name": "structured classical finds the AC-verified Smax in << sqrt(N) evaluations at all tested sizes",
      "much_less_than_factor": 0.1,   # '<<' pre-registered as: mean discovery unique evaluations <= 0.1 * sqrt(N)
      "structured_methods": ["hillclimb", "beam", "lodf_pool", "ml_screen", "milp", "bnb", "sa", "ga"],
      "oracle": "AC truth table where an exhaustive AC table exists (search run directly on the AC predicate)"}
F2 = {"name": "DC recall at tau below the 10.1 threshold", "recall_min": E3_RULE["recall_at_tau_min"]}
F3 = {"name": "top-10 Jaccard across rating families below ~0.3", "jaccard_min": 0.3,
      "jaccard_definition": "tie-expanded top-10 Jaccard of each non-baseline rating family vs the baseline family; F3 is met if the MEDIAN over "
                            "(family, grid) pairs is < 0.3"}
HC1 = {"name": "H-C1: at least one structured baseline finds Smax in fewer unique evaluations than c*sqrt(N) for most (grid,k) pairs",
       "c_source": "E6 fitted c_hat (discovery quantum calls / sqrt(N)) for the same table; the proven 22.5 bound is reported alongside",
       "most": 0.5}
E7_BUDGET = {"rule": "budget = ceil(0.5 N) unique evaluations if N <= 1e5, else ceil(50 sqrt(N)) (compute cap, stated)", "small_N": 100_000}
E7_SEEDS = 50
E7_TUNING = {"held_out": ("ieee30", 2), "seeds": 20, "objective": "mean discovery unique evaluations among successful runs; ties -> higher success",
             "note": "held-out pair is excluded from the comparison tables (V2 15.2)"}
E6_SEEDS = 200
E1_SAMPLES = {"random": 1000, "high_severity": 1000, "k": 3, "long_cascade_rounds": 4,
              "high_severity_definition": "uniform sample from the top 1% of the DC truth table (k=3) by S"}
E11_MAIN = {"headroom_h": [0.10, 0.25, 0.50], "stress_lambda": [1.0, 1.1, 1.2, 1.3], "trip_factor": [1.0, 1.1, 1.2, 1.25],
            "families": ["proportional", "n1_covering", "voltage_class", "case_file"], "perturb_frac": 0.10, "perturb_draws": 50,
            "trip_policy": ["all_overloaded", "most_overloaded_first"], "ladder_step": [0.01, 0.05, 0.10], "redispatch": ["up_and_down", "no_upward"],
            "max_rounds": [5, 10, 30]}
E11_GRID_K = {"ieee14": 3, "ieee30": 3, "ieee118": 2}
E11_PERTURB_DRAWS = {"ieee14": 50, "ieee30": 50, "ieee118": 10}
E11_AC = {"ieee14": 3, "ieee30": 2}                   # ladder-step and AC-tolerance variants (AC tables)
E11_APPENDIX = {"ac_tol_pu": [1e-6, 1e-8, 1e-10], "ladder_step": [0.01, 0.05, 0.10]}
E12_BITS = [12, 16, 20, 24, 32]
E12_RULE = {"label_agreement_min": 1.0, "top10_jaccard_min": 1.0,
            "rule": "minimum passing b = smallest b whose high-severity labels (S>=tau) agree on every set AND whose tie-expanded top-10 equals the float64 top-10"}
E9 = {"T": [1, 5, 10, 50], "seeds": 50, "tables": [("ieee14", 3), ("ieee30", 3), ("ieee118", 2), ("ieee118", 3)],
      "rule": "report mean total quantum calls / sum_{j<=T} sqrt(N/j) and / 2 sqrt(NT); 'tracks sqrt(NT)' if the log-log slope in T of mean calls is within 0.5 +- 0.15",
      "correct": "the T returned sets carry exactly the T largest S values (ties allowed)"}
E10 = {"grid": "ieee14", "shots": 4096, "p_max": 4, "starts": 10, "T_verify": 10, "n_train": [100, 200, 400, 800], "ridge_k2": 1e-6, "ridge_k3": 1e-3,
       "planted": {"L": 20, "k": 3, "seed": 0, "rule": "recovered iff x* appears in the 4096 shots AND P(x*) >= 10/N at the best p"},
       "verify_rule": "top-T = the T distinct sampled strings with the highest SURROGATE value; each is evaluated with the true oracle (T calls)",
       "aer_crosscheck": {"candidates": list(range(10)), "k": 2, "p": 2, "tol": 1e-8}}
E12_GRID_K = {"ieee14": 3, "ieee30": 3, "ieee118": 2}
E14_KAPPA_RANGE = (0.5, 2.0)

DEVIATIONS = [
    {"id": "E3b-k", "what": "V2 E3b samples IEEE-118 k=4; the DC k=4 table (48.3M sets, ~96 core-hours here) is NOT built, so pre-registered E3b is NOT_RUN. "
                           "A SUPPLEMENTARY stratified AC sample on IEEE-118 k=3 is reported separately.", "registered": REGISTERED_ON},
    {"id": "E3a-118k3", "what": "Exhaustive AC on IEEE-118 k=3 (1.06M sets, ~21 core-hours here) is NOT_RUN (compute); k<=2 is exhaustive.", "registered": REGISTERED_ON},
    {"id": "E2-118k4", "what": "IEEE-118 k=4 DC table NOT_RUN (compute, ~96 core-hours on this 2-vCPU machine).", "registered": REGISTERED_ON},
    {"id": "E0-reference", "what": "V2 names pandapower as the reference solver; pandapower 3.5.6's MATPOWER converter fails on case14 (no BASE_KV). "
                                   "The reference used is PYPOWER 5.1 (the MATPOWER port that pandapower's solver derives from) on the identical official case data.",
     "registered": REGISTERED_ON},
    {"id": "E6-y0", "what": "Secondary Durr-Hoyer run: y0 = best S of a hill climb limited to ceil(sqrt(N)) unique classical evaluations (seed-matched); "
                            "those classical evaluations are reported separately and never added to the quantum count.", "registered": REGISTERED_ON},
    {"id": "E11-118", "what": "E11 on IEEE-118 uses k=2 (17,205 sets per variant) and 10 perturbation draws instead of k=3 (1.06M sets, ~2 core-h per "
                              "variant) and 50 draws: compute. IEEE-14 and IEEE-30 use k=3 and 50 draws as pre-registered.", "registered": REGISTERED_ON},
    {"id": "E9-variants", "what": "Development (before any E9 run) found V2's literal 'repeated maximum finding with an exclusion list' costs ~T*sqrt(N); "
                                  "E9 therefore reports BOTH that scheme and the threshold-list scheme (keep T candidates, mark S > min(list)); the sqrt(NT) rule is "
                                  "evaluated on each separately.", "registered": REGISTERED_ON},
    {"id": "E12-118", "what": "E12 on IEEE-118 uses k=2 (compute, as E11-118); the minimum passing b is the largest of the per-grid minima.", "registered": REGISTERED_ON},
    {"id": "E12-truncation", "what": "Minimum passing b is decided at max_rounds=30; truncation to the E2-measured p95 rounds is reported separately (V2 17.1 combines them).",
     "registered": REGISTERED_ON},
    {"id": "E10-scope", "what": "E10 runs on IEEE-14 (L=20) only, as listed in V2; the Aer cross-check uses a 10-branch candidate shortlist (L <= 12 rule of V2 14.2).",
     "registered": REGISTERED_ON},
    {"id": "E11-baseline", "what": "E11 baseline = the configuration used by every other experiment (rating.family=n1_covering, h=0.25, lambda=1.1, "
                                   "trip_factor=1.0, all_overloaded, up_and_down, max_rounds=30, ladder_step=0.05); each factor is varied one at a time.",
     "registered": REGISTERED_ON},
    {"id": "E11-families","what": "'nominal MVA by voltage class' implemented as a uniform per-base-kV-class rating ((1+h) x class max base flow); case14 has no "
                                   "BASE_KV and case30 one class, so the family is a uniform rating there. case_file ratings exist only for IEEE-30.", "registered": REGISTERED_ON},
]

def _ds(*names, role=PRE): return [{"name": n, "role": role} for n in names]

SPECS = {
    "E0":  {"id": "E0",  "name": "Simulator validation", "v2_section": "18 E0; 19 U1-U9, U7", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E1":  {"id": "E1",  "name": "Runtime profile", "v2_section": "18 E1; 6.3", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E2":  {"id": "E2",  "name": "Cascade phenomenology", "v2_section": "18 E2", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E3":  {"id": "E3",  "name": "DC-AC agreement", "v2_section": "10.1; 18 E3", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E4":  {"id": "E4",  "name": "Oracle and circuit equivalence", "v2_section": "18 E4; 19 Q1-Q6, O1", "priority": "M", "phase": 8, "datasets": []},
    "E5":  {"id": "E5",  "name": "Grover dynamics, ideal and noisy", "v2_section": "13.1; 18 E5", "priority": "S (ideal M)", "phase": 8, "datasets": []},
    "E6":  {"id": "E6",  "name": "GAS / Durr-Hoyer scaling", "v2_section": "12.2; 18 E6", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E7":  {"id": "E7",  "name": "Classical comparison", "v2_section": "15; 18 E7", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E8":  {"id": "E8",  "name": "Threshold regime map", "v2_section": "12 (Problem 3); 18 E8", "priority": "S", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E9":  {"id": "E9",  "name": "Top-T cost", "v2_section": "12 (Problem 5); 18 E9", "priority": "N", "phase": 10, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E10": {"id": "E10", "name": "QAOA surrogate comparison (a, b, c)", "v2_section": "14; 18 E10", "priority": "S", "phase": 10, "datasets": _ds("ieee14")},
    "E11": {"id": "E11", "name": "Rating / trip / ladder robustness", "v2_section": "17; 18 E11", "priority": "M", "phase": 7, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E12": {"id": "E12", "name": "Fixed-point precision and truncation", "v2_section": "17.1; 18 E12", "priority": "S", "phase": 10, "datasets": _ds("ieee14", "ieee30", "ieee118")},
    "E13": {"id": "E13", "name": "Hardware run (A1 toy on an IBM device)", "v2_section": "13.1; 18 E13", "priority": "N [OPTIONAL]", "phase": 8, "datasets": []},
    "E14": {"id": "E14", "name": "Micro-oracle synthesis and calibration", "v2_section": "13.4; 18 E14", "priority": "S (high value)", "phase": 11, "datasets": []},
    "E15": {"id": "E15", "name": "Resource and crossover sensitivity", "v2_section": "16; 17; 18 E15", "priority": "M", "phase": 11, "datasets": _ds("ieee118")},
    "E16": {"id": "E16", "name": "Falsification summary", "v2_section": "18.1; 18 E16", "priority": "M", "phase": 14, "datasets": []},
}
GRID_KS_DC = {"ieee14": [1, 2, 3, 4], "ieee30": [1, 2, 3, 4], "ieee118": [1, 2, 3]}     # 118 k=4: NOT_RUN (compute)
GRID_KS_AC = {"ieee14": [1, 2, 3, 4], "ieee30": [1, 2, 3], "ieee118": [1, 2]}           # 118 k=3 AC: NOT_RUN (compute)
PRE_KS = {"E2": {"ieee14": [1, 2, 3, 4], "ieee30": [1, 2, 3, 4], "ieee118": [1, 2, 3, 4]},
          "E3a": {"ieee14": [1, 2, 3, 4], "ieee30": [1, 2, 3], "ieee118": [1, 2, 3]}}
COMPUTE_NOT_RUN = {("E2", "ieee118", 4): "DC table 48,277,230 sets: ~96 core-hours on this 2-vCPU machine",
                   ("E3a", "ieee118", 3): "exhaustive AC on 1,055,240 sets: ~21 core-hours on this 2-vCPU machine",
                   ("E3b", "ieee118", 4): "needs the IEEE-118 k=4 DC table (see E2) to stratify"}

def config_for(eid: str, **params) -> dict:
    s = SPECS[eid]
    return {"params": dict(params), "datasets": s["datasets"], "registered_on": REGISTERED_ON}
