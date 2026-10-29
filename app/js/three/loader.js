// Loads three.js r160 (ES module). Local copy first (offline `make serve`), then the pinned CDN build (hosted page).
const LOCAL = new URL("../../vendor/three.module.min.js", import.meta.url).href;
const CDN = "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.min.js";
export async function loadThree() {
  let last = null;
  for (const u of [LOCAL, CDN]) { try { const T = await import(u); if (T && T.WebGLRenderer) return T; } catch (e) { last = e; } }
  throw last || new Error("three.js could not be loaded");
}
export function webglAvailable() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; }
}
