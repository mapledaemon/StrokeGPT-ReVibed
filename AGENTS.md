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
  audio, device controls, motion controls, and setup.
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
- `strokegpt/motion_patterns.py`: reusable normalized motion pattern shapes.
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

- Open Settings
- Control Actions
- Preset Modes
- Standalone emergency stop

The unified settings popup has tabs:

- Persona
- Model
- Voice
- Device
- Motion
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
- Motion backend selection is persisted as `motion_backend`. Keep `hamp` as
  the recommended default for app motion and label `position` flexible
  position/script playback as experimental until more device testing lands.
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
- Keep natural language stop handling reliable. The explicit stop path should always interrupt active movement.
- Browser audio uses `/get_updates` for JSON and `/get_audio` for audio bytes. Do not recombine them into one endpoint.
- Browser UI code is split by behavior under `static/js/`. Keep new frontend
  work inside the relevant module instead of growing `static/app.js` again.
- Local Chatterbox sample browsing uploads/copies the selected file into `voice_samples/`; do not rely on browser-local file paths.
- `voice_samples/`, `.venv/`, `my_settings.json`, and bytecode/cache folders should stay ignored.
- Flask's default static route is disabled; static files are served explicitly from the project `static/` folder.
- Local Chatterbox WAV output is encoded with the Python `wave` module to avoid `torchaudio.save` / TorchCodec issues.
- Local Chatterbox defaults to the Turbo engine when available, reports Torch/CUDA status in the Voice tab, and splits long replies into smaller audio chunks. Do not preload/download Chatterbox weights automatically; the Voice tab has an explicit download/load button because first use may download several GB.
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
- CI covers the lightweight unit tests and Python compile checks, but not the full local Chatterbox stack.
- The original upstream repository did not include a local license file when this fork was prepared.

## Development Commands

Run tests:

```bash
python -m unittest discover -s tests
```

Compile-check Python:

```bash
python -m py_compile app.py strokegpt/*.py tests/*.py
```

Run the app:

```bash
python app.py
```

## Suggested Next Tasks

Use `ROADMAP.md` as the source of truth for future work. Before starting a new
branch, remove any roadmap item that has already landed and is covered in
`Changelog.txt`.

Current Up Next targets are:

1. Freestyle Diagnostics And Mode Control Reliability: validate PR #42/#43
   diagnostics on-device, fix remaining stop/log/timer regressions, and verify
   the Pause/Resume and hotkey behavior on real hardware.
2. Compatibility Shim Paydown And Adapter Boundary Cleanup: keep the completed
   code reorganization stable by marking or retiring PR #48-#50 compatibility
   shims, migrating callers to canonical modules, and preserving real
   conversion boundaries for motion safety, pattern compilation, settings
   persistence, and browser payloads.
3. Motion Vocabulary And Preset Semantics: tighten deterministic versus
   freeform semantics, keep Milk/Freestyle behavior inspectable, and let visible
   mode controls and LLM requests share guard rails.
4. Persona Naming And Prompt Audit: check whether proper-noun persona handles
   such as `GLaDOS` should reach the local model or be hidden behind neutral
   internal labels.
5. Motion Style Preferences: add visible style controls and resettable learned
   preferences without burying motion behavior inside natural-language memory.
6. Chat Interface Refactor: modernize the chat shell, indicator strip, message
   rendering, and control layout while preserving chat-driven motion behavior.

## Continuation Prompts

Use one of these prompts to continue work with a coding agent:

```text
Continue stabilizing StrokeGPT-ReVibed. First read AGENTS.md, README.md, Changelog.txt, ROADMAP.md, KNOWN_PROBLEMS.md, and the strokegpt package. Do not assume prior chat context. Identify the highest-risk current roadmap item and make one focused improvement with tests.
```

```text
Continue the Freestyle Diagnostics And Mode Control Reliability stage in StrokeGPT-ReVibed. First read AGENTS.md, Changelog.txt, ROADMAP.md, KNOWN_PROBLEMS.md, static/js/motion-control.js, strokegpt/background_modes.py, and strokegpt/motion.py. Preserve HAMP as the default backend, keep stop behavior and speed limits non-negotiable, and add focused tests before preparing a PR.
```

```text
Continue the Compatibility Shim Paydown And Adapter Boundary Cleanup stage in StrokeGPT-ReVibed. First read AGENTS.md, ROADMAP.md, Changelog.txt, strokegpt/background_modes.py, strokegpt/freestyle.py, strokegpt/mode_decisions.py, strokegpt/web.py, and strokegpt/payloads.py. Mark or retire one compatibility shim surface at a time, migrate callers to canonical modules where practical, preserve behavior, and update Changelog.txt before preparing a PR.
```

```text
Continue the Chat Interface Refactor planning in StrokeGPT-ReVibed. First read AGENTS.md, ROADMAP.md, KNOWN_PROBLEMS.md, index.html, static/app.css, static/app.js, and static/js/chat.js. Preserve message safety, TTS/chat synchronization, stop handling, and motion controls while improving the chat shell incrementally.
```

```text
Audit the motion-control path in StrokeGPT-ReVibed. Confirm all hardware movement goes through MotionController or HandyController safety methods. Add tests for any uncovered unsafe paths.
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
