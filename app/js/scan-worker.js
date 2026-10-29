// Background worker for the live exhaustive scan: runs the JS DC cascade on every pair of lines and streams severities back in batches.
import { DCCascade } from "./core/cascade.js";

self.onmessage = (e) => {
  const { model } = e.data; const eng = new DCCascade(model), L = model.n_branch, N = (L * (L - 1)) / 2;
  let done = 0, i = 0, j = 1, t0 = performance.now();
  const step = () => {
    const out = [], tEnd = performance.now() + 45;
    while (done < N && performance.now() < tEnd) {
      out.push(i, j, eng.run([i, j]).metrics.S); done++;
      if (++j >= L) { i++; j = i + 1; }
    }
    self.postMessage({ batch: out, done, N, ms: performance.now() - t0 });
    if (done < N) setTimeout(step, 0);
  };
  step();
};
