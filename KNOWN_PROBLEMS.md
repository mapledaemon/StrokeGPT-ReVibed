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
