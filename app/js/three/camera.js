// Camera rig: Orbit, Recon (free flight), Follow (orbit locked to the selection), plus one-shot Focus / Overview / Event framing and an
// orthographic top-down Schematic view. Canonical state is (position p, look target t); modes only differ in how input changes p and t.
// Bounded: the camera stays inside a box around the network and above a minimum height. Keyboard input is ignored while typing.

const ease = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
export const SPEEDS = { slow: 0.25, normal: 0.6, fast: 1.4 };       // fraction of scene size per second in Recon

export class CameraRig {
  constructor(T, gs, el, { onChange } = {}) {
    this.T = T; this.gs = gs; this.el = el; this.onChange = onChange || (() => {});
    this.mode = "orbit"; this.schematic = false; this.speed = "normal"; this.reduced = false;
    this.p = new T.Vector3(30, 30, 30); this.t = new T.Vector3(); this.vel = new T.Vector3(); this.keys = new Set(); this.anim = null; this.followKey = null;
    this.orthoZoom = 1; this.drag = null; this._bind();
  }
  setScene(L) { this.L = L; this.size = L.size; this.overview(true); }

  // ---- poses ------------------------------------------------------------------------------------------------------------------------
  _apply() {
    const c = this.gs.camera, T = this.T;
    if (this.schematic) {
      const o = this.gs.ortho, a = this.gs.aspect || 1, half = (this.size * 0.62) / this.orthoZoom;
      o.left = -half * a; o.right = half * a; o.top = half; o.bottom = -half; o.position.set(this.t.x, 200, this.t.z); o.up.set(0, 0, -1); o.lookAt(this.t.x, 0, this.t.z); o.updateProjectionMatrix();
    } else { c.position.copy(this.p); c.lookAt(this.t); }
    this.gs.dirty = true; this.onChange(this.readout());
  }
  _bounds() {
    const B = this.size * 1.3; this.p.x = clamp(this.p.x, -B, B); this.p.z = clamp(this.p.z, -B, B); this.p.y = clamp(this.p.y, 0.8, this.size * 2.2);
    this.t.x = clamp(this.t.x, -B, B); this.t.z = clamp(this.t.z, -B, B); this.t.y = clamp(this.t.y, -1, this.size);
  }
  to(p, t, ms = 700) {
    if (this.reduced || ms <= 0) { this.p.set(...p); this.t.set(...t); this._bounds(); this._apply(); return; }
    this.anim = { p0: this.p.clone(), t0: this.t.clone(), p1: new this.T.Vector3(...p), t1: new this.T.Vector3(...t), s: performance.now(), ms };
  }
  frame(points, { ms = 700, keepDirection = true, minRadius = 4, pad = 1.35 } = {}) {
    if (!points.length) return; const T = this.T, box = new T.Box3(); points.forEach((p) => box.expandByPoint(new T.Vector3(...p)));
    const sph = box.getBoundingSphere(new T.Sphere()), r = Math.max(sph.radius, minRadius / 2) * pad, fov = (this.gs.persp.fov * Math.PI) / 180;
    const dist = Math.max(r / Math.sin(fov / 2), minRadius);
    let dir = keepDirection ? this.p.clone().sub(this.t).normalize() : new T.Vector3(0.55, 0.75, 0.9).normalize();
    if (dir.y < 0.35) { dir.y = 0.35; dir.normalize(); }
    const c = sph.center; if (this.schematic) { this.t.set(c.x, 0, c.z); this.orthoZoom = clamp((this.size * 0.62) / Math.max(r, 2), 0.6, 12); this._apply(); return; }
    if (this.mode === "recon") this.mode = "orbit";
    this.to([c.x + dir.x * dist, c.y + dir.y * dist, c.z + dir.z * dist], [c.x, c.y, c.z], ms);
  }
  overview(instant = false) {
    const b = this.L.bounds, pts = [[b.minX, 0, b.minZ], [b.maxX, 0, b.maxZ], [b.minX, b.maxY * 0.5, b.maxZ], [b.maxX, 0, b.minZ]];
    if (this.schematic) { this.t.set(0, 0, 0); this.orthoZoom = 1; this._apply(); return; }
    this.mode = this.mode === "recon" ? "orbit" : this.mode;
    const d = this.size * 1.05; this.to([d * 0.42, d * 0.78, d * 0.72], [0, 0, 0], instant ? 0 : 800);
    void pts;
  }
  setMode(m) {
    if (m === this.mode) return; this.mode = m; this.keys.clear(); this.vel.set(0, 0, 0);
    if (m === "recon") { const d = this.t.clone().sub(this.p).normalize(); this.t.copy(this.p).add(d.multiplyScalar(4)); }
    this._apply();
  }
  setSchematic(on) { this.schematic = on; this.gs.camera = on ? this.gs.ortho : this.gs.persp; if (on && this.mode === "recon") this.mode = "orbit"; this.orthoZoom = 1; this.t.set(0, 0, 0); this._apply(); }

  // ---- per-frame update --------------------------------------------------------------------------------------------------------------
  update(dt, followPos) {
    if (this.anim) { const a = this.anim, k = clamp((performance.now() - a.s) / a.ms, 0, 1), e = ease(k);
      this.p.lerpVectors(a.p0, a.p1, e); this.t.lerpVectors(a.t0, a.t1, e); if (k >= 1) this.anim = null; this._bounds(); this._apply(); return; }
    if (this.mode === "follow" && followPos && !this.schematic) { const tgt = new this.T.Vector3(...followPos), d = tgt.clone().sub(this.t);
      if (d.lengthSq() > 1e-6) { const s = Math.min(1, dt * 4); this.t.add(d.multiplyScalar(s)); this.p.add(d); this._bounds(); this._apply(); } }
    if (this.mode === "recon" && !this.schematic) {
      const fwd = this.t.clone().sub(this.p).setY(0).normalize(), right = new this.T.Vector3(-fwd.z, 0, fwd.x), want = new this.T.Vector3();
      if (this.keys.has("w")) want.add(fwd); if (this.keys.has("s")) want.sub(fwd); if (this.keys.has("d")) want.add(right); if (this.keys.has("a")) want.sub(right);
      if (this.keys.has("r")) want.y += 1; if (this.keys.has("f")) want.y -= 1;
      const v = SPEEDS[this.speed] * this.size * (this.keys.has("shift") ? 2.5 : 1); if (want.lengthSq()) want.normalize().multiplyScalar(v);
      this.vel.lerp(want, Math.min(1, dt * 6));                       // smooth acceleration / deceleration
      if (this.vel.lengthSq() > 1e-6) { const step = this.vel.clone().multiplyScalar(dt); this.p.add(step); this.t.add(step); this._bounds(); this._apply(); }
    }
  }

  // ---- input -----------------------------------------------------------------------------------------------------------------------
  _bind() {
    const el = this.el;
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); this.drag = { x: e.clientX, y: e.clientY, b: e.button, shift: e.shiftKey, moved: 0 }; this.anim = null; });
    el.addEventListener("pointermove", (e) => {
      if (!this.drag) return; const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y; this.drag.x = e.clientX; this.drag.y = e.clientY; this.drag.moved += Math.abs(dx) + Math.abs(dy);
      const pan = this.drag.b === 2 || this.drag.shift || (this.schematic && this.drag.b === 0);
      if (pan) this._pan(dx, dy); else if (this.mode === "recon") this._look(dx, dy); else this._orbit(dx, dy);
    });
    const end = (e) => { if (this.drag) { this.lastDragMoved = this.drag.moved; this.drag = null; } try { el.releasePointerCapture(e.pointerId); } catch { /* ignore */ } };
    el.addEventListener("pointerup", end); el.addEventListener("pointercancel", end);
    el.addEventListener("wheel", (e) => { e.preventDefault(); this.anim = null; this._zoom(e.deltaY); }, { passive: false });
    const typing = (e) => e.target.closest && e.target.closest("input, textarea, select, [contenteditable]");
    window.addEventListener("keydown", (e) => { if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return; const k = e.key.toLowerCase();
      if (this.mode === "recon" && ["w", "a", "s", "d", "r", "f"].includes(k)) { this.keys.add(k); e.preventDefault(); }
      if (k === "shift") this.keys.add("shift"); });
    window.addEventListener("keyup", (e) => { this.keys.delete(e.key.toLowerCase()); if (e.key === "Shift") this.keys.delete("shift"); });
    window.addEventListener("blur", () => this.keys.clear());
  }
  _orbit(dx, dy) {
    if (this.schematic) return; const off = this.p.clone().sub(this.t), sph = new this.T.Spherical().setFromVector3(off);
    sph.theta -= dx * 0.006; sph.phi = clamp(sph.phi - dy * 0.006, 0.12, 1.45); off.setFromSpherical(sph); this.p.copy(this.t).add(off); this._bounds(); this._apply();
  }
  _look(dx, dy) {
    const d = this.t.clone().sub(this.p), sph = new this.T.Spherical().setFromVector3(d); sph.theta -= dx * 0.004; sph.phi = clamp(sph.phi + dy * 0.004, 0.25, 2.9);
    d.setFromSpherical(sph); this.t.copy(this.p).add(d); this._apply();
  }
  _pan(dx, dy) {
    if (this.schematic) { const r = this.el.getBoundingClientRect(), k = ((this.size * 1.24) / this.orthoZoom) / r.height; this.t.x -= dx * k; this.t.z -= dy * k; this._bounds(); this._apply(); return; }
    const dist = this.p.distanceTo(this.t), k = dist * 0.0016, fwd = this.t.clone().sub(this.p).setY(0).normalize(), right = new this.T.Vector3(-fwd.z, 0, fwd.x);
    const mv = right.multiplyScalar(-dx * k).add(fwd.multiplyScalar(dy * k)); this.p.add(mv); this.t.add(mv); this._bounds(); this._apply();
  }
  _zoom(dy) {
    if (this.schematic) { this.orthoZoom = clamp(this.orthoZoom * Math.exp(-dy * 0.0012), 0.5, 14); this._apply(); return; }
    if (this.mode === "recon") { const d = this.t.clone().sub(this.p).normalize().multiplyScalar(-dy * 0.01 * this.size * 0.05); this.p.add(d); this.t.add(d); this._bounds(); this._apply(); return; }
    const off = this.p.clone().sub(this.t), r = clamp(off.length() * Math.exp(dy * 0.0011), 2.5, this.size * 2.2); off.setLength(r); this.p.copy(this.t).add(off); this._bounds(); this._apply();
  }
  readout() {
    const off = this.p.clone().sub(this.t), sph = new this.T.Spherical().setFromVector3(this.mode === "recon" ? this.t.clone().sub(this.p).negate() : off);
    const heading = ((((-sph.theta * 180) / Math.PI) % 360) + 360) % 360, pitch = 90 - (sph.phi * 180) / Math.PI;
    return { mode: this.mode, schematic: this.schematic, heading, pitch, distance: this.schematic ? null : off.length(), height: this.p.y, zoom: this.orthoZoom, speed: this.speed };
  }
  pose() { return { p: this.p.toArray(), t: this.t.toArray(), schematic: this.schematic, zoom: this.orthoZoom }; }
  restore(b) { if (!!b.schematic !== this.schematic) this.setSchematic(!!b.schematic); if (b.schematic) { this.t.set(...b.t); this.orthoZoom = b.zoom || 1; this._apply(); } else { if (this.mode === "recon") this.mode = "orbit"; this.to(b.p, b.t); } }
}
