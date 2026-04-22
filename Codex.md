# Codex Handoff

This file is for future coding agents continuing StrokeGPT-ReVibed. Keep it free of machine-specific paths, account names, private emails, credentials, and local environment details.

## Project Summary

StrokeGPT-ReVibed is a work-in-progress fork/refactor of StrokeGPT. It is a local Flask web app for controlling The Handy through natural language, Ollama model responses, deterministic motion reliability logic, and optional voice output.

The current goal is not feature expansion. The current goal is stabilization, simplification, and making the app easier to safely maintain.

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
- Danger Zone

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
- Keep motion transitions smooth and clamped to user settings.
- `strokegpt/motion_patterns.py` prepares pattern actions before expansion: sort/dedupe, minimum interval filtering, repeat expansion, eased interpolation, large-step limiting, and redundant point simplification. Keep that pipeline dependency-free unless a larger funscript importer is deliberately added.
- `strokegpt/motion_anchors.py` defines soft anchor-loop programs. These let the model choose 2-6 waypoint labels while the backend compiles them into Catmull/minimum-jerk action streams with bounded target deltas. Treat anchors as soft waypoints, not hard stops.
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

## Known Rough Edges

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

1. Add Playwright or another browser test for the settings modal, chat polling, and key buttons.
2. Add a clear runtime diagnostics panel for Ollama, Handy API, ElevenLabs, and Chatterbox.
3. Improve local Chatterbox setup documentation and failure messages.
4. Add an explicit stop/safety state indicator in the UI.
5. Review the LLM prompt for reliability and reduce prompt bloat.
6. Review and clean legacy easter egg content.
7. Add release notes that clearly mark the app as experimental.
8. Continue motion training in stages using `docs/motion_training_prompts.md`.

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
