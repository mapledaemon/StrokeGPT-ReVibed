# Known Problems

This file tracks known rough edges that are visible to users but not blocking
the current branch. Move fixed items into `Changelog.txt` when they are resolved.

## Handy Visualizer Alignment And Latency

Status: Open

The sidebar Handy cylinder is currently a commanded-motion estimate, not a
confirmed live device-position readout. It can still show poor alignment or
slight latency compared with the physical Handy, especially when switching
between HAMP and the experimental position/script backend or when network/API
timing differs from local command timing.

Follow-up work:

- Compare commanded position against live Handy position if the device/API path
  exposes a practical polling endpoint.
- Keep the green cylinder background static; only the purple position line
  should move.
- Tune the local estimate against calibrated stroke range, physical position,
  and status polling cadence without adding excessive Handy API traffic.

## Flexible Position Backend Default Readiness

Status: Open / Needs Verification

The experimental flexible position/script backend now routes pattern playback,
Freestyle playback, motion training previews, and plain chat-generated targets
through shared smoothing and velocity guard rails. It still needs real Handy
testing before it replaces HAMP as the default, because recent manual testing
showed boundary stutter/stopping in Freestyle and direction-change smoothing
that was not obvious enough on-device. PR #42 added a current-position bridge
and per-frame timing traces that may have fixed the regular Freestyle stop, but
that needs longer on-device confirmation before the problem is closed or the
flexible backend is promoted.

Transition notes to preserve when the motion schema is fully replaced:

- Keep one shared playback sanitizer for trained patterns, imported scripts,
  Freestyle, Edge/Milk scripts, and plain chat-generated targets.
- Keep final-target pass-through available for continuous planners so one
  selected segment can slide into the next without a stop-on-target boundary.
- Keep XAVA/position velocity capped against the current user max-speed setting,
  not only against pattern-local speed.
- Keep depth jump splitting and turn-apex smoothing in the backend layer so
  every caller benefits from reversal and oversized-step protection.

Follow-up work:

- Compare HAMP and flexible position playback on the physical Handy using the
  same speed limits, depth/range settings, and pattern set.
- Verify Freestyle runs continuously without regular stop intervals or visible
  speed-limit escapes.
- Instrument the normal Freestyle command loop and Handy command responses to
  distinguish planner gaps, XAVA command completion, rejected commands, and
  device-side position-mode behavior.
- Confirm intra-script reversal smoothing is apparent on-device for fast
  patterns, wide strokes, and Edge/Milk scripts.
- Keep HAMP as the default until these checks pass.

## Visual Element Formatting

Status: Open

Some UI elements still need visual polish after the motion observability and
training-window work. Known rough spots include line distance, vertical spacing,
button grouping, tight control rows, and alignment of compact indicators at
different window sizes.

Follow-up work:

- Review spacing in the main chat footer, sidebar control stack, settings tabs,
  model controls, and motion training window at common desktop and mobile
  widths.
- Keep status bars and feedback controls compact without oversized bezels.
- Prefer small layout fixes and responsive constraints over large visual
  rewrites unless the current structure blocks clean formatting.
