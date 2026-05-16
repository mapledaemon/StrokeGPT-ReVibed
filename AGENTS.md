# Agent Handoff

This is the canonical shared handoff for future coding agents continuing StrokeGPT-ReVibed. Keep it free of machine-specific paths, account names, private emails, credentials, and local environment details.

## Project Summary

StrokeGPT-ReVibed is a work-in-progress fork/refactor of StrokeGPT. It is a local Flask web app for controlling The Handy through natural language, Ollama model responses, deterministic motion reliability logic, and optional voice output.

The current goal is incremental, test-backed feature work that also makes the
app easier to safely maintain. Keep each branch scoped, document user-visible
behavior, and route motion changes through the shared controller path.

## Documentation Layout

- `AGENTS.md`: canonical shared handoff for all coding agents.
- `Codex.md`: compatibility entry point that points to `AGENTS.md`.
- `CLAUDE.md`: compatibility entry point that points to `AGENTS.md`.
- `README.md`: user-facing setup, install, and project overview.
- `Changelog.txt`: fork PR history and the current branch entry. Completed
  work belongs here, not in the roadmap.
- `ROADMAP.md`: future work only, grouped into Up Next / Queued / Backlog /
  Long-Horizon tiers.
- `KNOWN_PROBLEMS.md`: visible rough edges and open regressions that should
  survive between branches until fixed.
- `docs/local_voice_setup.md`: manual CUDA PyTorch install paths for fast
  local Chatterbox voice on non-Windows or custom NVIDIA setups.
- `docs/lan_https.md`: LAN/mobile browser HTTPS setup, local certificate trust
  notes, and Mobile Chrome exact-IP troubleshooting.
- `docs/voice_input.md`: voice-input provider details (NVIDIA Parakeet vs
  faster-whisper), Parakeet runtime install, and the hands-free /
  typed-chat mode-action toggles.
- `docs/ollama_gpu.md`: GPU acceleration notes for AMD/Intel/non-default
  hardware paths and VRAM detection caveats.
- `docs/motion_training_prompts.md`: archived staged prompts for the motion
  training workstream. Keep these pointing at `AGENTS.md`.

## Current Architecture

- `app.py`: thin launcher that imports `strokegpt.web.main`.
- `index.html`: single-page browser UI markup.
- `static/app.css`: browser UI styles.
- `static/app.js`: browser UI entrypoint and polling orchestration.
- `static/js/`: focused browser modules for shared context, settings, chat,
  audio, device controls, motion controls, and setup. `static/js/motion/`
  holds the split motion sub-modules (sequence log, pause/hotkey controls,
  pattern list, feedback controls, training editor); `motion-control.js`
  stays as the top-level wiring boundary with compatibility re-exports.
- `strokegpt/web.py`: Flask app composition, shared services, chat/update
  runtime, and compatibility exports.
- `strokegpt/app_state.py`: mutable web runtime state and shared `RLock`
  boundary.
- `strokegpt/blueprints/`: domain route modules for settings, motion, audio,
  and preset/mode controls.
- `strokegpt/payloads.py`: settings, Ollama status, and motion-pattern payload
  builders for browser routes.
- `strokegpt/server_tls.py`: optional local HTTPS certificate handling for
  LAN browser voice input.
- `strokegpt/settings.py`: JSON-backed user/app settings.
- `strokegpt/handy.py`: The Handy API wrapper.
- `strokegpt/llm.py`: Ollama API integration and prompt construction.
- `strokegpt/motion.py`: deterministic intent matching, safety clamping, and smooth transitions.
- `strokegpt/motion_anchors.py`: soft anchor-loop program parsing and
  waypoint semantics.
- `strokegpt/motion_preferences.py`: visible pattern weights and feedback
  summaries for LLM context.
- `strokegpt/motion_patterns.py`: reusable normalized motion pattern shapes,
  the continuous `MotionSample` schema, and the JSON loader that materializes
  the built-in catalog at import time.
- `strokegpt/builtin_patterns.json`: pure data file holding the 34 built-in
  `MotionPattern` definitions consumed by `motion_patterns._load_builtin
  _patterns()`. Keeping the data in JSON keeps it free of Python imports.
- `strokegpt/pattern_library.py`: shareable motion pattern schema, built-in
  pattern catalog, and user pattern file registry.
- `strokegpt/program_library.py`: separate long-form Programs (funscripts)
  schema and user program registry for imported full timelines that should not
  be treated as short LLM-selectable loop patterns.
- `strokegpt/motion_scripts.py`: longer scripted motion plans.
- `strokegpt/background_modes.py`: auto, edging, milking, and freestyle mode
  orchestration.
- `strokegpt/freestyle.py`: Freestyle pattern selection, scoring, and playback
  helpers.
- `strokegpt/mode_decisions.py`: mode-decision parsing, coercion, and
  intensity helpers.
- `strokegpt/mode_contracts.py`: typed service/callback contracts shared by
  `web.py`, `background_modes.py`, and `mode_decisions.py`.
- `strokegpt/audio.py`: ElevenLabs and local Chatterbox TTS providers.
- `scripts/bootstrap_windows.ps1`: first-run Windows helper that downloads or
  clones the repo, optionally installs Git, and then runs the installer.
- `scripts/install_windows.ps1`: Windows install helper with prompts for
  Python 3.11, Ollama, default Ollama model download, CUDA PyTorch, and
  optional Parakeet voice-input runtime setup.
- `scripts/update_windows.ps1`: Windows user-update helper for Git
  fast-forward, dependency refresh, optional Parakeet runtime refresh, and
  validation.
- `tests/`: focused regression tests.

## Current Progress Snapshot

- The April reorganization sequence split the biggest legacy modules:
  Freestyle and mode-decision helpers left `background_modes.py`, Flask routes
  moved into blueprints, browser payload builders moved into `payloads.py`,
  mutable web runtime state moved into `AppState`, and typed mode contracts
  plus bridge/payload guard tests now pin the remaining compatibility seams.
- The frontend motion-control split is complete through
  `static/js/motion/{sequence-log,pause-controls,pattern-list,
  feedback-controls,training-editor}.js`; `static/js/motion-control.js`
  should stay as wiring and compatibility exports instead of regrowing domain
  behavior.
- Built-in fixed motion patterns now live in `strokegpt/builtin_patterns.json`,
  with `motion_patterns.py` responsible for loading, normalizing, expanding,
  and sampling them. Continuous position is the recommended default backend,
  while HAMP remains a selectable legacy fallback pending real-device checks.
- The browser shell has gained responsive chat/layout foundations, profile
  menu/About surfaces, backend-required control locking, single-tab warning,
  top-bar voice controls, streamed chat rendering, fenced-code rendering, and
  Node-based frontend behavioral tests.
- Voice input now has a flexible ASR foundation, faster-whisper and optional
  NVIDIA Parakeet provider paths, push-to-talk / hands-free UI plumbing,
  microphone calibration, confidence gates, diagnostics, and a simplified
  routine Voice settings surface with advanced capture controls collapsed.
- Recent mode and motion work added guarded hands-free and typed-chat
  `mode_action` permissions, editable Ollama model options and GPU-fit
  warnings, natural preset-mode narration, a visible Motion Style selector,
  startup speedups, and hot-path speedups for streamed chat, polling, voice
  model cache checks, and continuous motion traces.
- `Changelog.txt` is the detailed PR history source of truth. Keep this
  snapshot high-level and update it only when a new workstream changes the
  current architecture or next-agent assumptions.

## Runtime Requirements

- Python, preferably 3.11 for local Chatterbox TTS.
- Ollama running locally.
- Default model: `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b`.
- Python dependencies are listed in `requirements.txt`.
- The Handy control API requires internet access.
- ElevenLabs voice output requires an API key.
- Local Chatterbox voice output can be slow and dependency-sensitive.

## Current UI Shape

The sidebar should stay sparse:

- Control Actions
- Preset Modes
- Standalone emergency stop

The upper-right profile image opens a compact menu with Settings and About.
Keep routine settings entry points there instead of adding another full-width
sidebar button. The About popup reuses the README Support Development text
plus the repo-local Bitcoin and Ethereum QR assets.

The top bar status area uses separate fixed-size active-mode label and timer
chips, followed by the mood chip, so long mode names or elapsed clocks do not
resize each other.

The unified settings popup has tabs:

- Persona
- Model
- Voice
- Device
- Motion
- Prompts (read-only visibility into the system prompts the local model
  can receive: chat, motion repair, name-this-move, profile
  consolidation. Lazy-loaded on first open; refresh button re-renders
  against the current context.)
- Diagnostics (setup checks, Ollama/voice latency probes, and diagnostics
  verbosity. Latency probes must not trigger surprise model downloads or paid
  hosted TTS calls; they measure only already-loaded local voice paths.)
- Advanced

Do not move detailed settings back into the sidebar unless there is a strong usability reason.

## Important Implementation Notes

- The app intentionally uses a deterministic motion layer between LLM output and hardware commands.
- The motion layer is primarily for reliability: spatial language mapping, pattern expansion, configured speed limits, and consistent stop behavior.
- The LLM may provide direct numeric moves or named zone/pattern cues, but hardware movement should still pass through `MotionController` and `HandyController`.
- Behavior-preserving refactors should use the house compatibility pattern:
  extract the new module, bridge old imports/attributes, add a regression test
  for the bridge, then migrate callers in a follow-up PR. Mark compatibility
  re-exports, aliases, and bridges with a comment such as "Compatibility shim -
  do not extend" so new code imports from the canonical module instead of
  expanding the shim surface.
- When an extraction creates a new cross-module contract, define the
  `TypedDict`/`Protocol` contract and a small contract regression test in the
  same PR.
- If the LLM claims or appears to need a motion change but sends no usable
  movement target, the web connector performs one repair prompt. The repair
  pass must still allow `move: null` for conversational or informational
  requests.
- Keep motion transitions smooth and clamped to user settings.
- `HandyController.diagnostics()` includes the last non-secret Handy command
  result (`path`, `ok`, status, elapsed milliseconds, safe body fields, and
  error text). Motion trace rows may mirror that as `handy_ok` /
  `handy_path` / `handy_status` / `handy_error`; use those fields to separate
  planner waits from device/API rejection during real-device debugging. HSP
  trace rows use scheduled point times and also include
  `hsp_segment_depth_per_second` after the first point so reviewers can inspect
  the actual timed-point transport slope instead of the time a future batch was
  buffered. For HSP, `physical_speed` / `hsp_segment_mm_per_second` in trace
  rows is a planned slope derived from outgoing timed points, not confirmed
  device speed. Prefer HSP response-state fields such as
  `hsp_state_current_time_ms`, `hsp_state_current_point`, and
  `hsp_state_play_state` when checking whether firmware is actually following
  the planned stream.
- `strokegpt/motion_patterns.py` prepares pattern actions before expansion: sort/dedupe, minimum interval filtering, repeat expansion, eased interpolation, large-step limiting, and redundant point simplification. Keep that pipeline dependency-free unless a larger funscript importer is deliberately added.
- Long imported funscripts belong in the separate Programs (funscripts) library
  rather than being forced through the short pattern library. Programs are for
  authored timelines that should preserve long timing/shape; future playback
  still has to route through the shared motion controller and Handy safety path.
- `strokegpt/motion_preferences.py` turns enabled fixed patterns and thumbs
  feedback into simple LLM-facing weights. Disabled fixed patterns should stay
  visible in settings but hidden from the LLM prompt to avoid confusing smaller
  local models.
- Motion backend selection is persisted as `motion_backend`. `continuous` is
  the recommended app-motion default: fixed patterns and anchor programs are
  phase-sampled as live position control until the next command or stop.
  Plain generated targets that do not resolve to a fixed pattern or anchor
  program should stay on live stroke control so LLM/direct commands still
  apply velocity and stroke-window changes as continuous motion, not as a
  one-shot position move.
  Keep `hamp` selectable only as a legacy fallback unless real-device testing
  shows the continuous backend is worse for a specific recovery path.
- Handy firmware selection is persisted as `handy_firmware_version`, and REST
  v3 authentication uses the persisted `handy_api_v3_key` public Application
  ID plus the normal Handy connection key. Firmware v4 with both values
  configured enables HSP timed point streaming for the continuous backend, v3
  HAMP commands for live stroke control, and v3 HDSP `xpt` duration moves for
  position playback. HSP playback should follow the current v3 split of
  `hsp/add` timed points followed by `hsp/play` with server time metadata; do
  not rely on speed-only visualizer fields as the transport contract. For v3
  HDSP `xpt`, send `xp` as the current REST v3 normalized physical position
  (`0..1`) after applying local stroke-depth calibration; HSP timed points send
  current HSP/funscript `0..100` position units directly and rely on
  `/slider/stroke` for the saved physical depth window. Do not multiply HSP
  `x` values into a `0..1000` range, and do not pre-apply the local
  stroke-depth calibration to each HSP point unless current upstream Handy
  documentation and real-device traces prove that the REST v3 HSP point schema
  changed again. Firmware v3 / legacy mode, v4 without the Application ID, or
  v4 after an API v3 401 auth failure should not silently run Continuous
  through HDSP direct-position fallback; report HSP as unavailable and let the
  user choose HAMP legacy or fix credentials. When diagnosing fixed-speed
  continuous motion, check
  `api_v3_enabled`, `api_v3_key_configured`, `api_v3_auth_failed`, and
  `api_v3_unavailable_reason` before changing sampler math.
- Continuous position keeps semantic intent speed separate from the transport
  schema. `MotionTarget.speed` remains the user/LLM speed intent. HSP encodes
  speed as timed point spacing and position deltas; direct-position HDSP paths
  derive a per-sample command-speed budget in `MotionSample.target.speed`, with
  the Handy command's `velocity` as the final mm/s value after distance,
  command interval, and user speed-limit clamping. Derived sample speed must
  remain intent-relative; do not let a low requested speed saturate every
  direct-position XAVA frame at the user maximum, and do not feed it back
  into `motion.current_target()`, Freestyle scoring, or LLM context. Continuous
  HSP must not apply saved speed limits by rewriting `MotionTarget.speed`
  before sampling; that converts physical velocity back into relative intent
  and compresses `sample_tempo_scale`. Physical mm/s duration caps belong to
  HDSP/Flexible Position direct moves, not HSP timed-point spacing.
  Continuous morphing and step limiting smooth depth/range only; do not
  interpolate or delta-limit the command-speed budget as if it were a spatial
  target. HSP timed-point streams must preserve authored phase timing and
  point-to-point depth deltas; do not stretch HSP timestamps through a
  point-to-point velocity budget because that flattens fast segments into a
  fixed-slope feel. Flexible Position `xpt.t` durations may still be stretched
  when an authored timed move exceeds the configured Handy speed cap.
  Pattern swaps should not repeat HSP setup or resend `/hsp/play` while an HSP
  stream is already active. Rebuffer the replacement plan through a flushed
  `/hsp/add` scheduled against the active HSP stream clock, update
  `/hsp/threshold`, and keep playback running so pattern changes do not pause
  during setup or play-start latency. Replacement points need enough future
  lead time to survive observed REST command latency; use recent HSP command
  timing plus padding rather than scheduling the first replacement point only a
  few milliseconds ahead of the estimated clock. Active HSP streams should only correct
  firmware playback time through soft, delayed `/hsp/synctime` updates and
  preserve sanitized response state in diagnostics so planned point timing can
  be compared with device-reported playback. If the response state reports
  `current_time_ms` already past the buffered point range, restart `/hsp/play`
  at the first newly-added point instead of sending more expired points or
  trying to pull the firmware clock back through `/hsp/synctime`.
  Sparse built-in HSP streams should keep
  authored endpoints but insert Catmull-Rom intermediate points inside long
  segments so firmware receives the smooth curve rather than long linear
  keyframes, while filtering sub-frame prepared points that create transport
  chatter without materially changing the curve. Replacement HSP streams should
  include an exact point at the replacement stream time and no pre-start points
  so mid-cycle swaps do not snap toward a stale endpoint. During active continuous playback,
  `MotionController.current_target()` estimates the current sampled target
  from the active plan clock; do not use the tail of the future HSP buffer as
  the current device state. If an active HSP append fails, treat the stream as
  failed and stop the continuous worker without demoting to HDSP direct
  position playback.
  Same-pattern continuous updates should preserve phase. New-pattern
  replacements may choose the phase whose sampled depth/range is closest to
  the current target before minimum-jerk morphing, instead of always starting
  at phase zero and forcing a larger transition.
  Keep direct-position step limiting on HDSP/direct fallback moves instead of
  applying it to every HSP point. Flexible Position fixed-pattern playback
  uses the same `TimedMotionPoint` projection as HSP streaming so `hdsp/xpt`
  durations, HSP point spacing, and planned point slopes describe the same
  pattern envelope; HAMP adapts patterns through legacy stroke-window frames
  only as the fallback backend.
- `strokegpt/motion_anchors.py` defines soft anchor-loop programs. These let the model choose 2-6 waypoint labels while the backend compiles them into Catmull/minimum-jerk action streams with bounded target deltas. `shaft` is accepted as the user-facing midpoint label, with `middle`/`mid` kept as aliases. Treat anchors as soft waypoints, not hard stops.
- Spatial cues should treat `tip`, `shaft`, and `base` as regions of emphasis,
  not single lock points. `shaft` is the in-between region; ordinary zone cues
  should prefer adjacent regional travel, while tight endpoint focus should
  require explicit tiny/short/flick/flutter/hold style wording.
- Area-only focus commands should not inherit a previous high-speed state. When
  reducing speed and changing Handy slide bounds, `HandyController.move()` must
  send the lower velocity before the new bounds so the device does not jump to a
  new region at the old speed.
- When Auto, Edge, or Milk mode is active, motion feedback from chat should be
  queued into the active mode planner and wake the mode loop. Do not apply it as
  a one-off command that the next scripted mode step can immediately overwrite.
- Routine Freestyle selection should not randomly choose `edge-*` hold/reaction
  patterns. Those are reserved for close-signal handling or explicit edge
  feedback because their intentionally tiny ranges can look like fixed-speed or
  paused continuous motion during ordinary Freestyle.
- Hands-free voice can optionally expose a narrow LLM `mode_action` field.
  Keep it gated by saved Hands-free Voice mode plus the Advanced Flow toggle,
  and route normalized actions through the same preset-mode start/stop and
  close-signal helpers used by visible controls. If no mode action is chosen
  while a mode is active, keep relaying the transcript to the active planner.
- Typed chat can optionally expose the same narrow LLM `mode_action` field
  behind the Motion > LLM Mode Permissions toggle. Keep reviewed/manual voice
  transcript sends out of this path until they get their own explicit product
  decision.
- Visible preset-mode buttons should start modes through explicit
  `/start_*_mode` routes. Do not route sidebar mode starts through chat text
  just to reuse natural-language intent parsing.
- Keep natural language stop handling reliable. The explicit stop path should always interrupt active movement.
- Browser audio uses `/get_updates` for JSON and `/get_audio` for audio bytes. Do not recombine them into one endpoint.
- Normal chat prefers `/send_message_stream` so the initiating browser can
  render the assistant's `chat` field while Ollama is still producing JSON.
  Motion application, chat history, and TTS must still wait for final JSON
  validation. The legacy `/send_message` route remains the non-streaming
  fallback and still skips the matching queued echo on the next `/get_updates`
  poll when it returns `chat` plus `chat_queued: true`.
- `sendUserMessage()` owns the model-readiness send guard. When
  `state.chatModelBlockedMessage` is set by Ollama status, no caller should
  bypass it to POST `/send_message`; preserve draft text and surface the block
  through the shared warning status tone.
- Local model transport failures from `/send_message` return
  `status: model_error` with `chat_queued: false`. Render them as system/error
  messages in the initiating browser only; do not queue them as assistant
  dialogue, feed them into chat history, generate TTS, decrement persona-turn
  counters, or apply motion.
- Backend-failure feedback uses `setStatusMessage()` plus
  `reportSaveFailure()`: network/backend loss and HTTP errors are global error
  states, while reachable route rejections get one local warning near the
  affected control. Avoid adding ad hoc `var(--yellow)` writes for new backend
  failures.
- Browser UI code is split by behavior under `static/js/`. Keep new frontend
  work inside the relevant module instead of growing `static/app.js` again.
- Local Chatterbox sample browsing uploads/copies the selected file into `voice_samples/`; do not rely on browser-local file paths.
- `voice_samples/`, `.venv/`, `my_settings.json`, and bytecode/cache folders should stay ignored.
- Flask's default static route is disabled; static files are served explicitly from the project `static/` folder.
- Local Chatterbox WAV output is encoded with the Python `wave` module to avoid `torchaudio.save` / TorchCodec issues.
- Local Chatterbox defaults to the Turbo engine when available, reports Torch/CUDA status in the Voice tab, and splits long replies into smaller audio chunks. Do not preload/download Chatterbox weights automatically; the Voice tab has an explicit download/load button because first use may download several GB.
- Settings > Voice should not keep growing as a tuning console. Treat the current voice-input knobs as instrumentation until real microphone testing proves which defaults and recovery controls users need; routine UI should stay smaller than the backend's available ASR/browser-capture parameters.
- Local faster-whisper voice input treats `language=auto` as English for live command latency, sends a short motion-command vocabulary prompt, starts recognition at beam 1, and reruns low-confidence clips with the configured beam size. The visible beam setting is the fallback quality beam, not the first-pass beam. Low-confidence rerun failures should reject the transcript instead of sending uncertain motion commands into chat.
- NVIDIA Parakeet voice input is the preferred low-latency stack for compatible NVIDIA CUDA systems, but it must stay isolated from the main app runtime via `STROKEGPT_PARAKEET_PYTHON` / `scripts/install_parakeet.ps1` or another compatible NeMo environment. Fresh/reset settings should select Parakeet only when that runtime exists and NVIDIA tooling is detected, otherwise local faster-whisper is the default provider. Keep `nvidia/parakeet-tdt-0.6b-v3` as the default Parakeet preset and `nvidia/parakeet-tdt-1.1b` as an explicit larger preset, load both through the persistent external worker, and do not add NeMo or multi-GB model downloads to the base install or startup path. Local faster-whisper must remain the full-function CPU/non-NVIDIA voice-input fallback.
- `auto_mode_logic`, `/start_auto_mode`, and persisted active mode `auto` are
  legacy compatibility names for the scripted Legacy Auto takeover loop. Do
  not treat this path as Freestyle legacy or expand it toward adaptive
  behavior; adaptive continuation belongs in Freestyle or a successor planner.
- The Model tab reports Ollama availability and has an explicit download
  button for selected or typed Ollama models. Saved model options are editable
  in the browser list and should show known/installed model sizes plus
  Ollama-reported GPU status. Treat nonzero `/api/ps` `size_vram` as GPU use;
  only show partial CPU/GPU fallback when Ollama reports an explicit processor
  split. Deleting a built-in default should hide that option in settings
  instead of forcing it back on the next save. Do not hide large model
  downloads in startup code. The default Ollama model catalog is intentionally
  duplicated in `strokegpt/settings.py` (`DEFAULT_OLLAMA_MODEL_OPTIONS`) and
  `scripts/install_windows.ps1` (`$DefaultOllamaModelChoices`) because the
  installer must run before importing the app. Update both surfaces, plus the
  README and installer/model tests, whenever changing the default options.
- Saved settings should stay centralized in `SettingsManager.to_dict()` and `default_settings_dict()` so reset, migration, and future portability work use one schema.
- Before pushing a PR, provide a local PowerShell validation script for the
  user to run, include a final app launch step for manual browser/device
  testing, and make sure `Changelog.txt` already describes the branch.
- Once a branch has an open PR, change its changelog heading from `Unreleased`
  to the PR-numbered entry before leaving the PR ready to merge. Do not rely on
  a follow-up changelog-only PR just to convert `Unreleased` after merge.

## Known Rough Edges

- See `KNOWN_PROBLEMS.md` for current user-visible rough edges that should stay
  tracked across branches.
- UI needs browser visual testing after layout changes.
- Some strings and old easter egg content are legacy and could be cleaned up.
- README is better than before but still needs release-quality polish.
- Local Chatterbox still depends heavily on CUDA-enabled PyTorch for good latency; CPU-only Torch is expected to be slow even on fast CPUs.
- There is no full browser automation test suite.
- CI covers the lightweight Python unit tests, Python compile checks, and the
  Node-driven behavioral frontend tests under `tests/js/`, but not the full
  local Chatterbox stack.
- The original upstream repository did not include a local license file when this fork was prepared.
- Runtime state is intentionally single-operator: one trusted active browser
  session, one Flask process, one Handy controller, and one shared settings
  file. Multiple tabs share update queues and device state; keep the
  browser-local multi-tab warning as expectation-setting instead of adding
  multi-user/session architecture by accident.

## Development Commands

Run tests:

```bash
python -m unittest discover -s tests
```

This runs both the Python unit tests and, when Node 20+ is on `PATH`, the
behavioral JS suite under `tests/js/` (driven by the
`tests/test_frontend_runtime.py` wrapper). When Node is not installed, the
frontend behavioral suite skips cleanly — same skip pattern as the
Flask-gated tests in `tests/_web_support.py`.

Compile-check Python:

```bash
python -m py_compile app.py strokegpt/*.py tests/*.py
```

Run the app:

```bash
python app.py
```

## Frontend Behavioral Tests

Source-text assertions (e.g.
`tests/test_frontend_chat_statuses.py`,
`tests/test_motion_status_log_timecodes.py`,
`tests/test_connection_lost_banner.py`) read JS files as text and pin
structural invariants. They cannot drive runtime behavior. When a test
needs to call a browser ES module and inspect the DOM that the production
code mutates, write a behavioral test instead.

Behavioral tests live under `tests/js/` as `*.test.mjs` files and run
through Node's stdlib `node:test` runner. No `package.json`, no
`node_modules`, no `npm install`. The runner is invoked from
`tests/test_frontend_runtime.py`, which preloads `tests/js/_harness.mjs`
and passes each `*.test.mjs` file explicitly; do not pass the `tests/js`
directory directly because Node 24 rejects directory arguments for ESM test
resolution.

`tests/js/_harness.mjs` installs a small DOM stub on `globalThis` so
production modules can evaluate without a browser (`context.js` touches
`document.getElementById(...)` at top-level). The leading underscore
keeps it out of `node:test`'s default discovery.

Guidance for picking a test style:

- **Source-text** when you need to pin static structure: an export name,
  compatibility re-export, route/markup presence, or a module-boundary
  invariant. Avoid source-text assertions for behavior merely because they are
  cheap; substring checks for branch shape are brittle once a runtime test can
  call the production module.
- **Behavioral** when the bug is a state-machine or DOM-mutation
  regression, async handler outcome, or user-visible status change (e.g.
  "after stop, the next log entry must render at the frozen elapsed timecode,
  not 00:00"). Behavioral tests skip cleanly when Node is not available, so
  they are not a hard dependency for contributors with Python-only
  environments.
- Do not bulk-port existing source-text tests to behavioral tests. Port
  one when a future bug retests the same surface and a runtime assertion
  would have caught it.

Adding a new behavioral test:

1. Add a `tests/js/<topic>.test.mjs` file that imports from `node:test`
   and `node:assert/strict`, plus the production module under test.
2. If your test needs a DOM API the harness does not yet stub, extend
   `tests/js/_harness.mjs` by one method rather than introducing a
   heavier dep. The harness is intentionally minimal; jsdom-or-similar
   is a tier-up reach when the maintenance cost crosses the dep cost.
3. Run `python -m unittest tests.test_frontend_runtime` locally to
   confirm. CI runs Node 20 and exercises the suite on every push/PR.

## Suggested Next Tasks

Use `ROADMAP.md` as the source of truth for future work. Before starting a new
branch, remove any roadmap item that has already landed and is covered in
`Changelog.txt`.

Current Up Next targets are:

1. Freestyle Diagnostics And Mode Control Reliability: validate PR #42/#43
   diagnostics on-device, reproduce regular Freestyle stops, fix
   Legacy Auto-to-Freestyle no-action cases, and verify Pause/Resume and hotkey
   behavior on real hardware.
2. Adapter Boundary Guardrails And Translation Audit: PRs #48-#75 paid down
   most compatibility shims; preserve real schema/safety adapters and keep
   legacy bridges frozen. The `strokegpt.web` runtime-state bridge is now
   guarded by `tests/test_web_bridge_guardrails.py` and the `payloads.*`
   binding surface by `tests/test_web_payload_guardrails.py`; extend either
   allowlist only when intentionally adding new compatibility coverage. Do not
   defend the `strokegpt.web` AppState bridge indefinitely if no external
   consumers still need it.
3. Motion Vocabulary And Preset Semantics: tighten deterministic versus
   freeform semantics, keep Milk/Freestyle behavior inspectable, and let visible
   mode controls and LLM requests share guard rails.
4. Motion Style Preferences: validate and refine the visible Motion Style
   selector, decide whether planners should consume it deterministically, and
   add resettable learned preferences without burying motion behavior inside
   natural-language memory.
5. Chat Interface Refactor: modernize the chat shell, indicator strip, message
   rendering, voice toggle, TTS/chat synchronization, and control layout while
   preserving chat-driven motion behavior.

## Continuation Prompts

Continuation prompts should orient a future agent, not decide the
implementation for them. Keep them short enough that the next agent still has
to read the current code, verify the branch state, and form its own plan.

```text
Continue StrokeGPT-ReVibed from the current master. Read AGENTS.md, Changelog.txt, ROADMAP.md, and KNOWN_PROBLEMS.md, then make one focused, tested improvement.
```

```text
Continue Freestyle and mode-control reliability. Reproduce one current failure, fix the smallest confirmed cause, and preserve stop/speed safety.
```

```text
Continue the adapter-boundary audit. Confirm one bridge or wrapper is still useful or actively harmful, then document or change only that surface.
```

```text
Continue the chat/UI refactor. Make one behavior-preserving usability improvement and verify chat, TTS, and motion contracts still hold.
```

```text
Audit one motion-control path from UI or LLM input to HandyController. Patch any proven safety bypass.
```

## Agent Rules For This Repo

- Preserve user settings and secrets. Never commit `my_settings.json`.
- Keep changes focused and tested.
- Refactor aggressively when it materially improves editability or safety, but keep behavior changes intentional and tested.
- Do not introduce new external services without a settings toggle and documentation.
- Do not weaken hardware safety clamping for convenience.
- Use clear error messages in the UI instead of silent failures.
- Keep attribution to the original StrokeGPT repository.
- Keep shared agent guidance in `AGENTS.md`. `Codex.md` and `CLAUDE.md` should
  stay short compatibility pointers unless there is a strong reason to add a
  tool-specific note.
