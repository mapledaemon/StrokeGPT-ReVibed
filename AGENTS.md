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
- `strokegpt/settings.py`: JSON-backed user/app settings.
- `strokegpt/handy.py`: The Handy API wrapper.
- `strokegpt/llm.py`: Ollama API integration and prompt construction.
- `strokegpt/motion.py`: deterministic intent matching, safety clamping, and smooth transitions.
- `strokegpt/motion_anchors.py`: soft anchor-loop program parsing and
  waypoint semantics.
- `strokegpt/motion_preferences.py`: visible pattern weights and feedback
  summaries for LLM context.
- `strokegpt/motion_patterns.py`: reusable normalized motion pattern shapes
  and the JSON loader that materializes the built-in catalog at import time.
- `strokegpt/builtin_patterns.json`: pure data file holding the 34 built-in
  `MotionPattern` definitions consumed by `motion_patterns._load_builtin
  _patterns()`. Keeping the data in JSON keeps it free of Python imports.
- `strokegpt/pattern_library.py`: shareable motion pattern schema, built-in
  pattern catalog, and user pattern file registry.
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
- `scripts/install_windows.ps1`: Windows install helper.
- `tests/`: focused regression tests.

## Current Progress Snapshot

- PR #43 added broader Freestyle/mode diagnostics, active-mode elapsed timing,
  terminal-style motion sequence logging, prompt tightening, Edge/Milk start
  guards, and motion hot-path caching.
- PR #44 reorganized `ROADMAP.md` into priority tiers and merged the latest
  planning notes into roadmap and known-problems tracking.
- PR #45 added the chat interface refactor plan, explicit Pause/Resume
  planning, profile-driven splash/profile-image planning, and the known
  problem for motion status log timecodes resetting on stop.
- PR #48 split Freestyle planning and mode-decision helpers out of
  `background_modes.py` while preserving compatibility re-exports.
- PR #49 split web routes into domain blueprints and extracted payload
  builders while preserving old `strokegpt.web` route and payload names.
- PR #50 moved mutable web runtime state into `AppState` and preserved legacy
  `strokegpt.web` attribute access through a module bridge.
- PR #51 added typed contracts for long-running mode services and callbacks.
- PR #52 completed the adapter/shim audit, documented which conversion layers
  are real boundaries, and queued the compatibility-shim paydown sequence.
- PR #53 marked the PR #48-#50 compatibility shim surfaces and moved the
  direct Freestyle/mode-decision helper tests to canonical split modules.
- PR #54 shrank the `background_modes.py` compatibility surface by removing
  private split-helper re-exports while keeping the public type/constant
  compatibility exports.
- Agent guidance now lives in `AGENTS.md`, with `Codex.md` and `CLAUDE.md`
  kept as short compatibility pointers. If the current docs branch has an open
  PR, its changelog entry should use the PR number before merge.

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
- `strokegpt/motion_patterns.py` prepares pattern actions before expansion: sort/dedupe, minimum interval filtering, repeat expansion, eased interpolation, large-step limiting, and redundant point simplification. Keep that pipeline dependency-free unless a larger funscript importer is deliberately added.
- `strokegpt/motion_preferences.py` turns enabled fixed patterns and thumbs
  feedback into simple LLM-facing weights. Disabled fixed patterns should stay
  visible in settings but hidden from the LLM prompt to avoid confusing smaller
  local models.
- Motion backend selection is persisted as `motion_backend`. `continuous` is
  the recommended app-motion default: fixed patterns and anchor programs are
  phase-sampled as live position control until the next command or stop.
  Keep `hamp` selectable only as a legacy fallback unless real-device testing
  shows the continuous backend is worse for a specific recovery path.
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
- Visible preset-mode buttons should start modes through explicit
  `/start_*_mode` routes. Do not route sidebar mode starts through chat text
  just to reuse natural-language intent parsing.
- Keep natural language stop handling reliable. The explicit stop path should always interrupt active movement.
- Browser audio uses `/get_updates` for JSON and `/get_audio` for audio bytes. Do not recombine them into one endpoint.
- Chat replies from `/send_message` are rendered immediately by the initiating
  browser when the response includes `chat` plus `chat_queued: true`; the next
  `/get_updates` poll skips the matching queued echo so audio readiness can
  still be polled without duplicating the message.
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
- NVIDIA Parakeet voice input is an optional provider behind the existing Settings > Voice provider selector. Keep `nvidia/parakeet-tdt-0.6b-v3` on the optional `requirements-parakeet.txt` / NeMo path, and do not add NeMo or multi-GB model downloads to the base install or startup path.
- The Model tab reports Ollama availability and has an explicit download button for selected or typed Ollama models. Do not hide large model downloads in startup code.
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
  file. Multiple tabs share update queues and device state; document that
  assumption instead of adding multi-user/session architecture by accident.

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
`tests/test_frontend_runtime.py`, which subprocesses
`node --import ./tests/js/_harness.mjs --test ./tests/js`.

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
   Auto-to-Freestyle no-action cases, and verify Pause/Resume and hotkey
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
4. Motion Style Preferences: add visible style controls and resettable learned
   preferences without burying motion behavior inside natural-language memory.
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
