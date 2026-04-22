# StrokeGPT-ReVibed Roadmap

This roadmap is a working backlog, not a release commitment. Items should be
implemented in small PRs with focused tests and clear user-facing behavior.

## Current Focus

- Make local voice output reliable, visible, and low-latency.
- Add local voice control with push-to-talk before considering always-on
  microphone behavior.
- Improve motion planning so model/script output maps clearly to tip, base,
  length, range, speed, and style.
- Keep model downloads, optional dependencies, and device state visible in the
  UI.

## Voice, Story, And Interaction Loop

Voice work should stay local/offline. The first control path should be
push-to-talk with transcript preview, visible recording/transcribing states,
and clear errors.

- Add a provider-neutral speech recognition service interface.
- Add push-to-talk browser capture with `MediaRecorder`.
- Add a `/transcribe_voice` route that accepts short recorded audio clips.
- Preview transcripts before submitting them through the existing
  `/send_message` path.
- Route recognized movement requests through the deterministic motion layer.
  Do not bypass speed limits, smoothing, or stop handling.
- Keep the physical stop button and explicit stop command independent from
  voice transcription latency.
- Add local provider selection and explicit download/load controls for ASR
  models.
- Add latency diagnostics for recording, upload, transcription, LLM response,
  voice generation, and motion dispatch.
- Add story mode: a model-guided or scripted sequence that can speak lines,
  change motion styles, react to user feedback, and optionally listen for voice
  feedback between beats.
- Let story mode use the same inspected motion/style controls as normal chat so
  generated scenes cannot bypass speed limits, stop behavior, or user-visible
  preferences.

Candidate local ASR providers:

- **OpenAI Whisper, local open-source model**: baseline PyTorch ASR option with
  multilingual speech recognition, translation, and language identification.
  Source: https://github.com/openai/whisper
- **faster-whisper**: optimized Whisper runtime using CTranslate2 with CPU/GPU
  execution and quantization options. Source:
  https://github.com/SYSTRAN/faster-whisper
- **whisper.cpp**: lightweight GGML/GGUF Whisper runtime for CPU-first testing
  and possible packaged builds. Source: https://github.com/ggerganov/whisper.cpp
- **NVIDIA Parakeet TDT 0.6B v3**: promising local ASR for NVIDIA GPU systems
  with punctuation/capitalization, language detection, timestamps, and CC BY
  4.0 licensing. Source:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

## Motion, Patterns, And Visualization

- Add a small pattern browser/editor for reusable motion shapes.
- Build on the internal funscript-style action pipeline with user-visible
  controls for smoothing, repeat count, large-step limiting, and point
  simplification.
- Import user-provided `.funscript` snippets into internal movement targets
  after license/attribution and preview concerns are resolved.
- Add a pattern evaluation view that visualizes speed, depth, range, and zone
  changes before sending anything to The Handy.
- Add Handy position visualization that shows current reported position, target
  range, tip/base calibration, and recent motion path.
- Add a motion style preference selector for broad movement feel such as
  smooth, steady, teasing, pulsing, ramping, or high-variation.
- Improve LLM prompt examples around spatial requests: tip, upper, middle,
  base, full length, short stroke, half length, and smooth alternation.
- Keep range changes continuous. A single range should not become a static
  pattern unless the user explicitly asks to edge, hold, or pause.
- Add pattern transform presets inspired by funscript tooling: remap range,
  halve/double timing, smooth sparse actions, repeat a stroke shape, and apply
  subtle randomized variation with a preview before playback.
- Add command-focused tests for stop, faster, slower, tip, base, full stroke,
  edge, hold, and ambiguous motion requests.

## Preferences And Memory

- Add a visible preferences/memory panel for motion behavior the app has learned
  from user feedback.
- Show LLM-facing preference modifications in plain language before they affect
  future motion planning.
- Allow users to edit, disable, or delete individual learned motion
  preferences.
- Store motion style preferences separately from persona prompts so users can
  change model personality without losing device behavior preferences.
- Add reset controls for learned motion preferences without requiring a full
  settings reset.
- Include preference state in the model context only as concise, inspectable
  instructions rather than hidden prompt drift.

## Runtime, Setup, And Packaging

- Add a diagnostics tab for Ollama, selected model install state, local voice
  model state, Torch/CUDA status, Handy key presence, and active port.
- Add cancel/retry behavior for long model downloads where the provider supports
  it.
- Keep installation steps short and defer optional model downloads to explicit
  UI buttons.
- Add a setup verifier command that checks Python, dependencies, Ollama,
  Chatterbox availability, Torch/CUDA, and port availability.
- Consider an LLM backend abstraction so Ollama remains the default local path
  while other runtimes, such as SGLang, can be evaluated without rewriting chat
  and motion logic.
- Add startup checks that warn without blocking when optional dependencies are
  missing.
- Consider a packaged Windows launcher only after runtime and model download
  flows are stable.

## Frontend And Test Maintainability

- Split `static/app.js` into smaller modules for settings, chat, audio, device
  control, motion control, and setup.
- Add browser-level tests for the settings modal, model download controls,
  local voice controls, Handy position visualization, microphone capture, and
  story mode flow.
- Replace inline styles in `index.html` with CSS classes as the UI stabilizes.
- Continue tightening responsive layout so settings and chat remain readable in
  narrow desktop windows and mobile-sized browsers.

## Guardrails

- Push-to-talk should ship before always-on voice. Always-on voice can be
  revisited after microphone permissions, transcript review, latency, and
  mistaken command handling are reliable.
- Speed limits, smoothing, and stop handling are shared safety and reliability
  constraints. Voice control, story mode, LLM output, and pattern playback
  should all route through the same motion layer.
- Voice control should use local speech-to-text models. Hosted transcription
  would change the privacy and setup assumptions of the project.
- Large model downloads should be explicit UI actions with visible status.
  Startup, settings saves, and setup scripts should not silently download
  multi-GB model weights.
- Additional model runtimes should be optional until they show a clear app-level
  benefit over Ollama or Chatterbox for latency, quality, reliability, or setup.
