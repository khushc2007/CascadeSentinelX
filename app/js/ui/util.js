// Shared helpers for the web demonstration: data loading, number formatting, tooltip, toast, reveal-on-scroll and small DOM utilities.
export const $ = (id) => document.getElementById(id);
export const RM = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
export const NS = "http://www.w3.org/2000/svg";
export const GRIDNAME = { ieee14: "IEEE-14", ieee30: "IEEE-30", ieee118: "IEEE-118" };

const cache = new Map();
export function load(name) {
  if (!cache.has(name)) cache.set(name, fetch(`data/${name}`).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  return cache.get(name);
}

export const fmtInt = (n) => Math.round(Number(n)).toLocaleString("en-US");
export const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? "–" : `${(100 * x).toFixed(d)}%`);
export function sup(e) { const m = { "-": "⁻", 0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹" }; return String(e).split("").map((c) => m[c] ?? c).join(""); }
export function sci(x, p = 2) {
  if (x === Infinity || x === "inf") return "∞"; if (x == null || Number.isNaN(x)) return "–";
  if (x === 0) return "0"; const e = Math.floor(Math.log10(Math.abs(x)));
  if (e >= -2 && e < 6) return Number(x.toPrecision(p + 1)).toLocaleString("en-US");
  return `${(x / 10 ** e).toFixed(p - 1)}×10${sup(e)}`;
}
export function dur(s) {
  if (!Number.isFinite(s)) return "∞";
  const AGE = 4.35e17;
  if (s >= AGE * 10) return `${sci(s / AGE, 2)} × age of the universe`;
  const u = [[3.156e7, "years"], [86400, "days"], [3600, "hours"], [60, "min"], [1, "s"], [1e-3, "ms"], [1e-6, "µs"], [1e-9, "ns"]];
  for (const [v, n] of u) if (s >= v) { const q = s / v; return `${q >= 1e5 ? sci(q, 2) : Number(q.toPrecision(3)).toLocaleString("en-US")} ${n}`; }
  return `${(s * 1e12).toPrecision(3)} ps`;
}
export const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
export const ease = (t) => 1 - Math.pow(1 - t, 3);
export const lineLabel = (g, l) => `${g.buses[g.branches[l].from].id}–${g.buses[g.branches[l].to].id}`;

export function svg(tag, attrs = {}, parent = null, text = null) {
  const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text; if (parent) parent.appendChild(e); return e;
}

// ---- tooltip ----
const tip = () => $("tip");
export function showTip(html, x, y) {
  const t = tip(); t.innerHTML = html; t.hidden = false;
  const w = t.offsetWidth, h = t.offsetHeight, W = innerWidth, H = innerHeight;
  t.style.left = `${clamp(x + 14, 8, W - w - 8)}px`; t.style.top = `${clamp(y + 14 + h > H ? y - h - 12 : y + 14, 8, H - h - 8)}px`;
}
export const hideTip = () => { tip().hidden = true; };

let toastT = null;
export function toast(msg, ms = 2600) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), ms); }

// ---- visibility helpers ----
export function onVisible(el, cb, threshold = 0.15) {
  if (!("IntersectionObserver" in window)) { cb(true); return; }
  new IntersectionObserver((es) => es.forEach((e) => cb(e.isIntersecting)), { threshold }).observe(el);
}
export function once(el, cb, threshold = 0.3) {
  let done = false; onVisible(el, (v) => { if (v && !done) { done = true; cb(); } }, threshold);
}
export function initReveal() {
  const els = document.querySelectorAll(".reveal");
  if (RM || !("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("in")); return; }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.08, rootMargin: "0px 0px -6% 0px" });
  els.forEach((e) => io.observe(e));
}
export function initSpotlight() {
  document.addEventListener("pointermove", (e) => {
    const p = e.target.closest && e.target.closest(".panel"); if (!p) return; const r = p.getBoundingClientRect();
    p.style.setProperty("--mx", `${e.clientX - r.left}px`); p.style.setProperty("--my", `${e.clientY - r.top}px`);
  }, { passive: true });
}
export function rangeFill(input) { const f = () => input.style.setProperty("--p", `${(100 * (input.value - input.min)) / (input.max - input.min)}%`); input.addEventListener("input", f); f(); return f; }

export function countUp(el, to, fmt, ms = 1600) {
  const f = { int: (v) => fmtInt(v), pct1: (v) => `${v.toFixed(1)}<small>%</small>`, x: (v) => `${fmtInt(v)}<small>×</small>` }[fmt] || ((v) => String(v));
  if (RM) { el.innerHTML = f(to); return; }
  const t0 = performance.now(); const step = (t) => { const k = clamp((t - t0) / ms, 0, 1); el.innerHTML = f(to * ease(k)); if (k < 1) requestAnimationFrame(step); }; requestAnimationFrame(step);
}

// ---- canvas sizing ----
export function fitCanvas(c) {
  const r = c.getBoundingClientRect(), d = Math.min(devicePixelRatio || 1, 2), w = Math.max(1, Math.round(r.width * d)), h = Math.max(1, Math.round(r.height * d));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  return { w: r.width, h: r.height, d };
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
