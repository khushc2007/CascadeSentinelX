// Rendered scene: instanced procedural equipment built once per grid; setView() updates per-instance colour/scale only. Picking is done in
// screen space against projected bus/generator/load centres and branch polylines (reliable at every zoom level, no hidden proxy meshes).
import { sceneLayout, pointAt, SEG } from "./layout.js";
import { utilRamp } from "../core/encoding.js";
import { branchVisual } from "./branchviz.js";
import { cityBlocks } from "./context.js";

export const PAL = {
  bg: 0x0e0f10, ground: 0x17181a, grid: 0x34373b, bus: 0xa9b2bc, busDead: 0x2a2b2e, gen: 0xb8955a, genDead: 0x3a342b, load: 0xa08e74, shed: 0xd0473a,
  xfmr: 0x7a828c, line: 0xb4bcc5, lineDead: 0x3a3d42, warn: 0xe0a33a, fail: 0xd0473a, trip: 0x8c4038, tripNow: 0xe07a68, unknown: 0x7d848b, sel: 0xf2efe8, hover: 0xc9c5bb,
  city: 0x1e2023, cityFocus: 0x18191c, cityNear: 0x151618, switchgear: 0x8d959e, insulator: 0x6e757d,
  islands: [0x5f7f8f, 0x8f7f5f, 0x6f8f6a, 0x8a6f86, 0x7f8a5a, 0x5a6f8a, 0x8a6a5a, 0x6a8a8a],
};

export class GridScene {
  constructor(T, canvas) {
    this.T = T; this.canvas = canvas;
    const r = (this.renderer = new T.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" }));
    r.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); r.outputColorSpace = T.SRGBColorSpace; r.toneMapping = T.ACESFilmicToneMapping; r.toneMappingExposure = 1.45;
    r.shadowMap.enabled = true; r.shadowMap.type = T.PCFSoftShadowMap; r.setClearColor(PAL.bg, 1);
    this.scene = new T.Scene(); this.scene.background = new T.Color(PAL.bg);
    this.persp = new T.PerspectiveCamera(42, 1, 0.1, 2000); this.ortho = new T.OrthographicCamera(-10, 10, 10, -10, -500, 500); this.camera = this.persp;
    const hemi = new T.HemisphereLight(0xd6d9dd, 0x1a1816, 1.6); this.scene.add(hemi);
    const key = (this.key = new T.DirectionalLight(0xfff1dc, 2.8)); key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -0.0004; key.shadow.normalBias = 0.02;
    this.scene.add(key); this.scene.add(key.target);
    const rim = new T.DirectionalLight(0x9fb3c8, 0.9); rim.position.set(-40, 25, -60); this.scene.add(rim);
    this.root = new T.Group(); this.scene.add(this.root);
    this.clock = performance.now(); this.flowOn = true; this.reduced = false; this.dirty = true; this.flowT = 0;
    this.fps = { frames: 0, t0: performance.now(), value: null };
  }

  dispose() {
    if (!this.root) return;
    this.root.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach((m) => m.dispose()); });
    this.scene.remove(this.root); this.root = new this.T.Group(); this.scene.add(this.root);
  }

  build(model, { schematic = false } = {}) {
    const T = this.T; this.dispose(); this.model = model; this.schematic = schematic; const L = (this.L = sceneLayout(model, { schematic }));
    const std = (c, o = {}) => new T.MeshStandardMaterial({ color: c, roughness: 0.75, metalness: 0.15, ...o });
    const add = (o) => { this.root.add(o); return o; };
    // ground + scene-relative reference grid (major lines only)
    const gsz = L.size * 2.4;
    this.ground = add(new T.Mesh(new T.PlaneGeometry(gsz, gsz), new T.MeshStandardMaterial({ color: PAL.ground, roughness: 1, metalness: 0 })));
    this.ground.rotation.x = -Math.PI / 2; this.ground.position.y = -0.02; this.ground.receiveShadow = true;
    this.grid = add(new T.GridHelper(gsz, Math.round(gsz / 5), PAL.grid, PAL.grid)); this.grid.position.y = -0.01;
    [].concat(this.grid.material).forEach((m) => { m.transparent = true; m.opacity = 0.35; m.depthWrite = false; });
    this.scene.fog = schematic ? null : new T.FogExp2(PAL.bg, 1.15 / (L.size * 2.2));
    // key light frames the network
    const s = L.size * 0.75; Object.assign(this.key.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 1, far: L.size * 4 }); this.key.shadow.camera.updateProjectionMatrix();
    this.key.position.set(L.size * 0.45, L.size * 0.9, L.size * 0.3); this.key.target.position.set(0, 0, 0);
    this.renderer.shadowMap.enabled = !schematic;

    const m4 = new T.Matrix4(), q = new T.Quaternion(), v = new T.Vector3(), sc = new T.Vector3(), up = new T.Vector3(0, 1, 0);
    const inst = (geo, mat, n, shadow = true) => { const im = add(new T.InstancedMesh(geo, mat, Math.max(n, 1))); im.count = n; im.castShadow = shadow; im.receiveShadow = true;
      im.instanceMatrix.setUsage(T.DynamicDrawUsage); im.instanceColor = new T.InstancedBufferAttribute(new Float32Array(Math.max(n, 1) * 3), 3); im.frustumCulled = false; return im; };
    this.setM = (im, i, pos, quat, scale) => { m4.compose(v.set(...pos), quat || q.identity(), sc.set(...scale)); im.setMatrixAt(i, m4); };

    // buses: faceted hexagonal prisms
    this.busMesh = inst(new T.CylinderGeometry(1, 1, 1, 6), std(0xffffff, { roughness: 0.55, metalness: 0.35, flatShading: true }), model.nBus);
    L.bus.forEach((b, i) => this.setM(this.busMesh, i, [b.x, b.y + b.h / 2, b.z], null, [b.r, b.h, b.r]));
    // plinth: a darker, wider hexagonal base that grounds each bus (and its voltage tier) visually
    this.plinth = inst(new T.CylinderGeometry(1, 1.08, 1, 6), std(0x2a2d31, { roughness: 0.9, metalness: 0.1, flatShading: true }), model.nBus);
    L.bus.forEach((b, i) => this.setM(this.plinth, i, [b.x, b.y - 0.01, b.z], null, [b.r * 1.35, 0.06, b.r * 1.35]));
    // masts for buses raised to a higher voltage tier (elevation encodes voltage class; the mast shows where the bus stands on the ground plane)
    const raised = L.bus.map((b, i) => [b, i]).filter(([b]) => b.y > 0.01);
    this.mast = inst(new T.CylinderGeometry(1, 1, 1, 8), std(0x4a4e55, { roughness: 0.7, metalness: 0.4 }), raised.length);
    raised.forEach(([b], j) => this.setM(this.mast, j, [b.x, b.y / 2, b.z], null, [0.07, b.y, 0.07]));
    this.mast.instanceMatrix.needsUpdate = true;
    // generator housings + caps + stub to the bus
    const nG = model.gens.length;
    // generator housing: lathe-turned profile (wide foot, slight waist, rolled rim) for a distinct silhouette; unit height, unit radius
    const prof = [[0, 0], [1.08, 0], [1.08, 0.06], [0.98, 0.1], [0.9, 0.45], [0.88, 0.7], [0.94, 0.92], [1.0, 0.97], [0.96, 1.0], [0, 1.0]].map(([x, y]) => new T.Vector2(x, y));
    const genGeo = new T.LatheGeometry(prof, 28); genGeo.translate(0, -0.5, 0);
    this.genBody = inst(genGeo, std(0xffffff, { roughness: 0.58, metalness: 0.3 }), nG);
    this.genCap = inst(new T.CylinderGeometry(0.72, 1, 0.22, 24), std(0xffffff, { roughness: 0.45, metalness: 0.45 }), nG);
    this.genStub = inst(new T.BoxGeometry(1, 1, 1), std(0x55595f, { roughness: 0.8 }), nG, false);
    L.gen.forEach((g, i) => {
      const b = L.bus[model.gens[i].bus]; this.setM(this.genBody, i, [g.x, g.y + g.h / 2, g.z], null, [g.s, g.h, g.s]);
      this.setM(this.genCap, i, [g.x, g.y + g.h + 0.11 * g.s, g.z], null, [g.s, g.s, g.s]);
      const dx = g.x - b.x, dz = g.z - b.z, len = Math.hypot(dx, dz); q.setFromUnitVectors(new T.Vector3(1, 0, 0), new T.Vector3(dx / len, 0, dz / len));
      this.setM(this.genStub, i, [(g.x + b.x) / 2, g.y + 0.06, (g.z + b.z) / 2], q, [len, 0.06, 0.08]);
    });
    // loads: served column (solid) + shed column (translucent red) on top
    const nL = model.loads.length;
    this.loadServed = inst(new T.BoxGeometry(1, 1, 1), std(0xffffff, { roughness: 0.9, metalness: 0.05 }), nL);
    this.loadShed = inst(new T.BoxGeometry(1, 1, 1), new T.MeshStandardMaterial({ color: PAL.shed, roughness: 0.6, transparent: true, opacity: 0.38, depthWrite: false }), nL, false);
    // transformer blocks at mid-span
    this.xIdx = model.branches.filter((b) => b.transformer).map((b) => b.l);
    this.xfmr = inst(new T.BoxGeometry(1, 1, 1), std(0xffffff, { roughness: 0.5, metalness: 0.5 }), this.xIdx.length);
    // conductors: SEG instanced cylinder segments per branch; ghost dashes for removed branches; cut markers for initial outages
    const nB = model.nBranch, segGeo = new T.CylinderGeometry(1, 1, 1, 6, 1, true); segGeo.translate(0, 0.5, 0);
    this.cond = inst(segGeo, std(0xffffff, { roughness: 0.4, metalness: 0.55, side: T.DoubleSide }), nB * SEG, false);
    this.ghost = inst(segGeo.clone(), new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 }), nB * SEG, false);
    this.cuts = inst(new T.BoxGeometry(1, 1, 1), new T.MeshBasicMaterial({ color: PAL.fail }), nB * 2, false);
    this.segQ = []; this.segInfo = [];
    L.branch.forEach((rt, l) => { for (let i = 0; i < SEG; i++) { const a = rt.pts[i], b = rt.pts[i + 1], d = new T.Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
      const len = d.length(); this.segQ[l * SEG + i] = new T.Quaternion().setFromUnitVectors(up, d.normalize()); this.segInfo[l * SEG + i] = { a, len }; } });
    // flow chevrons
    this.flowN = L.branch.map((rt) => Math.max(1, Math.min(6, Math.round(rt.span / 2.6))));
    this.flowBase = []; let acc = 0; this.flowN.forEach((n) => { this.flowBase.push(acc); acc += n; });
    const cone = new T.ConeGeometry(1, 1, 3); cone.rotateX(Math.PI / 2);
    this.flow = inst(cone, new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9 }), acc, false);
    this.flowPhase = new Float32Array(nB).map(() => Math.random());
    // island discs under buses
    this.disc = inst(new T.CylinderGeometry(1, 1, 0.02, 32), new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.32, depthWrite: false }), model.nBus, false);
    // trip markers (× at mid-span) for branches removed at the displayed step
    this.marks = inst(new T.BoxGeometry(1, 1, 1), new T.MeshBasicMaterial({ color: 0xffffff }), nB * 2, false);
    // switchyard detail, shown only at close range (level of detail): a busbar across each bus pad and two post insulators
    this.busbar = inst(new T.BoxGeometry(1, 1, 1), std(PAL.switchgear, { roughness: 0.5, metalness: 0.6 }), model.nBus, false);
    this.posts = inst(new T.CylinderGeometry(0.5, 0.65, 1, 8), std(PAL.insulator, { roughness: 0.6, metalness: 0.2 }), model.nBus * 2, false);
    L.bus.forEach((b, i) => { const len = b.r * 1.5, hh = schematic ? 0.02 : 0.18;
      this.setM(this.busbar, i, [b.x, b.top + hh + 0.03, b.z], null, [len, 0.035, 0.05]);
      [-1, 1].forEach((sgn, j) => this.setM(this.posts, 2 * i + j, [b.x + sgn * len * 0.38, b.top + hh / 2, b.z], null, [0.07, hh, 0.07])); });
    [this.busbar, this.posts].forEach((im) => { im.instanceMatrix.needsUpdate = true; im.visible = false; });
    // contextual city (decoration, not data): one instanced mesh of low dark blocks kept clear of all equipment and branch routes
    this.cityList = schematic ? [] : cityBlocks(L);
    const boxGeo = new T.BoxGeometry(1, 1, 1); boxGeo.translate(0, 0.5, 0);
    this.city = inst(boxGeo, new T.MeshLambertMaterial({ color: 0xffffff }), this.cityList.length, false);
    this.city.castShadow = false; this.city.userData.decorative = true;
    this.cityList.forEach((c, i) => this.setM(this.city, i, [c.x, 0, c.z], null, [c.w, c.h, c.d]));
    this.lod = null; this.setContext(this.contextMode || "spatial");
    // selection / hover helpers
    this.selGroup = add(new T.Group()); this.hovGroup = add(new T.Group());
    this.view = null; this.layers = null; this.dirty = true;
    return L;
  }

  // ---- context (decorative city) and level of detail ----------------------------------------------------------------------------------
  setContext(mode) {
    this.contextMode = mode; if (!this.city) return; const col = new this.T.Color(mode === "focus" ? PAL.cityFocus : PAL.city), k = mode === "focus" ? 0.45 : 1;
    this.city.visible = mode !== "grid" && this.cityList.length > 0;
    if (this.lod === "near") col.setHex(PAL.cityNear);
    this.cityList.forEach((c, i) => { this.setM(this.city, i, [c.x, 0, c.z], null, [c.w, c.h * k, c.d]); this.city.setColorAt(i, col); });
    this.city.instanceMatrix.needsUpdate = true; if (this.city.instanceColor) this.city.instanceColor.needsUpdate = true;
    const g = this.grid; if (g) { g.visible = mode !== "grid" && (this.layers ? this.layers.reference !== false : true); [].concat(g.material).forEach((m) => (m.opacity = mode === "focus" ? 0.18 : 0.35)); }
    this.dirty = true;
  }
  // level of detail from the camera distance: "far" (topology), "mid", "near" (switchyard detail visible)
  setLOD(distance) {
    if (!this.L) return; const s = this.L.size, lvl = this.schematic ? "far" : distance < s * 0.28 ? "near" : distance < s * 0.7 ? "mid" : "far";
    if (lvl === this.lod) return; this.lod = lvl; const near = lvl === "near" && (!this.layers || this.layers.equipment !== false);
    this.busbar.visible = near; this.posts.visible = near;
    // the decorative city recedes as the camera closes in on equipment (it must never compete with what is being inspected)
    if (this.city && this.cityList.length) { const col = new this.T.Color(lvl === "near" ? PAL.cityNear : this.contextMode === "focus" ? PAL.cityFocus : PAL.city);
      for (let i = 0; i < this.cityList.length; i++) this.city.setColorAt(i, col); if (this.city.instanceColor) this.city.instanceColor.needsUpdate = true; }
    this.dirty = true;
  }

  // ---- state → instances --------------------------------------------------------------------------------------------------------
  setView(view, layers) {
    const T = this.T, L = this.L, model = this.model; this.view = view; this.layers = layers; const col = new T.Color();
    const setC = (im, i, hex) => { col.setHex(hex); im.setColorAt(i, col); };
    const setRGB = (im, i, rgb) => { col.setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, T.SRGBColorSpace); im.setColorAt(i, col); };
    const vis = (k) => layers[k] !== false;
    const iso = layers.isolate, nb = layers.neighbourhood ? new Set(layers.neighbourhood) : null;   // isolate a component, or a selection's neighbourhood
    const out = (i) => (iso != null && view.buses[i].component !== iso) || (nb != null && !nb.has(i)); this._out = iso != null || nb != null ? out : null;
    // buses
    model.buses.forEach((b, i) => { const st = view.buses[i], p = L.bus[i]; setC(this.busMesh, i, out(i) ? 0x232427 : st.energized ? PAL.bus : PAL.busDead);
      this.setM(this.busMesh, i, [p.x, p.y + p.h / 2, p.z], null, vis("equipment") ? [p.r, p.h, p.r] : [p.r * 0.5, p.h, p.r * 0.5]);
      setC(this.plinth, i, out(i) ? 0x1a1b1d : 0x2a2d31);
      const isl = vis("islands") && view.frame && st.energized && !st.mainIsland && st.component != null;
      setC(this.disc, i, isl ? PAL.islands[st.component % PAL.islands.length] : 0); this.setM(this.disc, i, [p.x, p.y + 0.01, p.z], null, isl ? [p.r * 2.6, 1, p.r * 2.6] : [0, 0, 0]); });
    // generators
    model.gens.forEach((g, i) => { const on = view.gens[i].energized, s = vis("equipment") ? 1 : 0, gp = L.gen[i], dim = out(g.bus);
      setC(this.genBody, i, dim ? 0x26241f : on ? PAL.gen : PAL.genDead); setC(this.genCap, i, dim ? 0x26241f : on ? 0xcdb27f : 0x2f2a24); setC(this.genStub, i, dim ? 0x232427 : 0x55595f);
      if (!s) { [this.genBody, this.genCap, this.genStub].forEach((im) => this.setM(im, i, [0, -50, 0], null, [0, 0, 0])); }
      else { this.setM(this.genBody, i, [gp.x, gp.y + gp.h / 2, gp.z], null, [gp.s, gp.h, gp.s]); this.setM(this.genCap, i, [gp.x, gp.y + gp.h + 0.11 * gp.s, gp.z], null, [gp.s, gp.s, gp.s]); } });
    // loads: served vs shed (served fraction from the engine; when unavailable the full column is drawn and the inspector says so)
    model.loads.forEach((ld, i) => { const p = L.load[i], st = view.buses[ld.bus], f = st.served_fraction == null ? 1 : st.served_fraction, show = vis("loads");
      const hs = p.H * f, hd = p.H * (1 - f);
      setC(this.loadServed, i, out(ld.bus) ? 0x24221f : st.energized ? PAL.load : 0x3b352d);
      this.setM(this.loadServed, i, [p.x, p.y + hs / 2, p.z], null, show && hs > 1e-4 ? [p.w, hs, p.w] : [0, 0, 0]);
      setC(this.loadShed, i, PAL.shed); this.setM(this.loadShed, i, [p.x, p.y + hs + hd / 2, p.z], null, show && hd > 1e-4 ? [p.w * 1.04, hd, p.w * 1.04] : [0, 0, 0]); });
    // transformers
    this.xIdx.forEach((l, j) => { const m = L.branch[l].mid, st = view.branches[l].state, gone = st === "initial_outage" || st === "tripped";
      setC(this.xfmr, j, gone || out(model.branches[l].from) ? 0x2a2c2f : PAL.xfmr); this.setM(this.xfmr, j, [m[0], m[1], m[2]], null, vis("equipment") ? [0.42, 0.34, 0.42] : [0, 0, 0]); });
    // conductors (encoding: branchviz.js — every state also has a width, dash or marker cue)
    const rad = this.schematic ? 0.06 : 0.07; let gi = 0, ci = 0, mi = 0; const fi = view.frame ? view.frameIndex : null; this.kinds = new Map();
    const q45 = [new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 1, 0), Math.PI / 4), new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 1, 0), -Math.PI / 4)];
    model.branches.forEach((br, l) => {
      const st = view.branches[l], bv = branchVisual(st, fi), gone = bv.width === 0; this.kinds.set(l, bv.kind);
      let c = PAL[bv.color];
      if ((iso != null || nb != null) && (out(br.from) || out(br.to))) c = 0x26282b;
      else if (bv.kind === "normal" && vis("utilization") && st.u != null) c = null;
      const w = rad * (bv.width || 1);
      for (let i = 0; i < SEG; i++) { const k = l * SEG + i, si = this.segInfo[k];
        if (c == null) setRGB(this.cond, k, utilRamp(st.u)); else setC(this.cond, k, c);
        this.setM(this.cond, k, si.a, this.segQ[k], gone ? [0, 0, 0] : [w, si.len, w]);
        if (gone && i % 2 === 0 && vis("outages")) { setC(this.ghost, gi, c ?? PAL.trip); const r2 = rad * bv.dash * (bv.kind === "initial_outage" ? 1 : 0.9);
          this.setM(this.ghost, gi++, si.a, this.segQ[k], [r2, si.len * (bv.kind === "tripped_earlier" || bv.kind === "unavailable" ? 0.6 : 1), r2]); } }
      if (bv.cut && vis("outages")) [0.1, 0.9].forEach((t) => { const p = pointAt(L.branch[l], t); this.setM(this.cuts, ci, p, null, [0.22, 0.22, 0.22]); setC(this.cuts, ci++, PAL.fail); });
      if (bv.mark && vis("outages")) { const p = pointAt(L.branch[l], 0.5), ms = Math.max(0.5, L.size * 0.011); q45.forEach((qq) => { this.setM(this.marks, mi, [p[0], p[1] + 0.12, p[2]], qq, [ms, 0.07, ms * 0.16]); setC(this.marks, mi++, PAL.tripNow); }); }
    });
    this.marks.count = mi;
    this.ghost.count = gi; this.cuts.count = ci;
    [this.busMesh, this.plinth, this.disc, this.genBody, this.genCap, this.genStub, this.loadServed, this.loadShed, this.xfmr, this.cond, this.ghost, this.cuts, this.marks].forEach((im) => {
      im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; });
    this.flowOn = vis("flow"); this.grid.visible = vis("reference") && this.contextMode !== "grid"; if (this.city) this.city.visible = this.contextMode !== "grid" && vis("context") && this.cityList.length > 0;
    if (this.lod === "near") { this.busbar.visible = this.posts.visible = vis("equipment"); }
    this._flow(0); this.dirty = true;
  }

  _flow(dt) {                                                       // direction = sign of the DC flow; speed ∝ utilisation
    const v = this.view, L = this.L, col = new this.T.Color(); if (!v || !this.flow) return;
    this.model.branches.forEach((br, l) => {
      const st = v.branches[l], n = this.flowN[l], base = this.flowBase[l];
      const live = this.flowOn && st.flow_mw != null && Math.abs(st.flow_mw) > 0.5 && !["initial_outage", "tripped", "deenergized"].includes(st.state) && !(this._out && (this._out(br.from) || this._out(br.to)));
      const dir = st.flow_mw >= 0 ? 1 : -1, speed = this.reduced ? 0 : (0.05 + 0.35 * Math.min(st.u ?? 0, 1.3)) * (6 / Math.max(L.branch[l].span, 1));
      this.flowPhase[l] = (this.flowPhase[l] + dir * speed * dt + 1) % 1;
      for (let i = 0; i < n; i++) {
        const k = base + i; if (!live) { this.setM(this.flow, k, [0, -50, 0], null, [0, 0, 0]); continue; }
        const t = (this.flowPhase[l] + i / n) % 1, a = pointAt(L.branch[l], t), b = pointAt(L.branch[l], Math.min(Math.max(t + dir * 0.01, 0), 1));
        const q = new this.T.Quaternion(); const d = new this.T.Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]).normalize(); if (d.lengthSq() > 0) q.setFromUnitVectors(new this.T.Vector3(0, 0, 1), d);
        this.setM(this.flow, k, a, q, [0.085, 0.085, 0.2]);
        col.setHex(st.state === "overload" ? 0xffd3c9 : st.state === "warning" ? 0xffe2b0 : 0xe6ebef); this.flow.setColorAt(k, col);
      }
    });
    this.flow.instanceMatrix.needsUpdate = true; if (this.flow.instanceColor) this.flow.instanceColor.needsUpdate = true;
  }

  // ---- selection / hover helpers -----------------------------------------------------------------------------------------------------
  highlight(group, key, color) {
    const T = this.T, g = group === "sel" ? this.selGroup : this.hovGroup;
    g.children.slice().forEach((c) => { g.remove(c); c.geometry.dispose(); c.material.dispose(); });
    if (!key || !this.model) { this.dirty = true; return; }
    const [kind, vs] = key.split(":"), id = Number(vs), mat = new T.MeshBasicMaterial({ color, transparent: true, opacity: group === "sel" ? 0.95 : 0.7, depthTest: false });
    const add = (geo, pos) => { const m = new T.Mesh(geo, mat); if (pos) m.position.set(...pos); m.renderOrder = 10; g.add(m); return m; };
    if (kind === "branch") { const rt = this.L.branch[id], curve = new T.CatmullRomCurve3(rt.pts.map((p) => new T.Vector3(...p)));
      add(new T.TubeGeometry(curve, 48, group === "sel" ? 0.13 : 0.1, 8, false)); }
    else if (kind === "bus") { const b = this.L.bus[this.model.busById.get(id).i], ring = add(new T.TorusGeometry(b.r * 1.55, 0.06, 8, 48), [b.x, b.top + 0.05, b.z]); ring.rotation.x = Math.PI / 2; }
    else if (kind === "gen") { const p = this.L.gen[id], ring = add(new T.TorusGeometry(p.s * 1.5, 0.05, 8, 40), [p.x, p.y + p.h + 0.2, p.z]); ring.rotation.x = Math.PI / 2; }
    else if (kind === "load") { const i = this.model.loads.findIndex((l) => l.busId === id), p = this.L.load[i]; const ring = add(new T.TorusGeometry(0.45, 0.05, 8, 32), [p.x, p.y + p.H + 0.15, p.z]); ring.rotation.x = Math.PI / 2; }
    this.dirty = true;
  }

  // ---- geometry queries ---------------------------------------------------------------------------------------------------------------
  entityPos(key) {
    const [kind, vs] = key.split(":"), id = Number(vs), L = this.L;
    if (kind === "branch") return L.branch[id].mid;
    if (kind === "bus") { const b = L.bus[this.model.busById.get(id).i]; return [b.x, b.top, b.z]; }
    if (kind === "gen") { const p = L.gen[id]; return [p.x, p.y + p.h, p.z]; }
    if (kind === "load") { const i = this.model.loads.findIndex((l) => l.busId === id), p = L.load[i]; return [p.x, p.y + p.H, p.z]; }
    return [0, 0, 0];
  }
  entityPoints(key) { const [kind, vs] = key.split(":"); return kind === "branch" ? this.L.branch[Number(vs)].pts : [this.entityPos(key)]; }
  project(p) { const v = new this.T.Vector3(...p).project(this.camera); const r = this.canvas.getBoundingClientRect(); return [(v.x + 1) / 2 * r.width, (1 - v.y) / 2 * r.height, v.z]; }

  pick(x, y, tol = 9) {
    if (!this.model) return null; const L = this.L, m = this.model; let best = null, bd = Infinity;
    const consider = (key, d, pri) => { const s = d - pri; if (d < tol + pri && s < bd) { bd = s; best = key; } };
    m.buses.forEach((b, i) => { const p = this.project([L.bus[i].x, L.bus[i].top, L.bus[i].z]); if (p[2] < 1) consider(b.key, Math.hypot(p[0] - x, p[1] - y), 6); });
    if (this.layers?.equipment !== false) m.gens.forEach((g, i) => { const p = this.project([L.gen[i].x, L.gen[i].y + L.gen[i].h, L.gen[i].z]); if (p[2] < 1) consider(g.key, Math.hypot(p[0] - x, p[1] - y), 4); });
    if (this.layers?.loads !== false) m.loads.forEach((ld, i) => { const p = this.project([L.load[i].x, L.load[i].y + L.load[i].H, L.load[i].z]); if (p[2] < 1) consider(ld.key, Math.hypot(p[0] - x, p[1] - y), 3); });
    m.branches.forEach((br, l) => {
      const pts = L.branch[l].pts.map((p) => this.project(p)); let d = Infinity;
      for (let i = 0; i < SEG; i++) { const a = pts[i], b = pts[i + 1]; if (a[2] > 1 || b[2] > 1) continue; const vx = b[0] - a[0], vy = b[1] - a[1], ll = vx * vx + vy * vy || 1;
        const t = Math.max(0, Math.min(1, ((x - a[0]) * vx + (y - a[1]) * vy) / ll)); d = Math.min(d, Math.hypot(x - a[0] - vx * t, y - a[1] - vy * t)); }
      consider(br.key, d, 0);
    });
    return best;
  }

  resize() {
    const r = this.canvas.getBoundingClientRect(), w = Math.max(1, r.width), h = Math.max(1, r.height);
    this.renderer.setSize(w, h, false); this.persp.aspect = w / h; this.persp.updateProjectionMatrix(); this.aspect = w / h; this.dirty = true;
  }
  // Adaptive quality: when frames are slow (software rendering, weak GPU), step down pixel ratio, then shadows, then the flow update rate.
  _adapt(ms) {
    this.q = this.q || { level: 0, ema: 16, since: performance.now(), flowSkip: 0 };
    const q = this.q; q.ema = q.ema * 0.9 + ms * 0.1;
    if (q.ema > 45 && q.level < 3 && performance.now() - q.since > 1500) {
      q.level++; q.since = performance.now();
      if (q.level === 1) { this.renderer.setPixelRatio(1); this.resize(); }
      if (q.level === 2) { this.renderer.shadowMap.enabled = false; this.scene.traverse((o) => { if (o.material) [].concat(o.material).forEach((m) => (m.needsUpdate = true)); }); }
    }
  }
  qualityLabel() { const l = this.q ? this.q.level : 0; return ["full", "pixel ratio 1", "pixel ratio 1, no shadows", "pixel ratio 1, no shadows, flow at 15 fps"][l]; }
  render(dt) {
    const animate = this.flowOn && !this.reduced && this.view;
    if (animate) { const q = this.q; if (!q || q.level < 3 || (q.flowSkip = (q.flowSkip + 1) % 4) === 0) { this._flow(q && q.level >= 3 ? dt * 4 : dt); this.dirty = true; } }
    if (!this.dirty) return false;
    const t0 = performance.now(); this.renderer.render(this.scene, this.camera); this.dirty = false;
    // measure the interval between consecutive drawn frames while animating (includes asynchronous GPU work), not just the submit time
    if (animate && this._lastDraw) this._adapt(Math.min(t0 - this._lastDraw, 500)); this._lastDraw = animate ? t0 : 0;
    const now = performance.now(); this.fps.frames++; if (now - this.fps.t0 > 1000) { this.fps.value = (1000 * this.fps.frames) / (now - this.fps.t0); this.fps.frames = 0; this.fps.t0 = now; }
    return true;
  }
  info() { const i = this.renderer.info; return { calls: i.render.calls, triangles: i.render.triangles, geometries: i.memory.geometries, textures: i.memory.textures, fps: this.fps.value, frameMs: this.q ? this.q.ema : null, frameMsMeaning: "average interval between animated frames", quality: this.qualityLabel() }; }
}
