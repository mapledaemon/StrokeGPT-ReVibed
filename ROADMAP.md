# StrokeGPT-ReVibed Roadmap

This roadmap is a working backlog, not a release commitment. Items should be
implemented in small PRs with focused tests and clear user-facing behavior.

## Current Priority: Voice Control

Voice control is the largest near-term feature because it changes the main
input loop, latency profile, and error handling. Only local/offline ASR models
should be considered for this project. The first version should be
push-to-talk, visible in the UI, and routed through the existing command and
motion-control paths.

### Voice Control Goals

- Add a microphone button with obvious recording, transcribing, and error
  states.
- Transcribe speech into text, preview the transcript, then submit it through
  the same `/send_message` path used by typed chat.
- Route recognized movement requests through the existing deterministic motion
  layer. Do not bypass speed limits, smoothing, or stop handling.
- Keep the physical stop button and explicit stop command independent from
  voice transcription latency.
- Support local provider selection so users can choose between installed ASR
  runtimes.
- Make model downloads and dependencies explicit before first use.

### Candidate Local ASR Providers

- **OpenAI Whisper, local open-source model**: baseline local ASR option with
  multilingual speech recognition, translation, and language identification.
  The reference implementation is PyTorch-based and can run locally after the
  selected model weights are downloaded.
  Source: https://github.com/openai/whisper
- **faster-whisper**: optimized local Whisper runtime using CTranslate2. It is
  worth benchmarking first on Windows/NVIDIA because it supports CPU/GPU
  execution and quantization while keeping the model family familiar.
  Source: https://github.com/SYSTRAN/faster-whisper
- **whisper.cpp**: lightweight local Whisper runtime and GGML/GGUF model path.
  This is useful for CPU-first testing, smaller quantized models, and possible
  future packaged builds.
  Source: https://github.com/ggerganov/whisper.cpp
- **NVIDIA Parakeet TDT 0.6B v3**: promising local ASR for NVIDIA GPU systems.
  The NVIDIA model card describes a 600M-parameter multilingual ASR model with
  automatic language detection, punctuation/capitalization, word and segment
  timestamps, 25 European languages, and CC BY 4.0 licensing.
  Source: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

### Suggested Voice Control Milestones

1. Add a provider-neutral speech recognition service interface.
2. Add push-to-talk browser capture with `MediaRecorder`.
3. Add a `/transcribe_voice` route that accepts short recorded audio clips.
4. Add one local Whisper-family provider behind explicit model download/load
   controls.
5. Benchmark Whisper, faster-whisper, whisper.cpp, and Parakeet on this
   machine before choosing defaults.
6. Add transcript preview and a send/cancel affordance before the transcript is
   submitted to chat.
7. Add command-focused tests for "stop", "faster", "slower", "tip", "base",
   "full stroke", "edge", and ambiguous transcripts.
8. Add latency diagnostics for recording, upload, transcription, LLM response,
   and motion dispatch.

### Voice Control Risks

- False positives on motion commands are more disruptive than ordinary chat
  typos. Start with push-to-talk and transcript preview.
- Always-on microphone behavior should wait until push-to-talk is stable.
- Local ASR can introduce large model downloads and GPU-specific setup issues.
  Keep downloads explicit and visible.
- Different local ASR runtimes have different hardware assumptions. The UI
  should clearly show which provider is active, which model is loaded, and
  whether inference is using CPU, CUDA, or another accelerator.

## Motion And Pattern Work

- Add a small pattern browser/editor for reusable motion shapes.
- Import and normalize useful funscript-style patterns into internal movement
  targets.
- Add a pattern evaluation view that visualizes speed, depth, range, and zone
  changes before sending anything to The Handy.
- Add Handy position visualization that shows the current reported position,
  target range, tip/base calibration, and recent motion path. This should make
  spatial behavior inspectable before and during sessions.
- Add a user-facing motion style preference selector for broad movement feel
  such as smooth, steady, teasing, pulsing, ramping, or high-variation. This
  should influence pattern selection and LLM prompt context without bypassing
  speed limits or stop behavior.
- Improve LLM prompt examples around spatial requests: tip, upper, middle,
  base, full length, short stroke, half length, and smooth alternation.
- Keep range changes continuous. A single range should not become a static
  pattern that the app sticks to unless the user explicitly asks to edge, hold,
  or pause.

## User Preferences And Memory

- Add a visible preferences/memory panel for motion behavior the app has learned
  from user feedback.
- Show LLM-facing preference modifications in plain language before they affect
  future motion planning.
- Allow users to edit, disable, or delete individual learned motion preferences.
- Store motion style preferences separately from persona prompts so users can
  change model personality without losing device behavior preferences.
- Add reset controls for learned motion preferences without requiring a full
  settings reset.
- Include preference state in the model context only as concise, inspectable
  instructions rather than hidden prompt drift.

## Runtime And Model Management

- Add a diagnostics tab for Ollama, selected model install state, local voice
  model state, Torch/CUDA status, Handy key presence, and active port.
- Add cancel/retry behavior for long model downloads where the provider supports
  it.
- Consider an LLM backend abstraction so Ollama remains the default local path
  while other runtimes, such as SGLang, can be evaluated without rewriting chat
  and motion logic.
- Add startup checks that warn without blocking when optional dependencies are
  missing.

## Frontend Maintainability

- Split `static/app.js` into smaller modules for settings, chat, audio, device
  control, motion control, and setup.
- Add browser-level tests for the settings modal, model download controls,
  local voice controls, Handy position visualization, and microphone capture
  flow.
- Replace inline styles in `index.html` with CSS classes as the UI stabilizes.
- Continue tightening responsive layout so settings and chat remain readable in
  narrow desktop windows and mobile-sized browsers.

## Packaging And Setup

- Keep installation steps short and defer optional model downloads to explicit
  UI buttons.
- Add a setup verifier command that checks Python, dependencies, Ollama,
  Chatterbox availability, Torch/CUDA, and port availability.
- Consider a packaged Windows launcher only after the runtime and model download
  flows are stable.

## Non-Goals For Now

- Do not add always-on voice control before push-to-talk is reliable.
- Do not allow voice, LLM, or pattern code to bypass configured speed limits or
  stop handling.
- Do not use hosted speech-to-text APIs for voice control in this project.
- Do not hide multi-GB model downloads in startup, setup scripts, or settings
  saves.
- Do not introduce another mandatory model runtime until it has a clear benefit
  over Ollama for this app.
