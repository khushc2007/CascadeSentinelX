"""Phase 12: FastAPI layer (V2 20.3). Precomputed-first: every GET reads app/data/*.json built by scripts/build_demo_data.py; live computation is
optional and limited to IEEE-14/30 (V2). The static front end (app/) is served at / so one process runs the whole demo offline.
  PYTHONPATH=. uvicorn doomsday.api.app:app --port 8000
Every response carries an `evidence` label; invalid inputs return 4xx with a message, never a silently corrected answer."""
from __future__ import annotations
import json, os
from functools import lru_cache
from math import comb
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = Path(os.environ.get("GDF_APP_DIR", ROOT / "app")); DATA_DIR = Path(os.environ.get("GDF_DATA_DIR", APP_DIR / "data"))
LIVE_GRIDS = {"ieee14", "ieee30"}; ALL_GRIDS = {"ieee14": 20, "ieee30": 41, "ieee118": 186}

app = FastAPI(title="Grid Doomsday Finder API", version="0.2.0",
              description="Precomputed-first API for the N-k cascade search benchmark. Labels: [MEASURED] [EMULATED] [MODELLED] [PROPOSED]. No quantum advantage is claimed.")

@lru_cache(maxsize=64)
def _load(name: str):
    p = DATA_DIR / name
    if not p.exists(): raise HTTPException(404, f"precomputed file {name} not found; run scripts/build_demo_data.py")
    return json.loads(p.read_text())

def _grid_or_404(grid: str):
    if grid not in ALL_GRIDS: raise HTTPException(404, f"unknown grid {grid!r}; known: {sorted(ALL_GRIDS)}")

@app.get("/health")
def health():
    return {"status": "ok", "data_dir": str(DATA_DIR), "data_present": (DATA_DIR / "index.json").exists(), "live_grids": sorted(LIVE_GRIDS)}

@app.get("/grids")
def grids():
    return {"grids": _load("index.json")["grids"], "evidence": "[MEASURED] official MATPOWER 8.1 cases; synthetic ratings (see docs)"}

@app.get("/grid/{grid}")
def grid(grid: str):
    _grid_or_404(grid); return _load(f"grid_{grid}.json")

@app.get("/ranking")
def ranking(grid: str, k: int, T: int = 10):
    _grid_or_404(grid)
    if not 1 <= T <= 20: raise HTTPException(422, "T must be in [1, 20] (precomputed top-20)")
    r = _load(f"ranking_{grid}_k{k}.json"); return {**r, "rows": r["rows"][:T]}

class CascadeReq(BaseModel):
    grid: str; outage: list[int] = Field(min_length=1, max_length=8); mode: Literal["dc", "ac"] = "dc"
    policy: Literal["all_overloaded", "most_overloaded_first"] = "all_overloaded"
    @field_validator("outage")
    @classmethod
    def distinct(cls, v):
        if len(set(v)) != len(v): raise ValueError("outage indices must be distinct")
        return sorted(v)

@app.post("/cascade")
def cascade(req: CascadeReq):
    _grid_or_404(req.grid); L = ALL_GRIDS[req.grid]
    if any(not 0 <= l < L for l in req.outage): raise HTTPException(422, f"branch indices must be in [0, {L - 1}] for {req.grid}")
    for name in (f"top_cascades_{req.grid}_k{len(req.outage)}.json",):                       # precomputed first
        p = DATA_DIR / name
        if p.exists() and req.policy == "all_overloaded":
            for row in _load(name):
                d = row.get(req.mode)
                if d and d["outage"] == req.outage: return {**d, "source": "precomputed"}
    if req.grid not in LIVE_GRIDS: raise HTTPException(409, f"live cascades are limited to {sorted(LIVE_GRIDS)} (V2 20.3); {req.grid} serves precomputed sets only")
    from ..experiments.common import bp_cached, cfg_for
    from ..gridtwin.cascade import CascadeEngine
    cfg = cfg_for(req.grid, {"cascade": {"trip_policy": req.policy}}); r = CascadeEngine(bp_cached(req.grid, cfg), cfg).run(req.outage, mode=req.mode)
    d = r.to_dict(frames=True); d["grid"] = req.grid; d["source"] = "live"
    d["metrics"]["cascade_driven"] = bool(r.S >= 0.2 - 1e-9 and r.C >= 0.1 - 1e-9); d["evidence"] = f"[MEASURED] live cascade run ({req.mode.upper()}, quasi-steady-state model)"
    return d

class SearchReq(BaseModel):
    grid: str; k: int = Field(ge=1, le=8); seed: int = Field(default=0, ge=0, le=10_000)

@app.post("/search")
def search(req: SearchReq):
    _grid_or_404(req.grid)
    if req.seed == 0: return {**_load(f"search_{req.grid}_k{req.k}.json"), "source": "precomputed"}
    if req.grid not in LIVE_GRIDS: raise HTTPException(409, "live emulation (seed != 0) is limited to IEEE-14/30")
    from ..api.demo_data import search_log
    from ..experiments.framework import Ctx
    try: d = search_log(Ctx(results_root=ROOT / "results/phase7"), req.grid, req.k, req.seed)
    except LookupError as e: raise HTTPException(404, str(e))
    return {**d, "source": "live"}

class CrossoverReq(BaseModel):
    grid: Literal["ieee14", "ieee30", "ieee118"] = "ieee118"; k: int = Field(default=3, ge=1, le=40)
    scenario: Literal["optimistic", "realistic", "pessimistic"] = "realistic"; prep: Literal["v2_assumed", "be_counted", "tree_counted"] = "be_counted"
    calibrated: bool = True; t_toffoli_s: float | None = Field(default=None, gt=0); P: int | None = Field(default=None, ge=1); alpha: float | None = Field(default=None, gt=0, le=1.5)
    c_q: float | None = Field(default=None, gt=0)

@app.post("/crossover")
def crossover(req: CrossoverReq):
    from ..resource.params import ModelParams
    from ..resource.scenarios import evaluate
    L, B = {"ieee14": (20, 14), "ieee30": (41, 30), "ieee118": (186, 118)}[req.grid]
    if req.k > L: raise HTTPException(422, f"k must be <= L={L}")
    if req.prep == "tree_counted" and comb(L, req.k) > 5e7: raise HTTPException(422, "tree_counted preparation is only evaluated for C(L,k) <= 5e7")
    cx = _load("crossover.json"); base = (cx.get("scenario_params_measured") or {}).get(req.scenario)
    p = ModelParams(**{k: v for k, v in base.items()}) if base else ModelParams()
    over = {k: v for k, v in (("t_toffoli_s", req.t_toffoli_s), ("P", req.P), ("alpha", req.alpha), ("c_q", req.c_q)) if v is not None}
    if over: p = p.with_(source="API slider override", **over)
    kap = cx.get("kappa_cal") if req.calibrated else None
    r = evaluate(L, B, req.k, req.scenario, req.prep, p, kappa=kap, kappa_source="E14")
    return {"inputs": r["inputs"], "G": r["toffoli_per_grover_iteration"]["G"], "Tq_s": r["totals"]["quantum_total_time_s"], "Tc_s": r["separate_costs"]["classical_time_s"],
            "ratio_Tq_over_Tc": r["totals"]["ratio_Tq_over_Tc"], "N_star": r["crossover"]["N_star"] if r["crossover"]["N_star"] != float("inf") else "inf",
            "k_bracket": r["crossover"]["k_bracket_at_N_star"], "calibrated": r["calibrated"], "logical_qubits": r["logical_qubits"]["total"],
            "evidence": "[MODELLED] analytical resource estimate; " + ("partially calibrated with E14 kappa" if kap else "uncalibrated V2 formulas") + "; no quantum advantage claimed"}

@app.get("/evidence")
def evidence():
    return {"experiments": _load("evidence.json"), "legend": ["[MEASURED]", "[EMULATED]", "[MODELLED]", "[PROPOSED]"]}

@app.exception_handler(ValueError)
async def value_error(_, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})

if APP_DIR.exists():                                       # static front end (offline demo) at /
    @app.get("/")
    def index():
        f = APP_DIR / "index.html"
        if not f.exists(): raise HTTPException(404, "front end not built")
        return FileResponse(f)
    app.mount("/", StaticFiles(directory=str(APP_DIR)), name="app")
