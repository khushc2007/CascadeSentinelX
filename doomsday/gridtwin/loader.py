"""MATPOWER case-file loader -> internal Grid (V2 5.1). No dependency on any grid library."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
import numpy as np
from .model import Grid, PQ, PV, SLACK

DATA_DIR = Path(__file__).resolve().parent / "data"
_BUILTIN = {"ieee14": "case14.m", "ieee30": "case30.m", "ieee118": "case118.m"}   # official MATPOWER names, as installed by scripts/verify_case_files.py --install

def _strip_comments(text: str) -> str:
    return "\n".join(line.split("%", 1)[0] for line in text.splitlines())

def _matrix(text: str, name: str) -> np.ndarray:
    m = re.search(r"mpc\.%s\s*=\s*\[(.*?)\]\s*;" % name, text, re.S)
    if not m:
        raise ValueError(f"MATPOWER section 'mpc.{name}' not found")
    rows = []
    for line in m.group(1).replace(";", "\n").splitlines():
        line = line.strip().replace(",", " ")
        if line:
            rows.append([float(v) for v in line.split()])
    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise ValueError(f"mpc.{name}: ragged rows {sorted(widths)}")
    return np.array(rows, dtype=np.float64)

def parse_matpower(text: str, name: str = "case", source: dict | None = None) -> Grid:
    t = _strip_comments(text)
    m = re.search(r"mpc\.baseMVA\s*=\s*([0-9.eE+\-]+)\s*;", t)
    if not m:
        raise ValueError("mpc.baseMVA not found")
    base = float(m.group(1))
    bus, gen, br = _matrix(t, "bus"), _matrix(t, "gen"), _matrix(t, "branch")
    if bus.shape[1] < 13 or gen.shape[1] < 10 or br.shape[1] < 11:
        raise ValueError("bus/gen/branch tables have too few columns for MATPOWER format")
    ids = bus[:, 0].astype(int)
    if len(set(ids.tolist())) != len(ids):
        raise ValueError("duplicate bus ids")
    idx = {int(i): k for k, i in enumerate(ids)}
    btype = bus[:, 1].astype(int)
    if np.any(btype == 4):
        raise ValueError("isolated (type 4) buses are not supported")
    notes = []
    gbus = np.array([idx[int(g)] for g in gen[:, 0]], dtype=int)
    gstat = gen[:, 7].astype(int)
    # PV bus without an in-service generator behaves as PQ (MATPOWER convention); record it.
    for bi in np.flatnonzero(btype == PV):
        if not np.any((gbus == bi) & (gstat > 0)):
            btype[bi] = PQ
            notes.append(f"bus {ids[bi]}: PV without in-service generator -> PQ")
    if np.count_nonzero(btype == SLACK) != 1:
        raise ValueError("case must contain exactly one slack (type 3) bus")
    sl = int(np.flatnonzero(btype == SLACK)[0])
    if not np.any((gbus == sl) & (gstat > 0)):
        raise ValueError("slack bus has no in-service generator")
    vset = gen[:, 5].copy()
    ratio = br[:, 8]
    tap = np.where(ratio == 0, 1.0, ratio)
    is_tr = (ratio != 0) | ((br[:, 2] == 0) & (br[:, 4] == 0))   # heuristic type tag (reporting only)
    nl = len(br)
    src = dict(source or {})
    src.update(sha256=hashlib.sha256(text.encode()).hexdigest(), notes=notes)
    g = Grid(
        name=name, base_mva=base, source=src,
        bus_id=ids, bus_type=btype, Pd=bus[:, 2].copy(), Qd=bus[:, 3].copy(),
        Gs=bus[:, 4].copy(), Bs=bus[:, 5].copy(), Vmin=bus[:, 12].copy(), Vmax=bus[:, 11].copy(),
        br_from=np.array([idx[int(v)] for v in br[:, 0]], dtype=int),
        br_to=np.array([idx[int(v)] for v in br[:, 1]], dtype=int),
        r=br[:, 2].copy(), x=br[:, 3].copy(), b=br[:, 4].copy(), tap=tap,
        shift=np.deg2rad(br[:, 9]), br_status=br[:, 10].astype(int),
        br_is_transformer=is_tr, rate_a_case=br[:, 5].copy(),
        rating_ac=np.full(nl, np.nan), rating_dc=np.full(nl, np.nan),
        gen_bus=gbus, gen_Pg=gen[:, 1].copy(), gen_Qg=gen[:, 2].copy(), gen_Pmax=gen[:, 8].copy(),
        gen_Pmin=gen[:, 9].copy(), gen_Qmax=gen[:, 3].copy(), gen_Qmin=gen[:, 4].copy(),
        gen_Vset=vset, gen_status=gstat, bus_base_kv=bus[:, 9].copy(),
    )
    g.validate()
    return g

def provenance(path: Path) -> dict:
    """Look the file up in data/MANIFEST.json by file name AND sha256; a modified/unknown file is reported as such."""
    try:
        man = json.loads((DATA_DIR / "MANIFEST.json").read_text())
    except FileNotFoundError:
        return {"status": "no_manifest"}
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for key, ent in man.items():
        if isinstance(ent, dict) and ent.get("file") == Path(path).name:
            if ent.get("sha256") == sha:
                return {k: ent.get(k) for k in ("status", "matpower_commit", "upstream_path", "note")}
            return {"status": "UNVERIFIED_file_differs_from_manifest"}
    return {"status": "UNVERIFIED_not_in_manifest"}

def load_matpower_file(path: str | Path, name: str | None = None) -> Grid:
    p = Path(path)
    return parse_matpower(p.read_text(), name or p.stem, {"origin": str(p), "provenance": provenance(p)})

def load_grid(name: str) -> Grid:
    key = name.lower()
    if key in _BUILTIN and (DATA_DIR / _BUILTIN[key]).exists():
        return load_matpower_file(DATA_DIR / _BUILTIN[key], key)
    p = DATA_DIR / f"{key}.m"
    if p.exists():
        return load_matpower_file(p, key)
    raise FileNotFoundError(
        f"No case file for '{name}' (expected {_BUILTIN.get(key, key + '.m')}). Known names: {sorted(_BUILTIN)}. "
        f"Install the official MATPOWER file with scripts/verify_case_files.py --install, or call load_matpower_file(path).")
