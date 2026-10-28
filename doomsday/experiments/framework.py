"""Phase 7 experiment framework: statuses, provenance, manifests, failure handling. Honesty is structural: an experiment's status is DERIVED from its
parts, so nothing can be reported as executed unless a part really executed, and IEEE-14 (transcribed, unverified) results can never be labelled as
verified evidence. No experiment ever substitutes a different dataset for a pre-registered one."""
from __future__ import annotations
import hashlib, json, os, platform, time, traceback
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np, scipy
from .. import __version__
from ..config import config_hash, load_config
from ..gridtwin import loader

PART_STATUS = ("EXECUTED", "NOT_RUN", "NOT_IMPLEMENTED", "FAILED")
STATUS = ("EXECUTED", "PARTIAL", "NOT_RUN", "NOT_IMPLEMENTED", "FAILED")
DATA = ("NO_GRID_DATA", "UNVERIFIED_DATA", "OFFICIAL_DATA")
KINDS = {"MEASURED": "[MEASURED]", "EMULATED": "[EMULATED] Tier B exact classical emulation (not a quantum runtime)", "NUMPY_STATEVECTOR": "[SIMULATED] NumPy statevector simulation (not Aer, not hardware)",
         "ESTIMATED": "[ESTIMATED] analytical model (not calibrated)", "HAND_SOLVED": "[MEASURED] against hand-solved/analytic references",
         "AER_SIMULATED": "[SIMULATED] Qiskit Aer simulation (classical simulator of an ideal or noise-modelled device; not hardware)",
         "ESTIMATED_PARTIAL": "[ESTIMATED] analytical model: V2 formulas, reported both uncalibrated and with toy-scale partial kappa calibration (never fully calibrated)",
         "SYNTHESIZED": "[MEASURED] gate counts of a synthesized reversible circuit, verified by exhaustive basis-state simulation", "NONE": ""}
GRID_FILES = {"ieee14": "case14.m", "ieee30": "case30.m", "ieee118": "case118.m"}
UNVERIFIED_TAIL = " — EXPLORATORY — UNVERIFIED DATA (transcribed IEEE-14; not validated benchmark evidence)"

@dataclass
class Part:
    name: str; status: str; data_status: str = "NO_GRID_DATA"; kind: str = "NONE"; reason: str = ""; dataset: str | None = None
    def __post_init__(self):
        if self.status not in PART_STATUS or self.data_status not in DATA or self.kind not in KINDS: raise ValueError((self.status, self.data_status, self.kind))
        if self.status != "EXECUTED" and not self.reason.strip(): raise ValueError(f"part {self.name!r}: a non-executed part must state its reason")
    def label(self) -> str:
        if self.status != "EXECUTED": return f"[{self.status}] {self.reason}"
        return (KINDS[self.kind] + (UNVERIFIED_TAIL if self.data_status == "UNVERIFIED_DATA" else "")).strip()

def aggregate_status(parts) -> str:
    st = [p.status for p in parts]
    if not st: return "NOT_RUN"
    if "FAILED" in st: return "FAILED"
    if all(s == "EXECUTED" for s in st): return "EXECUTED"
    if any(s == "EXECUTED" for s in st): return "PARTIAL"
    return "NOT_IMPLEMENTED" if all(s == "NOT_IMPLEMENTED" for s in st) else "NOT_RUN"

def aggregate_data_status(parts) -> str:
    ex = [p.data_status for p in parts if p.status == "EXECUTED"]
    return "UNVERIFIED_DATA" if "UNVERIFIED_DATA" in ex else ("OFFICIAL_DATA" if "OFFICIAL_DATA" in ex else "NO_GRID_DATA")

def experiment_label(parts) -> str:
    st, ds = aggregate_status(parts), aggregate_data_status(parts)
    if st in ("NOT_RUN", "NOT_IMPLEMENTED", "FAILED"): return f"[{st}]"
    kinds = sorted({KINDS[p.kind] for p in parts if p.status == "EXECUTED" and KINDS[p.kind]})
    return (f"[{st}] " + "; ".join(kinds) + (UNVERIFIED_TAIL if ds == "UNVERIFIED_DATA" else "")).strip()

def dataset_info(name: str) -> dict:
    if name not in GRID_FILES: raise ValueError(f"unknown dataset {name!r}")
    p = loader.DATA_DIR / GRID_FILES[name]
    if not p.exists(): return {"name": name, "available": False, "verified": False, "provenance_status": "ABSENT", "file_sha256": None, "matpower_commit": None}
    pr = loader.provenance(p)
    return {"name": name, "available": True, "verified": pr.get("status") == "official_matpower", "provenance_status": pr.get("status"),
            "file_sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "matpower_commit": pr.get("matpower_commit")}

def data_status_for(name: str) -> str:
    d = dataset_info(name)
    if not d["available"]: raise LookupError(f"dataset {name} unavailable")
    return "OFFICIAL_DATA" if d["verified"] else "UNVERIFIED_DATA"

def unavailable_part(name: str, dataset: str, protocol: str) -> Part:
    d = dataset_info(dataset)
    why = (f"official MATPOWER {GRID_FILES[dataset]} is not installed/verified (provenance: {d['provenance_status']}); the pre-registered protocol ({protocol}) is NOT RUN and no smaller or unverified dataset is substituted"
           if not (d["available"] and d["verified"]) else "official data present but this protocol part is not wired to run it")
    return Part(name, "NOT_RUN", reason=why, dataset=dataset)

def to_jsonable(x):
    if isinstance(x, dict): return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [to_jsonable(v) for v in x]
    if isinstance(x, np.ndarray): return to_jsonable(x.tolist())
    if isinstance(x, np.floating): return to_jsonable(float(x))
    if isinstance(x, np.integer): return int(x)
    if isinstance(x, np.bool_): return bool(x)
    if isinstance(x, float):
        if x != x: return None
        if x in (float("inf"), float("-inf")): return "inf" if x > 0 else "-inf"
    if isinstance(x, Path): return str(x)
    return x

def canonical(x) -> str: return json.dumps(to_jsonable(x), sort_keys=True, separators=(",", ":"), allow_nan=False)
def digest(x) -> str: return hashlib.sha256(canonical(x).encode()).hexdigest()
def file_sha(p) -> str: return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def environment() -> dict:
    try: import sklearn; sk = sklearn.__version__
    except Exception: sk = None
    try: import matplotlib; mp = matplotlib.__version__
    except Exception: mp = None
    return {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sk, "matplotlib": mp, "doomsday": __version__,
            "threads_env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}, "cpu_count": os.cpu_count()}

def code_sha() -> str:
    h = hashlib.sha256(); root = Path(__file__).resolve().parent.parent
    for f in sorted(root.rglob("*.py"), key=lambda p: p.as_posix()): h.update(f.relative_to(root).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()

ACCOUNTING_KEYS = ("classical_function_evaluations", "quantum_oracle_calls_emulated", "classical_verification_calls", "preprocessing_evaluations", "estimated_quantum_runtime_s")
def accounting(**kw) -> dict:
    """The five cost classes are ALWAYS separate keys (None = not applicable). They are never summed."""
    bad = set(kw) - set(ACCOUNTING_KEYS) - {"notes"}
    if bad: raise KeyError(bad)
    return {**{k: kw.get(k) for k in ACCOUNTING_KEYS}, "notes": kw.get("notes", "")}

@dataclass
class ExpOutput:
    parts: list; payload: dict = field(default_factory=dict); timing: dict = field(default_factory=dict); figures: list = field(default_factory=list)
    accounting: dict = field(default_factory=lambda: accounting()); limitations: list = field(default_factory=list); criteria: list = field(default_factory=list)
    seeds: list = field(default_factory=list); parameters: dict = field(default_factory=dict); datasets_used: list = field(default_factory=list)

@dataclass
class Ctx:
    results_root: Path = Path("results/phase7"); tables_dir: Path = None; cfg: object = None
    def __post_init__(self):
        self.results_root = Path(self.results_root); self.tables_dir = Path(self.tables_dir) if self.tables_dir else self.results_root / "tables"; self.cfg = self.cfg or load_config()
    def exp_dir(self, eid: str) -> Path: d = self.results_root / eid; d.mkdir(parents=True, exist_ok=True); return d
    def load_result(self, eid: str):
        p = self.results_root / eid / "result.json"; return json.loads(p.read_text()) if p.exists() else None
    def load_manifest(self, eid: str):
        p = self.results_root / eid / "manifest.json"; return json.loads(p.read_text()) if p.exists() else None

def build_manifest(spec, config, out, ctx, started, error=None, config_file=None) -> dict:
    eid = spec["id"]; parts = out.parts if out else []; status = "FAILED" if error else aggregate_status(parts); outputs = {}; d = ctx.results_root / eid
    for p in sorted(d.glob("*")) if d.exists() else []:
        if p.is_file() and p.name != "manifest.json": outputs[str(p)] = file_sha(p)
    m = {"experiment_id": eid, "name": spec["name"], "v2_section": spec.get("v2_section"), "priority": spec.get("priority"), "status": status, "data_status": aggregate_data_status(parts),
         "evidence_label": "[FAILED]" if error else experiment_label(parts),
         "parts": [{"name": p.name, "status": p.status, "data_status": p.data_status, "kind": p.kind, "dataset": p.dataset, "reason": p.reason, "label": p.label()} for p in parts],
         "config": {"file": config_file, "params": to_jsonable(config.get("params", config)), "datasets": to_jsonable(config.get("datasets")), "config_hash": digest(config), "base_config_hash": config_hash(ctx.cfg)},
         "datasets": {n: dataset_info(n) for n in sorted(set((out.datasets_used if out else []) + [dd["name"] for dd in config.get("datasets", [])]))},
         "seeds": to_jsonable(out.seeds) if out else [], "parameters_and_stopping_conditions": to_jsonable(out.parameters) if out else {}, "accounting": out.accounting if out else accounting(),
         "limitations": out.limitations if out else [], "acceptance_criteria": to_jsonable(out.criteria) if out else [], "implementation": {"package_version": __version__, "source_sha256": code_sha()},
         "environment": environment(), "runtime_s": time.perf_counter() - started, "outputs": outputs, "result_digest": digest(out.payload) if out else None, "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if error: m["error"] = error
    return m

def run_experiment(spec: dict, fn, config: dict, ctx: Ctx, config_file: str | None = None, figure_fn=None) -> dict:
    """Run one experiment with failure isolation. Always writes manifest.json; result.json (and figures) only for non-failed runs."""
    t0 = time.perf_counter(); d = ctx.exp_dir(spec["id"])
    for old in d.glob("*"):                                   # stale outputs from a previous run must not masquerade as this run's
        if old.is_file(): old.unlink()
    out, err = None, None
    try:
        out = fn(config, ctx)
        if not isinstance(out, ExpOutput) or not out.parts: raise RuntimeError("experiment returned no parts")
        res = to_jsonable({"experiment_id": spec["id"], "payload": out.payload, "timing": out.timing, "parts": [p.__dict__ for p in out.parts]})
        (d / "result.json").write_text(json.dumps(res, indent=1))
        if figure_fn: figure_fn(spec["id"], res, d)
    except Exception:
        err = traceback.format_exc(); out = None
    m = build_manifest(spec, config, out, ctx, t0, err, config_file)
    (d / "manifest.json").write_text(json.dumps(to_jsonable(m), indent=1)); return m
