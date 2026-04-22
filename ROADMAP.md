# StrokeGPT-ReVibed Roadmap

This roadmap is a working backlog, not a release commitment. Completed work
belongs in `Changelog.txt`; this file should stay focused on future work. Items
are ordered by best next target, balancing user value, feasibility, complexity,
and risk.

Complexity key:

- **S**: narrow change, low risk.
- **M**: moderate UI/backend work with focused tests.
- **L**: multiple subsystems or meaningful device testing.
- **XL**: broad workflow or runtime change; split into staged PRs.

## Best Next Targets

### 1. Motion Observability And Redirect Diagnostics (S/M)

Why next: it will make device behavior easier to understand before adding more
generation logic.

- Add Handy position visualization showing reported position, target range,
  tip/base calibration, active backend, and recent motion path.
- Add a compact live motion inspector for current speed, depth, range, pattern,
  backend, and whether the command came from deterministic chat, LLM JSON,
  repair, training preview, or background mode.
- Add user-facing diagnostics for redirect behavior: last commanded speed,
  last slide bounds, and whether a speed-reducing redirect lowered velocity
  before changing range.
- Add focused tests for visualization payloads and command-source reporting.

### 2. Motion Training Editor Depth (M)

Why next: the training workspace already exists, so richer editing can build on
the current surface without crowding Settings.

- Add point dragging on the motion graph with snap/undo and validation before
  playback.
- Add side-by-side original versus edited previews before rating or saving.
- Add transform history with per-step undo/redo.
- Add remaining pattern transforms: repeat a stroke shape, simplify noisy
  points, mirror timing, and apply subtle randomized variation.
- Add pattern sequencing: alternate multiple patterns in order with small
  blends between segments to avoid stutter.
- Keep compact Motion settings limited to management: enablement, weights,
  import/export, and status.

### 3. Soft-Anchor Pattern Authoring (M/L)

Why next: it addresses the gap between fixed scripts and raw LLM numeric
control while staying inspectable.

- Add a soft-anchor editor where users can arrange 2-6 targets such as tip,
  upper, shaft/middle, lower, and base.
- Preview Catmull-Rom and minimum-jerk trajectory output before sending it to
  the device.
- Expose tempo, softness, large-step limiting, and repeat count as visible
  controls.
- Let the LLM choose from saved soft-anchor patterns by id and weight instead
  of inventing hidden free-form behavior.
- Keep anchors as soft waypoints, not hard stops.

### 4. Motion Style Preferences (M)

Why next: this is a clean way to steer model behavior without hidden prompt
drift.

- Add a user-visible motion style selector for broad movement feel, such as
  smooth, steady, teasing, pulsing, ramping, high-variation, or full-range.
- Store style preferences separately from persona prompts so users can change
  character without losing device behavior preferences.
- Include style preferences in model context as concise, inspectable numeric
  or enumerated values rather than natural-language memory.
- Let users reset learned motion feedback and style preferences without a full
  settings reset.

### 5. Runtime And Setup Diagnostics (M)

Why next: it reduces support friction and makes model/device state explicit.

- Add a diagnostics tab for Ollama status, selected model install state, local
  voice model state, Torch/CUDA status, Handy key presence, active port, and
  current motion backend.
- Add a setup verifier command that checks Python, dependencies, Ollama,
  Chatterbox availability, Torch/CUDA, port availability, and writable
  user-data folders.
- Add cancel/retry behavior for long model downloads where the provider
  supports it.
- Add startup checks that warn without blocking when optional dependencies are
  missing.
- Keep optional model downloads as explicit UI actions with visible status.

### 6. Local Voice Control MVP (L)

Why next: voice control is the largest user-facing feature, but it should ship
as push-to-talk before always-on listening.

- Add a provider-neutral speech recognition service interface.
- Add push-to-talk browser capture with `MediaRecorder`.
- Add a `/transcribe_voice` route that accepts short recorded audio clips.
- Preview transcripts before submitting them through the existing
  `/send_message` path.
- Route recognized movement requests through the deterministic motion layer.
  Do not bypass speed limits, smoothing, stop handling, or user-visible
  preferences.
- Keep the physical stop button and explicit stop command independent from
  recording, upload, transcription, LLM response, and TTS latency.
- Add latency diagnostics for recording, upload, transcription, LLM response,
  voice generation, and motion dispatch.

Candidate local ASR providers:

- **faster-whisper**: optimized Whisper runtime using CTranslate2 with CPU/GPU
  execution and quantization options. Source:
  https://github.com/SYSTRAN/faster-whisper
- **whisper.cpp**: lightweight GGML/GGUF Whisper runtime for CPU-first testing
  and possible packaged builds. Source: https://github.com/ggerganov/whisper.cpp
- **OpenAI Whisper, local open-source model**: baseline PyTorch ASR option with
  multilingual speech recognition, translation, and language identification.
  Source: https://github.com/openai/whisper
- **NVIDIA Parakeet TDT 0.6B v3**: promising local ASR for NVIDIA GPU systems
  with punctuation/capitalization, language detection, timestamps, and CC BY
  4.0 licensing. Source:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

### 7. Story Mode (L/XL)

Why later: it depends on reliable voice, motion preferences, and sequence
editing.

- Add scripted and model-guided scene sequences that can speak lines, change
  motion styles, react to user feedback, and optionally listen for voice
  feedback between beats.
- Let story mode use the same inspected motion/style controls as normal chat.
- Allow story mode to select saved patterns and soft-anchor programs rather
  than inventing opaque motion.
- Add interruption and recovery states so stop, pause, and resume remain
  predictable during longer scenes.

### 8. Optional Runtime And Packaging Work (XL)

Why later: these should follow device and voice reliability work unless a
runtime shows a clear app-level benefit.

- Consider an LLM backend abstraction so Ollama remains the default local path
  while other runtimes, such as SGLang, can be evaluated without rewriting chat
  and motion logic.
- Compare optional local runtimes on actual app metrics: first-token latency,
  JSON reliability, model setup friction, GPU memory behavior, and recovery
  after failed requests.
- Consider a packaged Windows launcher only after runtime diagnostics, model
  downloads, voice setup, and device state handling are stable.

## Guardrails

- Speed limits, smoothing, stop handling, and user-visible preferences are
  shared reliability constraints. Voice control, story mode, LLM output, and
  pattern playback should all route through the same motion layer.
- HAMP continuous motion should remain the recommended default until flexible
  position/script playback has more real-device validation for smoothness,
  pattern fidelity, latency, and recovery behavior.
- Voice control should use local speech-to-text models. Hosted transcription
  would change the privacy and setup assumptions of the project.
- Always-on voice should wait until push-to-talk, transcript preview, latency,
  and mistaken command handling are reliable.
- Large model downloads should be explicit UI actions with visible progress.
  Startup, settings saves, and setup scripts should not silently download
  multi-GB model weights.
