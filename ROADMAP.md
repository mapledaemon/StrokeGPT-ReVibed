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

### 1. Diagnostics And Verbosity Controls (S/M)

Why next: recent motion observability work already exposes useful data, so the
app can make runtime state more visible without changing motion behavior.

- Add user-visible verbosity levels for motion diagnostics and Ollama
  diagnostics.
- Keep the default compact, with higher motion verbosity showing the active
  motion source, pattern/name, backend, Handy timing, latency, connection state,
  and available position diagnostics.
- Let higher Ollama verbosity expose the latest local provider status and raw
  returned content where available, including model-emitted thinking text if the
  local model returns it in the response body.
- Keep debug output local and inspectable; do not treat raw diagnostics as
  hidden memory or prompt context.
- Reuse the existing `/get_status` motion observability payload before adding
  another polling path.

### 2. Feedback Governance And Pattern Library (M)

Why next: feedback currently affects model-visible pattern weights, so users
need full control over any automatic changes.

- Make feedback changes visible in Settings, including numeric weights,
  enablement, and feedback counts.
- Add clearer feedback-history indicators for fixed and trained patterns.
- Add a reset path for individual pattern feedback without clearing the whole
  motion preference set.
- Keep disabled motion patterns out of LLM-visible pattern preferences.
- Keep fixed/generated pattern files importable, exportable, and shareable from
  the larger Motion Training workspace rather than crowding compact Settings.

### 3. Motion Vocabulary And Preset Semantics (S/M)

Why next: consistent terms make both deterministic commands and LLM outputs less
surprising before deeper pattern generation work.

- Define named motion semantics for `milk`, `flick`, `freestyle`,
  deterministic speed ranges, full-range behavior, and optional LLM-controlled
  auto timing.
- Make `milk` use most or all of the configured safe stroke range unless the
  user has constrained it.
- Make `flick` a quick upward/outward move followed by a slower return.
- If freestyle or LLM-controlled auto timing is added, gate it behind explicit
  experimental controls and keep stop handling, speed limits, and smoothing
  intact.
- Add LLM-directed finite mode decisions for Edge/Milk transitions: on mode
  start and on the I'm Close signal, the model should be able to choose a
  bounded duration, intensity, and action such as hold-then-resume, pull back,
  switch to Milk, or stop, using chat history and edge count as visible
  context.
- Let preset modes speak occasionally without turning mode timers into repeated
  narration.

### 4. Motion Style Preferences (M)

Why next: this is a clean way to steer model behavior without hidden prompt
drift.

- Add a user-visible motion style selector for broad movement feel, such as
  smooth, steady, teasing, pulsing, ramping, high-variation, full-range, or
  freestyle.
- Store style preferences separately from persona prompts so users can change
  character without losing device behavior preferences.
- Include style preferences in model context as concise, inspectable numeric
  or enumerated values rather than natural-language memory.
- Let users reset learned motion feedback and style preferences without a full
  settings reset.

### 5. Soft-Anchor Pattern Authoring (M/L)

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
- Treat the anchors like pattern-matching notes: movement should slide through
  targets smoothly, may slow down to hit a target, and should not snap or stop
  just because a target was reached.

### 6. Architecture Audit And Refactor Targets (M)

Why next: the app has accumulated adapters and translation layers while motion
control stabilized; targeted cleanup should happen before larger feature work.

- Check for code that translates between multiple overlapping schemas or
  function sets and decide whether each layer should be preserved, simplified,
  or rewritten.
- Evaluate whether Python remains adequate for the app's runtime, UI, and local
  model-control constraints before considering any rewrite.
- Evaluate fuzzy-logic style controllers only as an experiment with clear
  human-test feedback, because motion feel is subjective and easy to overfit.
- Prefer practical maintainability refactors when they improve editability,
  recoverability, or safety.

### 7. Motion Training Editor Depth (M)

Why next: the training workspace already exists, so richer editing can build on
the current surface without crowding Settings.

- Add point dragging on the motion graph with snap/undo and validation before
  playback.
- Add transform history with per-step undo/redo.
- Add remaining pattern transforms: repeat a stroke shape, simplify noisy
  points, mirror timing, and apply subtle randomized variation.
- Add pattern sequencing: alternate multiple patterns in order with small
  blends between segments to avoid stutter.
- Keep compact Motion settings limited to management: enablement, weights,
  import/export, and status.

### 8. User Profile And Preference Setup (M)

Why later: identity and preference setup affects persona prompts and model
context, so it should follow runtime diagnostics and motion vocabulary cleanup.

- Add a user profile picture and custom user display name.
- Consider using the user profile control as the settings entry point in the
  upper-right area.
- Add startup and Settings selectors for user identity and interested-in
  preferences, with custom values.
- Keep identity/preferences inspectable and resettable; do not bury them inside
  natural-language memory.

### 9. Runtime And Setup Diagnostics (M)

Why later: broader setup checks should follow the first diagnostics verbosity
slice.

- Add a diagnostics tab for Ollama status, selected model install state, local
  voice model state, Torch/CUDA status, Handy key presence, active port, and
  current motion backend.
- Add optional live Handy position polling where it is useful and does not
  create excessive device/API traffic, so the sidebar position indicator can
  compare reported position against commanded targets.
- Add a setup verifier command that checks Python, dependencies, Ollama,
  Chatterbox availability, Torch/CUDA, port availability, and writable
  user-data folders.
- Add cancel/retry behavior for long model downloads where the provider
  supports it.
- Add startup checks that warn without blocking when optional dependencies are
  missing.
- Keep optional model downloads as explicit UI actions with visible status.

### 10. Reference Research Backlog (S/M)

Why later: the external projects are useful inputs, but each needs licensing,
scope, and architecture review before implementation.

- Review Handy-control references:
  https://github.com/defucilis/thehandy,
  https://github.com/Yazui1/handy-companion,
  https://github.com/KarilChan/handy-koikatsu-server, and
  https://thehandyapp.ddns.net/#/voice-commands-page.
- Review funscript and editor references:
  https://github.com/throwaway734/Simple-Funscript-Editor,
  https://github.com/michael-mueller-git/Python-Funscript-Editor,
  https://github.com/defucilis/funscript-io,
  https://github.com/mnh86/NimbleFunscriptPlayer,
  https://github.com/justfortheNSFW/Funscript-Tools,
  https://github.com/OpenFunscripter/OFS,
  https://github.com/michael-mueller-git/mtfg-rs,
  https://github.com/ilor1/HapticsEditor-v2,
  https://github.com/ncdxncdx/FunscriptDancer, and
  https://github.com/funjack/funscripting.
- Review pattern-generation and example-script references:
  https://github.com/ack00gar/FunGen-AI-Powered-Funscript-Generator/tree/main,
  https://github.com/FredTungsten/Scripts/tree/master,
  https://github.com/Aguy1724/thehandy_resources, and
  https://github.com/Amethyst-Sysadmin/Howl.
- Review device-abstraction references:
  https://github.com/ConAcademy/buttplug-mcp,
  https://github.com/ofs69/syncopathy, and
  https://github.com/buttplugio/awesome-buttplug.

### 11. Local Voice Control MVP (L)

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

### 12. Story Mode (L/XL)

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

### 13. Optional Runtime And Packaging Work (XL)

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
- Repeated thumbs-down auto-disable must remain opt-in, visible, and reversible;
  feedback should not silently hide motion patterns from the user.
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
