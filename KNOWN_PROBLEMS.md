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
- Verify Freestyle runs continuously without regular stop intervals or visible
  speed-limit escapes.
- Instrument the normal Freestyle command loop and Handy command responses to
  distinguish planner gaps, XAVA command completion, rejected commands, and
  device-side position-mode behavior.
- Confirm intra-script reversal smoothing is apparent on-device for fast
  patterns, wide strokes, and Edge/Milk scripts.
- Keep HAMP selectable until these checks pass.

## Visual Element Formatting

Status: Partial

Some UI elements still need visual polish after the motion observability and
training-window work. Known rough spots include line distance, vertical spacing,
button grouping, tight control rows, and alignment of compact indicators at
different window sizes.

Follow-up work:

- Review spacing in the main chat footer, settings tabs, model controls, and
  motion training window at common desktop and mobile widths.
- Keep status bars and feedback controls compact without oversized bezels.
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
without a visible chat emit.

Local model transport failures now return a direct `model_error` response to
the initiating browser instead of entering the queued assistant-message path.
The front end renders those as `MODEL ERROR` bubbles with an error status tone,
and the backend keeps them out of chat history, TTS, persona-turn countdowns,
and motion application.

Follow-up work:

- Verify the chat-emit path runs in lockstep with the TTS-enqueue path for both
  streamed and non-streamed Ollama responses. The current fix covers the
  non-streamed `/send_message` response path; future streaming work should keep
  the same "render once, play once" contract.
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

Status: Documented / Watch

The runtime is designed as one local Flask process controlling one Handy with
one shared `AppState`, one `messages_for_ui` queue, one audio output queue, one
settings file, and one active mode controller. That matches the local-machine
product shape. The README now calls the app a single-operator local controller
and the Troubleshooting section tells users to keep one active browser tab
while controlling hardware.

Follow-up work:

- Avoid multi-user/session architecture unless the project direction changes;
  the near-term fix is expectation-setting, not auth or per-session state.
- If repeated multi-tab confusion is observed, show a small in-app warning
  rather than pretending the current shared queues are tab-isolated.
