# Codex Handoff

This file is for future coding agents continuing StrokeGPT-ReVibed. Keep it free of machine-specific paths, account names, private emails, credentials, and local environment details.

## Project Summary

StrokeGPT-ReVibed is a work-in-progress fork/refactor of StrokeGPT. It is a local Flask web app for controlling The Handy through natural language, Ollama model responses, deterministic motion reliability logic, and optional voice output.

The current goal is incremental, test-backed feature work that also makes the
app easier to safely maintain. Keep each branch scoped, document user-visible
behavior, and route motion changes through the shared controller path.

## Current Architecture

- `app.py`: thin launcher that imports `strokegpt.web.main`.
- `index.html`: single-page browser UI markup.
- `static/app.css`: browser UI styles.
- `static/app.js`: browser UI entrypoint and polling orchestration.
- `static/js/`: focused browser modules for shared context, settings, chat,
  audio, device controls, motion controls, and setup.
- `strokegpt/web.py`: Flask routes, global app state, settings wiring, UI update polling.
- `strokegpt/settings.py`: JSON-backed user/app settings.
- `strokegpt/handy.py`: The Handy API wrapper.
- `strokegpt/llm.py`: Ollama API integration and prompt construction.
- `strokegpt/motion.py`: deterministic intent matching, safety clamping, and smooth transitions.
- `strokegpt/motion_patterns.py`: reusable normalized motion pattern shapes.
- `strokegpt/pattern_library.py`: shareable motion pattern schema, built-in
  pattern catalog, and user pattern file registry.
- `strokegpt/motion_scripts.py`: longer scripted motion plans.
- `strokegpt/background_modes.py`: auto, edging, and milking background modes.
- `strokegpt/audio.py`: ElevenLabs and local Chatterbox TTS providers.
- `scripts/install_windows.ps1`: Windows install helper.
- `tests/`: focused regression tests.

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

Good next targets are:

1. Motion training editor depth, especially point dragging and original versus
   edited preview.
2. Soft-anchor pattern authoring with visible trajectory controls.
3. Runtime/setup diagnostics for Ollama, Torch/CUDA, voice, port, and Handy
   state.
4. Local push-to-talk voice control MVP.

## Continuation Prompts

Use one of these prompts to continue work with a coding agent:

```text
Continue stabilizing StrokeGPT-ReVibed. First read Codex.md, README.md, and the strokegpt package. Do not add features yet. Identify the highest-risk maintainability issues and make one focused improvement with tests.
```

```text
Continue frontend maintainability work in StrokeGPT-ReVibed. The browser code is split into static/app.js plus static/js modules; keep new behavior in the relevant module. Verify Flask static serving still works and add/adjust tests where practical.
```

```text
Add CI for StrokeGPT-ReVibed. Create a GitHub Actions workflow that installs dependencies, runs unit tests, and compile-checks Python. Keep it lightweight and document any dependency limitations for Chatterbox.
```

```text
Improve runtime diagnostics in StrokeGPT-ReVibed. Add a settings or status view showing Ollama availability, selected model, Handy key presence without exposing the key, voice provider status, and local Chatterbox readiness.
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
