// Branch state → visual encoding (pure; tested in app/test/scene.test.mjs). The state comes from the shared view state
// (core/encoding.js: initial_outage, tripped, unavailable, deenergized, overload, warning, normal); this module only adds the round
// distinction the engine data supports — a branch whose trip round equals the displayed frame index was removed at this step
// ("tripped now"); earlier trips are "tripped earlier". Every state has a non-colour cue (width, dash pattern, marker).
//
//   kind              colour token   conductor          ghost dashes            marker
//   normal            line / ramp    1.0 ×               –                       –
//   unknown           unknown        1.0 ×, no ramp      –                       –          (in service, loading not recorded for this result)
//   warning           warn           1.5 ×               –                       –          (80–100 % of rating)
//   overload          fail           2.2 ×               –                       –          (> 100 %: trips in this round under the trip rule)
//   deenergized       lineDead       0.8 ×               –                       –
//   unavailable       lineDead       hidden              faint, fine             –          (out of service in the base case)
//   initial_outage    fail           hidden              bold dashes             cut markers at 10 % and 90 % + T0 label
//   tripped_now       trip (bright)  hidden              medium dashes           × marker at mid-span + R n label
//   tripped_earlier   trip (dim)     hidden              fine dashes             –
export const KINDS = ["normal", "unknown", "warning", "overload", "deenergized", "unavailable", "initial_outage", "tripped_now", "tripped_earlier"];

export function branchVisual(st, frameIndex) {
  const s = st.state;
  if (s === "initial_outage") return { kind: "initial_outage", color: "fail", width: 0, dash: 1.1, cut: true, mark: false };
  if (s === "tripped") {
    const now = st.tripRound != null && frameIndex != null && st.tripRound === frameIndex;
    return now ? { kind: "tripped_now", color: "tripNow", width: 0, dash: 0.8, cut: false, mark: true } : { kind: "tripped_earlier", color: "trip", width: 0, dash: 0.45, cut: false, mark: false };
  }
  if (s === "unavailable") return { kind: "unavailable", color: "lineDead", width: 0, dash: 0.35, cut: false, mark: false };
  if (s === "deenergized") return { kind: "deenergized", color: "lineDead", width: 0.8, dash: 0, cut: false, mark: false };
  if (s === "overload") return { kind: "overload", color: "fail", width: 2.2, dash: 0, cut: false, mark: false };
  if (s === "warning") return { kind: "warning", color: "warn", width: 1.5, dash: 0, cut: false, mark: false };
  if (frameIndex != null && st.u == null) return { kind: "unknown", color: "unknown", width: 1, dash: 0, cut: false, mark: false };
  return { kind: "normal", color: "line", width: 1, dash: 0, cut: false, mark: false };
}
