# Motion Control Mode Notes

This note preserves motion-control decisions that should be re-evaluated when
new LLM-driven motion modes are designed.

## Area-Focus Morph Regression

In June 2026, normal chat and Freestyle testing showed repeated stop/go or
"brick wall" motion when the trace label included `area_focus continuous
morph`. Earlier fixes improved buffering and point cadence but did not resolve
the on-device feel once the path entered HSP morph replacement.

The important regression was not just sampler math. PR #314 had moved more LLM
motion into the HSP area-focus morph path, including explicit `anchor_loop`
programs and active generated regional focus retargets. That violated the
older PR #242 / PR #243 real-device finding that explicit LLM anchor-loop HSP
replacements felt micro-stepped, while live-stroke control was smoother.

The HSP morph path also had two design hazards:

- A spatial morph blends from the predicted old position into a new moving
  cyclic sample. Depending on the selected phase, that blend can cancel part of
  the cycle and create near-hold segments.
- A replacement scheduled at a fixed future lead can land while the old stream
  is moving in the opposite direction from the new target. On hardware this can
  feel like hitting an endpoint before the new motion starts.

## Current Route Policy

The current policy intentionally separates generated chat focus changes from
remaining HSP area-focus playback:

- Explicit LLM `anchor_loop` / bounce programs use the live-stroke bypass,
  even when HSP streaming is available.
- Active generated regional focus retargets also use the live-stroke bypass,
  avoiding flushed HSP morph replacements during normal chat changes.
  They must still pass through the area-focus localization step first, so
  `tip`, `shaft`, and `base` requests become bounded local stroke windows
  instead of raw broad LLM targets.
- Active *plain* chat retargets (no zone program, no pattern label — e.g.
  "faster", "slower", numeric speed/depth adjustments) also take the
  live-stroke bypass (`generated_plain_retarget_hsp_morph_bypass`). Before
  this, every plain chat adjustment triggered a flushed HSP area-focus morph
  replacement, which is where the user-visible stop/go "morph" reports in
  normal chat came from. The bypass is scoped to chat sources (`llm`,
  `chat command`, `chat motion keepalive`); Freestyle and the scripted modes
  intentionally keep swapping patterns through HSP area-focus replacement
  streaming.
- Idle generated area-focus starts may still use HSP area-focus streaming.
- Remaining HSP area-focus intent morphs choose a handoff time and replacement
  phase that avoid opposing-direction and near-hold segments during the first
  morph window.

When debugging this path, check trace fields such as
`continuous_schema`, `active_continuous_schema`, `continuous_plan_kind`, `hsp_replacement_kind`,
`morph_phase_frozen`, `hsp_area_focus_handoff_delay_ms`,
`hsp_area_focus_handoff_reason`, `hsp_segment_depth_per_second`, and the Handy
command result fields. For generated chat focus changes while motion is active,
seeing `continuous_schema=hamp_live_anchor` is expected; seeing a flushed HSP
replacement labeled `area_focus continuous morph` is suspicious unless the
caller intentionally requested the internal HSP area-focus path.

Because `hamp_live_anchor` is not an HSP stream, stale or starving HSP state
from a previous stream should not trigger chat keepalive recovery while the
live-stroke bypass is active. Keepalive should restart motion only when the
current transport is actually inactive or the active HSP stream reports stale
playback.

## Future LLM Control Modes

The LLM still needs ways to change things up. In particular, future modes
should support combining multiple styles into a repeating sequence, but that
should be implemented as a higher-level planner contract rather than by
letting the model trigger low-level HSP morph replacements every turn.

Preferred direction:

- Let the LLM choose or request a bounded "motion arrangement" made of named
  styles, focus regions, durations, repetitions, and intensity drift.
- Compile that arrangement in deterministic code into a stable continuous plan,
  authored-HSP sequence, or live-stroke sequence with explicit transition
  rules.
- Keep each segment long enough to establish a feel before switching, usually
  multiple cycles or a short timed hold window rather than one chat turn.
- Preserve user safety settings and max speed as transport-layer caps, not as
  hidden prompt-only behavior.
- Surface the active arrangement in diagnostics so users can tell whether the
  LLM changed style, focus region, speed, pattern source, or mode.

Avoid designing new LLM modes that directly expose transport details like
HSP replacement, HDSP position frames, morph duration, or phase offsets. Those
should remain backend implementation details with tests and trace fields.
