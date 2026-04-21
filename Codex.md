# Codex Handoff

This file is for future coding agents continuing StrokeGPT-ReVibed. Keep it free of machine-specific paths, account names, private emails, credentials, and local environment details.

## Project Summary

StrokeGPT-ReVibed is a work-in-progress fork/refactor of StrokeGPT. It is a local Flask web app for controlling The Handy through natural language, Ollama model responses, deterministic motion safety logic, and optional voice output.

The current goal is not feature expansion. The current goal is stabilization, simplification, and making the app easier to safely maintain.

## Current Architecture

- `app.py`: thin launcher that imports `strokegpt.web.main`.
- `index.html`: single-page browser UI.
- `strokegpt/web.py`: Flask routes, global app state, settings wiring, UI update polling.
- `strokegpt/settings.py`: JSON-backed user/app settings.
- `strokegpt/handy.py`: The Handy API wrapper.
- `strokegpt/llm.py`: Ollama API integration and prompt construction.
- `strokegpt/motion.py`: deterministic intent matching, safety clamping, and smooth transitions.
- `strokegpt/motion_scripts.py`: longer scripted motion plans.
- `strokegpt/background_modes.py`: auto, edging, and milking background modes.
- `strokegpt/audio.py`: ElevenLabs and local Chatterbox TTS providers.
- `scripts/install_windows.ps1`: Windows install helper.
- `test_*.py`: focused regression tests.

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
- Do not let the LLM directly control raw hardware movements without passing through `MotionController`.
- Keep motion transitions smooth and clamped.
- Keep natural language matching conservative. If unsure, prefer no movement over unsafe or erratic movement.
- Browser audio uses `/get_updates` for JSON and `/get_audio` for audio bytes. Do not recombine them into one endpoint.
- Local Chatterbox sample browsing uploads/copies the selected file into `voice_samples/`; do not rely on browser-local file paths.
- `voice_samples/`, `.venv/`, `my_settings.json`, and bytecode/cache folders should stay ignored.
- Flask's default static route is disabled; static files are served explicitly from the project `static/` folder.
- Local Chatterbox WAV output is encoded with the Python `wave` module to avoid `torchaudio.save` / TorchCodec issues.
- Saved settings should stay centralized in `SettingsManager.to_dict()` and `default_settings_dict()` so reset, migration, and future portability work use one schema.

## Known Rough Edges

- `index.html` is too large and should eventually be split into maintainable assets.
- UI needs browser visual testing after layout changes.
- Some strings and old easter egg content are legacy and could be cleaned up.
- README is better than before but still needs release-quality polish.
- Local Chatterbox installation and model loading need clearer failure handling.
- There is no full browser automation test suite.
- CI covers the lightweight unit tests and Python compile checks, but not the full local Chatterbox stack.
- The original upstream repository did not include a local license file when this fork was prepared.

## Development Commands

Run tests:

```bash
python -m unittest test_audio_service.py test_motion_control.py test_configuration.py test_handy_controller.py test_motion_scripts.py test_web_static_assets.py
```

Compile-check Python:

```bash
python -m py_compile app.py strokegpt/*.py test_*.py
```

Run the app:

```bash
python app.py
```

## Suggested Next Tasks

1. Split `index.html` into separate CSS and JavaScript files without changing behavior.
2. Add Playwright or another browser test for the settings modal, chat polling, and key buttons.
3. Add a clear runtime diagnostics panel for Ollama, Handy API, ElevenLabs, and Chatterbox.
4. Improve local Chatterbox setup documentation and failure messages.
5. Add an explicit stop/safety state indicator in the UI.
6. Review the LLM prompt for reliability and reduce prompt bloat.
7. Review and clean legacy easter egg content.
8. Add release notes that clearly mark the app as experimental.

## Continuation Prompts

Use one of these prompts to continue work with a coding agent:

```text
Continue stabilizing StrokeGPT-ReVibed. First read Codex.md, README.md, and the strokegpt package. Do not add features yet. Identify the highest-risk maintainability issues and make one focused improvement with tests.
```

```text
Refactor the frontend of StrokeGPT-ReVibed. Split index.html into static CSS and JS files while preserving behavior. Verify Flask static serving still works and add/adjust tests where practical.
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
