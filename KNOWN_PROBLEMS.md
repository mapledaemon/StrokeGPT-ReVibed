# Known Problems

This file tracks known rough edges that are visible to users but not blocking
the current branch. Move fixed items into `Changelog.txt` when they are resolved.

## Handy Visualizer Alignment And Latency

Status: Partial / Needs Real-Device Verification

The sidebar Handy cylinder is a commanded-motion estimate, not a confirmed
live device-position readout. The green range band now maps to the active
program's observed min/max depth window when the backend emits one, and the
purple position line estimates the current commanded position from the active
backend: continuous sampled output replay for Continuous position, trace
interpolation for finite position playback, and phase estimation inside the
active slide window for HAMP legacy. It can still show latency or misalignment
compared with the physical Handy when browser polling, network timing, Handy
firmware behavior, or local velocity assumptions diverge from the device.

Follow-up work:

- Compare commanded position against live Handy position if the device/API path
  exposes a practical polling endpoint.
- Verify the continuous trace replay against the physical device at slow and
  fast speeds, then tune the local estimate against calibrated stroke range,
  physical position, and status polling cadence without adding excessive Handy
  API traffic.
- Re-check finite position/script playback and HAMP legacy on hardware; their
  visual range now follows program/slide min/max, but the position line is
  still an estimate rather than a live device readout.

## Continuous Position Backend Real-Device Readiness

Status: Open / Needs Verification

Continuous position is now the default app-motion backend. Fixed patterns and
anchor programs run as live sampled control bases instead of finite repeating
scripts, while HAMP remains selectable as a legacy fallback. This still needs
real Handy testing because recent manual testing showed boundary
stutter/stopping in Freestyle and direction-change smoothing that was not
obvious enough on-device.

Transition notes to preserve when the motion schema is fully replaced:

- Keep one shared playback sanitizer for trained patterns, imported scripts,
  Freestyle, Edge/Milk scripts, and plain chat-generated targets.
- Keep continuous planners interruptible by the same generation/stop/pause
  boundary as every other motion path.
- Keep XAVA/position velocity capped against the current user max-speed setting,
  not only against pattern-local speed.
- Keep depth jump splitting and turn-apex smoothing in the backend layer so
  every caller benefits from reversal and oversized-step protection.

Follow-up work:

- Compare HAMP legacy, finite position playback, and Continuous position on
  the physical Handy using the same speed limits, depth/range settings, and
  pattern set.
- Re-test plain LLM and Legacy Auto targets that do not resolve to a named
  fixed pattern. These should now use live stroke control in the default
  continuous backend instead of single-depth position playback, so visible
  speed changes should translate to device velocity changes again.
- Verify that Continuous position speed changes now affect HSP point timing on
  firmware v4 and HDSP fallback cadence/command-speed budget on legacy paths.
  The trace separates semantic `intent_speed`, sampled `sample_speed`,
  `sample_tempo_scale`, `effective_cycle_ms`, `sample_interval_ms`, HSP point
  metadata, final fallback `handy_velocity`, and HSP `hsp_transport_time_scale`;
  use those fields together when diagnosing fixed-speed feel. HSP should now
  preserve authored sub-sample phase intervals without local point-to-point
  velocity stretching. Flexible Position may still stretch `xpt.t` when an
  authored direct position move would exceed the configured speed cap.
  Continuous HDSP fallback should show varied `handy_duration_ms` values because
  its `xpt.t` is derived from the velocity budget again. If speed still feels
  compressed, compare point-preview intervals, wire HSP `x` values (`0..100`
  position units relative to the active `/slider/stroke` window),
  `hsp_segment_depth_per_second`, fallback `handy_duration_ms`, HSP response
  state, and physical movement before changing sampler math again. For HSP,
  `phase_interval_ms`, `transport_interval_ms`, and `sample_interval_ms` should
  match; if they diverge, software is flattening the timed stream again.
  `physical_speed` and `hsp_segment_mm_per_second` in HSP trace rows are planned
  outgoing point slopes, not measured device speed. Use
  `hsp_state_current_time_ms`, `hsp_state_current_point`,
  `hsp_state_play_state`, and `hsp_clock_sync` rows to confirm whether firmware
  is actually advancing through the streamed points at the planned time.
  Pattern swaps should reuse an already-active HSP setup, start with an exact
  point at `hsp/play.start_time`, flush the replacement buffer through
  `/hsp/add`, update the tail threshold via `/hsp/threshold`, and play with
  `pause_on_starving: false`;
  if swaps still pause, inspect whether command history shows a repeated
  `hsp/setup`, stale `server_time`, threshold, or starvation behavior before
  changing sampler math again. Sparse
  built-in patterns now share one timed point projection for HSP and Flexible
  Position, including inserted intermediate points between authored endpoints;
  verify on-device that this restores smooth speed variation without disturbing
  dense imported timing. HAMP should be compared as the legacy stroke-window
  adapter rather than as a timed-point transport.
- Before changing sampler math for fixed-speed Continuous reports, confirm that
  firmware v4 actually entered HSP. Motion transport captures now include
  `api_v3_enabled`, `api_v3_key_configured`, `api_v3_auth_failed`,
  `api_v3_unavailable_reason`, and `continuous_schema=hdsp_fallback` when the
  controller is running Continuous through slow HDSP fallback instead of HSP;
  missing/failed v3 auth here means the public API v3 Application ID path, not
  the user's Handy connection key field.
- Verify Freestyle runs continuously without regular stop intervals or visible
  speed-limit escapes.
- Use the normal Freestyle trace metadata (`freestyle_pattern_id`,
  `freestyle_planner_sleep_ms`, choice score/mood, and controller `gap_ms` /
  `command_ms`) plus the Handy command-result fields (`handy_ok`,
  `handy_path`, `handy_status`, and `handy_error`) during device testing to
  distinguish planner waits, controller command timing, and rejected/failed
  HSP/HDSP requests. Handy diagnostics now also include a bounded
  `command_history` with sanitized request bodies and HSP point previews; use
  that history to compare what the app actually sent in HAMP, HDSP, and HSP
  before changing sampler math again.
- If Continuous still feels fixed-speed, first verify that `sample_tempo_scale`
  spans the full relative intent range for explicit slow/fast requests
  regardless of the saved velocity-limit band. A prior regression converted
  relative intent speed into physical Handy velocity before sampling, then
  treated that velocity as relative intent again; that unit mix compressed
  patterns into a narrow low-speed band even when the visualizer showed
  changing sample speeds. HSP should not have a local point-to-point duration
  ceiling, and it should not rewrite `MotionTarget.speed` through
  `effective_speed_for_relative()` before sampling. Timed position/HDSP
  transports still convert speed settings to absolute mm/s duration caps.
- Confirm intra-script reversal smoothing is apparent on-device for fast
  patterns, wide strokes, and Edge/Milk scripts.
- Keep HAMP selectable until these checks pass.

## Visual Element Formatting

Status: Watch

Some UI elements still need visual polish after the motion observability and
training-window work. Known rough spots include line distance, vertical spacing,
button grouping, tight control rows, and alignment of compact indicators at
different window sizes.

Follow-up work:

- Watch for user-visible spacing problems after the chat footer, settings
  tabs, Motion Training window, and motion status strip passes.
- Prefer small layout fixes and responsive constraints over large visual
  rewrites unless the current structure blocks clean formatting.
## Voice Input Settings Surface Is Overexposed

Status: Partial

Settings > Voice now exposes provider/mode/transcript handling, hands-free
sensitivity and clip timing, browser microphone processing toggles, calibrated
noise floor, model preset/custom path, language, beam size, previous-transcript
context, and VAD threshold/silence/padding controls. Those controls are useful
for debugging, but the default surface currently makes voice reliability feel
like a 12-knob user problem before the app has proven good defaults on real
microphones.

The default Voice tab now keeps the normal path to provider, recording mode,
transcript handling, hands-free sensitivity/calibration, model preset/path, and
language, with raw capture and recognition controls collapsed under advanced
panels. The remaining problem is deciding, from real microphone use, whether
those advanced controls should stay reachable, move to diagnostics, or disappear
from routine settings entirely.

Follow-up work:

- Use real push-to-talk and hands-free microphone testing to decide which
  controls users actually need during normal operation.
- Move faster-whisper internals such as beam size, condition-previous, and VAD
  threshold/silence/padding farther out of the routine path unless testing
  shows they are necessary for common recovery.
- Do not add more visible voice-input tuning controls before the current
  defaults have been validated and simplified.

## Local LLM Chat Text Sometimes Missing While Voice Plays

Status: Partial / Watch

The local LLM occasionally emits a reply that the TTS path speaks normally while
the chat panel never displays the matching text. The voice model receives the
message even though the user-facing transcript is missing the line, so the
divergence appears to be between the chat-emit path and the TTS-enqueue path
rather than a model failure.

The initiating browser now renders the `chat` text returned by `/send_message`
immediately when the backend also reports `chat_queued: true`, then skips the
matching queued echo from the next `/get_updates` response. That removes the
known queue-drain race where the reply was spoken and returned to the caller,
but the caller waited for a later update poll that another tab could consume
first.

A backend diagnostic now logs `[WARN] TTS enqueued without chat-emit ...` or
`[WARN] TTS enqueued with empty chat text ...` from
`strokegpt.web.add_message_to_queue` whenever the TTS-enqueue path runs without
a matching chat-emit (either `queue_message=False` or text that strips to
empty). That still gives a backend signal if a future caller sends voice
without a visible chat emit. The same diagnostic now also reaches the browser
as a one-shot `/get_updates` warning, so the status strip shows the
voice/chat-path mismatch instead of leaving the problem terminal-only.

Local model transport failures now return a direct `model_error` response to
the initiating browser instead of entering the queued assistant-message path.
The front end renders those as `MODEL ERROR` bubbles with an error status tone,
and the backend keeps them out of chat history, TTS, persona-turn countdowns,
and motion application.

The browser now prefers a streamed `/send_message_stream` path for normal
chat. That path renders the `chat` field as Ollama streams JSON content, then
waits for final JSON validation before applying motion or starting TTS; the
existing `/send_message` path remains the fallback for browsers without
readable fetch streams.

Follow-up work:

- Verify the chat-emit path runs in lockstep with the TTS-enqueue path across
  both streamed and non-streamed Ollama responses, especially when motion
  repair replaces the streamed draft chat with corrected final text.
- Confirm the front-end chat panel is not silently dropping ordinary assistant
  messages when a prior message is mid-render or while a mode transition is
  updating the status strip. Pair the next reproduction attempt with the
  backend warning so both sides can be compared.

## Web UI Stays Functional After Backend Shutdown

Status: Watch / Needs Browser Smoke

A persistent connection-lost banner and backend-required control lock are in
place: any connection-aware `fetch()` failure flips a fixed top-of-viewport
banner visible and disables controls marked `data-requires-backend`; the next
successful response hides the banner and restores those controls without
unlocking controls that were already disabled. The "backend reachable but
rejected the write" case surfaces the backend's `message` through either the
global status text or the affected control's local status span.

The frontend now uses one explicit status helper for backend-failure tones:
network/backend loss and HTTP errors use the global status line with an error
tone, while reachable route rejections use one local warning near the affected
control. `reportSaveFailure()` stays silent when `apiCall()` has already
reported a network or HTTP failure, so handlers do not overwrite the useful
global line with a second generic warning.

The code audit for known write/action controls is complete. Settings saves,
motion pattern feedback, motion training start/preview/stop/save/feedback,
like/dislike, Edge/Milk/Freestyle starts, LLM edge permissions, pause/resume,
I'm Close, and local TTS model preload all use the shared reachable-backend
failure helper where their success shape is not met. Source-text coverage for
the connection-lost behavior was retired in favor of Node runtime tests; static
markup/CSS coverage remains in the web asset test.

Remaining watch work:

- Smoke-test the real browser flow by starting the app, opening Settings,
  stopping the backend process, and confirming the banner/control lock and
  per-control failure copy still match the runtime tests.
- Do not expand warning/status styling ad hoc. If real use shows that save
  failures, slow ASR warnings, unavailable models, and other warnings are still
  visually ambiguous, extend the shared status-tone helper rather than adding
  handler-by-handler color writes.
- Confirm feedback-driven changes to weights or pattern enablement show the
  resulting numeric value in the GUI immediately so the user can see the
  change took effect rather than guessing from device behavior.

## Single Active Browser Session Assumption

Status: Warned / Watch

The runtime is designed as one local Flask process controlling one Handy with
one shared `AppState`, one `messages_for_ui` queue, one audio output queue, one
settings file, and one active mode controller. That matches the local-machine
product shape. The README now calls the app a single-operator local controller
and the Troubleshooting section tells users to keep one active browser tab
while controlling hardware. The browser now also shows a small warning when
more than one active StrokeGPT tab is detected through local tab heartbeats.

Follow-up work:

- Avoid multi-user/session architecture unless the project direction changes;
  the near-term fix is expectation-setting, not auth or per-session state.
- If repeated multi-tab confusion continues, refine the warning copy or
  placement rather than pretending the current shared queues are tab-isolated.
