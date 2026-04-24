# StrokeGPT-ReVibed Roadmap

This roadmap is a working backlog, not a release commitment. Completed work
belongs in `Changelog.txt`; this file should stay focused on future work.
Items are grouped into tiers by priority and feasibility, then ranked inside
each tier by best next target. Tier names are chosen so the difference
between *what is on deck right now* and *what waits for an upstream change* is
obvious at a glance.

Tier scheme:

- **Up Next** - actively scoped or ready to pick up; little blocking design
  work; mostly S/M complexity; expected to land in the next handful of PRs.
- **Queued** - design clear, scope contained, but waits for an Up Next item
  (or on-device verification) before it should be started; mostly M.
- **Backlog** - bigger feature programs, multi-PR cleanups, or work that
  depends on reference research and external libraries; M/L.
- **Long-Horizon** - replatform, runtime swap, or packaging-level work that
  should not be considered until the desktop app is reliable; L/XL.

Complexity key (orthogonal to tier):

- **S**: narrow change, low risk.
- **M**: moderate UI/backend work with focused tests.
- **L**: multiple subsystems or meaningful device testing.
- **XL**: broad workflow or runtime change; split into staged PRs.

## Up Next

### 1. Freestyle Diagnostics And Mode Control Reliability (S/M)

Why next: the diagnostics surface from PR #43 is now in place but the
on-device Freestyle stop has not been confirmed fixed, and the surrounding
mode controls still have rough edges that block daily use.

- Use the PR #42 trace fields and the expanded status/debug diagnostics UI
  during manual Freestyle testing to identify whether stops are planner-side,
  API-side, or Handy position-mode behavior.
- Validate the active-mode elapsed timer and detached vertical
  recent-sequence log across Auto, Edge, Milk, Freestyle, and mode
  transitions, and tune the displayed timing/label detail if on-device
  testing shows noisy or misleading output.
- Review whether the current Milking/Freestyle start-decision `stop` guard
  should remain in the final mode framework. The framework should eventually
  be smart enough to allow deliberate stops at any event without losing the
  continuous-mode contract; the guard is currently a small-model safety net.
- Investigate longer or adaptive chain lengths for all scripted/experimental
  modes after Freestyle trace data shows whether command starvation is still
  happening at batch boundaries. Chain length was raised for Freestyle in
  PR #41 but probably not enough.
- Split the active-mode timer indicator and the mode/label indicator into
  fixed-size elements so neither can resize the other when text length
  changes.

### 2. Compatibility Shim Paydown And Adapter Boundary Cleanup (S/M)

Why next: PRs #48-#51 finished the structural code reorganization by splitting
the biggest modules, moving web runtime state into `AppState`, and typing the
mode service/callback boundary. The adapter audit found that most conversion
layers are real safety or schema boundaries, but several compatibility shims
were deliberately left in place so the mechanical splits stayed behavior
preserving. Those shims should now be marked or paid down before new code
starts treating them as permanent API.

Adapter audit findings:

- Preserve the real safety boundaries:
  `MotionSanitizer.from_llm_move()` parses LLM JSON into `MotionTarget`,
  `MotionController.apply_generated_target()` chooses HAMP versus
  position-frame playback while preserving smoothing/stop behavior, and
  `HandyController.move()` / `move_to_depth()` translate relative app targets
  into calibrated device commands with user speed/depth limits.
- Preserve the pattern/compiler boundaries:
  `motion_patterns.normalize_actions()`, `expand_motion_pattern()`, and
  `expand_anchor_program()` turn pattern/action/anchor schemas into
  `PatternFrame` sequences with blend, turn, step-limit, and tempo rules.
  `motion_anchors.coerce_anchor_program*()` remains the anchor schema boundary.
- Preserve the persistence and UI-payload boundaries:
  `SettingsManager.default_settings_dict()`, `apply_dict()`, and `to_dict()`
  own settings migration/reset/save behavior, while `payloads.py` owns the
  browser-facing settings, Ollama, and motion-pattern payload shapes.
- Treat PR #48 `background_modes` re-exports from `freestyle.py` and
  `mode_decisions.py` as compatibility shims. Migrate tests and internal
  callers to canonical modules where practical; otherwise mark the re-export
  block "Compatibility shim - do not extend."
- Treat PR #49 `strokegpt.web` blueprint route aliases and payload wrapper
  names as compatibility shims. New code should import route handlers from
  `strokegpt.blueprints.*` and payload builders from `strokegpt.payloads`.
- Treat PR #50 `strokegpt.web` module-level `AppState` attribute bridge as a
  compatibility shim for older tests/callers. New code should use
  `web.app_state` or an explicit dependency, not add new bridged attributes.
- Simplify the Freestyle candidate adapter once the shim pass starts:
  `web._freestyle_candidate_patterns()` now returns a typed
  `FreestyleCandidate`, but `freestyle._candidate_*()` still accepts both dicts
  and record-like objects. Pick one canonical candidate shape and remove the
  historical duck-typing after tests are migrated.
- Track `web._motion_pattern_summary()` as an open boundary decision before
  changing Freestyle candidate handling. It merges
  `PatternRecord.to_summary_dict()` with catalog weight/enabled fields; decide
  whether that is a real route payload boundary or should be merged into the
  canonical catalog summary shape.

Concrete follow-up PRs:

- Migrate web payload tests to `strokegpt.payloads` and route registration
  tests to the blueprint modules before removing or freezing old `web.*`
  payload/route aliases.
- Split web tests out of `tests/test_web_static_assets.py` alongside the
  production seams they cover so payload, blueprint, runtime-state, and static
  asset tests stop sharing one catch-all file.
- Normalize Freestyle candidate handling around the `FreestyleCandidate`
  contract and remove `_candidate_*` duck typing that only exists for
  historical shapes. Must follow the canonical helper-test migration and the
  `web._motion_pattern_summary()` boundary decision.

### 3. Frontend Motion-Control Module Split (M)

Why next: `static/js/motion-control.js` is now the largest single file in the
repo and it sits directly next to future chat-shell, diagnostics, motion
training, and pattern-management UI work. Split it before those surfaces grow
around one monolithic frontend module.

- Extract one focused module at a time under `static/js/motion/`, starting with
  low-risk seams such as the motion sequence log, pause/resume and hotkey
  wiring, motion-pattern list controls, motion settings/feedback controls, and
  motion-training editor utilities.
- Keep `static/js/motion-control.js` as the top-level wiring boundary until
  callers are migrated. Use small compatibility exports where needed, and add
  regression tests for each extracted browser module seam.
- Preserve existing route URLs, payload shapes, keyboard shortcuts,
  Pause/Resume/Stop behavior, feedback controls, motion training preview/start
  behavior, and disabled-pattern filtering.
- Avoid broad UI restyling in the extraction PRs. The goal is to make later
  Chat Interface Refactor and Motion Training Editor Depth work safer.

### 4. Built-In Pattern Data Extraction (S/M)

Why next: a large share of `strokegpt/motion_patterns.py` is static built-in
pattern data. Moving that data out of the normalization/expansion logic is a
behavior-preserving readability win and is separate from the deferred lazy-load
optimization.

- Move the hardcoded built-in `PATTERNS` definitions into a dedicated data
  source such as `strokegpt/patterns/builtin.json` or a small Python data
  module organized by pattern family.
- Keep eager loading for now. Do not combine this extraction with the parked
  pattern-library lazy-load optimization or prepared-action cache changes.
- Preserve pattern IDs, names, enabled defaults, action timestamps, positions,
  interpolation settings, LLM visibility, and user-visible weight semantics.
- Add a contract test that the built-in catalog produced from the extracted
  data matches the current ids and representative action sequences.

### 5. Motion Vocabulary And Preset Semantics (S/M)

Why next: consistent terms make both deterministic commands and LLM outputs
less surprising before deeper pattern generation work, and several of these
items are short follow-ups to PR #38 / PR #41 / PR #43.

- Define remaining named motion semantics for deterministic speed ranges,
  full-range behavior, and optional LLM-controlled auto timing.
- Confirm Milk Me and natural-language milk requests actually use most or
  all of the safe calibrated range unless the user explicitly asks for
  short/tight motion. PR #38 added milk vocabulary; the on-device check
  that this still holds across HAMP and the experimental backend is open.
- Add a Freestyle/freeform toggle (checkbox or dropdown in settings) that
  switches between deterministic speed/range semantics and a more
  freeform/freestyle interpretation, so users can choose how tightly the
  app maps language to fixed ranges. The freeform position should clearly
  indicate it removes some safety mappings and stays subject to the global
  user max-speed cap.
- Bias generated motion to vary speed and depth more (within the safety
  envelope) instead of vibration-style high-frequency motion in a tight
  range, which feels unnatural. Variation should come from changing
  targets, not from rapid oscillation around one target.
- Add user-facing Freestyle planner controls and diagnostics for fuzzy
  inputs such as visible weights, feedback, recent chat, and current motion
  context.
- Keep Freestyle off HAMP/current scripted Auto arcs; it should continue
  using the experimental pattern/script playback path until a later motion
  backend replaces the current default.
- Allow users to replace or import Edge/Milk mode scripts through the same
  visible pattern-management surface used for fixed and trained patterns.
- Allow the LLM to request visible modes such as Freestyle, Edge Me, and
  Milk Me through the same guard rails as the UI buttons, making sure chat
  edge-blocking settings also affect model-requested mode changes.
- Let preset modes speak occasionally without turning mode timers into
  repeated narration.

### 6. Persona Naming And Prompt Audit (S)

Why next: the persona name `GLaDOS` is referenced in the prompt-tightening
work from PR #43, and it is not clear whether the local model sees it
literally and copies its style. This is a small targeted audit before the
larger Motion Style Preferences work.

- Locate every place the persona name `GLaDOS` (or any other proper noun
  persona handle) is interpolated into prompts, settings, or memory.
- Decide whether the literal name should reach the model. If yes, document
  why; if no, replace it with a neutral placeholder and verify the persona
  voice continues to come from the prompt body, not from the model's
  trained associations with the name.
- Sweep chat, repair, naming, and memory-consolidation prompts for any
  other proper-noun handles that may be steering local-model behavior.

### 7. Motion Style Preferences (M)

Why next: this is a clean way to steer model behavior without hidden prompt
drift, and it slots in after the persona audit so style preferences and
persona prompts stay separable.

- Add a user-visible motion style selector for broad movement feel, such as
  smooth, steady, teasing, pulsing, ramping, high-variation, full-range, or
  freestyle.
- Store style preferences separately from persona prompts so users can
  change character without losing device behavior preferences.
- Include style preferences in model context as concise, inspectable
  numeric or enumerated values rather than natural-language memory.
- Let users reset learned motion feedback and style preferences without a
  full settings reset.

### 8. Chat Interface Refactor (M)

Why next: the chat panel and its surrounding toolbars/indicators are
largely unchanged from the pre-fork code, and the recent diagnostics work
(PR #43) keeps adding compact indicators around a chat surface that was
not designed for them. Do the `static/js/motion-control.js` split first so
chat-shell work does not have to share a 1700-line motion frontend module.

- Audit the existing chat panel against modern local-LLM front-ends
  (Ollama UI, Open WebUI, LM Studio, etc.) for layout, message styling,
  scroll/auto-scroll behavior, streaming render, and accessible focus
  handling. Use them as references for ergonomics, not as templates to
  copy whole-cloth.
- Redo the chat toolbar and indicator strip so the speed/depth meter,
  motion sequence log, feedback buttons, mode/timer indicators, and
  Pause/Resume/Stop controls share one consistent layout grammar instead
  of being individually retrofitted around the legacy chat panel.
- Make message rendering robust to streamed and non-streamed Ollama
  responses, so the chat-emit path stays in lockstep with the TTS-enqueue
  path (see KNOWN_PROBLEMS "Local LLM Chat Text Sometimes Missing While
  Voice Plays").
- Keep markdown/code rendering opt-in and predictable; do not regress
  copy/paste, scrollback, or screen-reader behavior while restyling.
- Preserve the existing chat-driven motion contract (chat-driven
  Pause/Resume, chat edge-blocking, motion-target language) while moving
  the visible surface into the new layout.

## Queued

### 9. Soft-Anchor Pattern Authoring (M/L)

Why later: it addresses the gap between fixed scripts and raw LLM numeric
control while staying inspectable, but should follow the code reorg so it
can land cleanly inside the new motion blueprints/modules.

- Add a soft-anchor editor where users can arrange 2-6 targets such as
  tip, upper, shaft/middle, lower, and base.
- Preview Catmull-Rom and minimum-jerk trajectory output before sending
  it to the device.
- Expose tempo, softness, large-step limiting, and repeat count as
  visible controls.
- Let the LLM choose from saved soft-anchor patterns by id and weight
  instead of inventing hidden free-form behavior.
- Later, allow bounded on-the-fly pattern generation only after graph
  preview, validation, smoothing, and stop/speed/range safeguards are
  reliable.
- Keep anchors as soft waypoints, not hard stops.
- Treat the anchors like pattern-matching notes: movement should slide
  through targets smoothly, may slow down to hit a target, and should not
  snap or stop just because a target was reached.

### 10. Architecture Audit And Strategic Refactor (M)

Why later: the immediate code reorg in Up Next #2, the frontend split in Up
Next #3, and the chat shell refactor in Up Next #8 cover the obvious splits.
This entry is for the
deeper, design-level audits that need a clean tree first.

- Before changing the default motion backend, audit the flexible
  position/script path against chat control, Freestyle, motion training,
  Edge/Milk mode scripts, stop behavior, and real-device smoothness.
- When the new schema becomes the only motion backend, preserve the
  current shared backend guard rails: pass-through final targets for
  continuous planners, user-speed-relative XAVA velocity caps, depth-jump
  splitting, and turn-apex smoothing for all position/script callers.
- Evaluate whether Python remains adequate for the app's runtime, UI, and
  local model-control constraints before considering any rewrite.
- Evaluate fuzzy-logic style controllers only as an experiment with clear
  human-test feedback, because motion feel is subjective and easy to
  overfit. Likely too noisy without large-scale human input; treat as a
  research spike, not a roadmap commitment.
- Split `strokegpt/motion.py` into intent matching, LLM motion sanitization,
  and motion controller modules using the same compatibility-bridge pattern as
  the `background_modes.py` split. Keep `MotionController` safety behavior,
  stop semantics, smoothing, and user speed/depth clamping unchanged.
- Split `strokegpt/audio.py` provider concerns only after higher-ROI motion and
  web refactors land. A future extraction should keep the public `AudioService`
  entry point stable while moving ElevenLabs and Chatterbox provider details
  into focused modules.
- Pattern-library lazy-load parking lot: defer lazy-loading the JSON pattern
  library and prepared-action cache until pattern count grows enough to justify
  it; the cache exists, but eager loading is still simpler and cheap at the
  current catalog size.
- Prefer practical maintainability refactors when they improve
  editability, recoverability, or safety.

### 11. Motion Training Editor Depth (M)

Why later: the training workspace already exists, so richer editing can
build on the current surface without crowding Settings.

- Add point dragging on the motion graph with snap/undo and validation
  before playback.
- Add transform history with per-step undo/redo.
- Add remaining pattern transforms: repeat a stroke shape, simplify noisy
  points, mirror timing, and apply subtle randomized variation.
- Add a funscript import workflow that graphs the source actions before
  saving and lets users cut the timeline down to the useful section so
  imported patterns do not keep unwanted video-synchronization lead-in,
  dead space, or unrelated motion.
- Add pattern sequencing: alternate multiple patterns in order with small
  blends between segments to avoid stutter.
- Keep compact Motion settings limited to management: enablement, weights,
  import/export, and status.

### 12. User Profile And Preference Setup (M)

Why later: identity and preference setup affects persona prompts and model
context, so it should follow runtime diagnostics, motion vocabulary
cleanup, and the persona naming audit.

- Add a user profile picture and custom user display name.
- Use the user profile control as the settings entry point in the
  upper-right area.
- Drive the splash screen and the default profile image from the profile
  wizard selections (identity, interested-in, custom values) so the first
  visible app surface reflects the user's chosen preferences instead of a
  generic default. Keep a neutral fallback for users who skip the wizard
  and a Settings control to change the splash/profile image after setup.
- Add startup and Settings selectors for user identity and interested-in
  preferences, with custom values.
- Include initial identity options for Cis Male, Cis Female, Trans Man,
  Trans Woman, Gender fluid, No gender, and custom values. Include
  interested-in options for Cis Male, Cis Female, Trans Man, Trans Woman,
  Gender neutral, and custom values.
- Add an About window reachable from the profile/settings area, preserving
  the README donation information and Bitcoin/Ethereum QR codes without
  crowding the main UI.
- Keep identity/preferences inspectable and resettable; do not bury them
  inside natural-language memory.

### 13. Runtime And Setup Diagnostics (M)

Why later: broader setup checks should build on the completed diagnostics
verbosity slice (PR #43) without turning the compact status UI into a
setup console.

- Add a diagnostics tab for Ollama status, selected model install state,
  local voice model state, Torch/CUDA status, Handy key presence, active
  port, and current motion backend.
- Add a visible Handy connection indicator and reconnect button below the
  sidebar visualizer, using the same connection state as diagnostics
  rather than a separate hidden device path.
- Double-check frontend modules against backend save routes so settings
  changes show clear success/failure states and do not fail silently when
  the tab stays open after the app shuts down.
- Tighten spacing in the right-side/collapsible UI, settings panels, and
  compact control rows so new diagnostics, reconnect, pause/resume, and
  mode buttons fit without adding unnecessary boundaries or dead space.
- Add optional live Handy position polling where it is useful and does not
  create excessive device/API traffic, so the sidebar position indicator
  can compare reported position against commanded targets.
- Write backend logs to a file and keep the command-line window mostly
  static during normal app use.
- Make the local network address easy to open from the command-line
  output where the terminal supports clickable links.
- Add a setup verifier command that checks Python, dependencies, Ollama,
  Chatterbox availability, Torch/CUDA, port availability, and writable
  user-data folders.
- Add cancel/retry behavior for long model downloads where the provider
  supports it.
- Add startup checks that warn without blocking when optional dependencies
  are missing.
- Keep optional model downloads as explicit UI actions with visible
  status.

## Backlog

### 14. Tip And Base Calibration Research And Restoration (M/L)

Why later: calibrated tip/base anchors may solve feel issues, but the
benefit should be confirmed against current stroke-range behavior before
adding another setup surface.

- Confirm whether the original app used separate tip/base calibration
  beyond stroke range, and identify which feel problems the restoration
  should solve.
- Restore user-facing tip and base calibration points as settings separate
  from global stroke range and speed limits if the calibration pass proves
  useful.
- Use calibrated tip/base anchors when translating zones, fixed patterns,
  Edge/Milk scripts, imported patterns, trained patterns, and LLM motion
  targets into Handy motion.
- Preserve stroke range as a safety/comfort envelope: calibration defines
  the physical tip/base mapping, while range controls how much of that
  calibrated space a move is allowed to use.
- Add a setup/recalibration flow with preview/test moves, clear labels,
  and a reset path back to conservative defaults.
- Migrate existing settings conservatively so current users keep
  equivalent motion until they intentionally recalibrate.
- Keep HAMP continuous and experimental position/script playback honoring
  the same calibration mapping without bypassing smoothing, stop behavior,
  or user speed limits.

### 15. Reference Research Backlog (S/M)

Why later: the external projects are useful inputs, but each needs
licensing, scope, and architecture review before implementation.

- Review Handy-control references:
  https://github.com/defucilis/thehandy,
  https://github.com/fredtungsten/scriptplayerthe,
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
- Evaluate whether longer example funscript libraries can help remap
  existing patterns or train pattern-generation heuristics, filtering out
  long inactive gaps that were video-synchronization artifacts rather
  than pattern intent.
- Review device-abstraction references:
  https://github.com/ConAcademy/buttplug-mcp,
  https://github.com/ofs69/syncopathy,
  https://github.com/Karasukaigan/OSRChat, and
  https://github.com/buttplugio/awesome-buttplug.
- Check reference applications when they can clarify motion, editor, or
  device behavior, but avoid importing designs that add unnecessary
  pauses, stops, or other counterproductive playback behavior.

### 16. Local Voice Control MVP (L)

Why later: voice control is the largest user-facing feature, but it should
ship as push-to-talk before always-on listening.

- Add a provider-neutral speech recognition service interface.
- Add push-to-talk browser capture with `MediaRecorder`.
- Add a `/transcribe_voice` route that accepts short recorded audio
  clips.
- Preview transcripts before submitting them through the existing
  `/send_message` path.
- Route recognized movement requests through the deterministic motion
  layer. Do not bypass speed limits, smoothing, stop handling, or
  user-visible preferences.
- Keep the physical stop button and explicit stop command independent
  from recording, upload, transcription, LLM response, and TTS latency.
- Add latency diagnostics for recording, upload, transcription, LLM
  response, voice generation, and motion dispatch.

Candidate local ASR providers:

- **faster-whisper**: optimized Whisper runtime using CTranslate2 with
  CPU/GPU execution and quantization options. Source:
  https://github.com/SYSTRAN/faster-whisper
- **whisper.cpp**: lightweight GGML/GGUF Whisper runtime for CPU-first
  testing and possible packaged builds. Source:
  https://github.com/ggerganov/whisper.cpp
- **OpenAI Whisper, local open-source model**: baseline PyTorch ASR option
  with multilingual speech recognition, translation, and language
  identification. Source: https://github.com/openai/whisper
- **NVIDIA Parakeet TDT 0.6B v3**: promising local ASR for NVIDIA GPU
  systems with punctuation/capitalization, language detection,
  timestamps, and CC BY 4.0 licensing. Source:
  https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3

### 17. Story Mode (L/XL)

Why later: it depends on reliable voice, motion preferences, and sequence
editing.

- Add scripted and model-guided scene sequences that can speak lines,
  change motion styles, react to user feedback, and optionally listen
  for voice feedback between beats.
- Let story mode use the same inspected motion/style controls as normal
  chat.
- Allow story mode to select saved patterns and soft-anchor programs
  rather than inventing opaque motion.
- Add interruption and recovery states so stop, pause, and resume remain
  predictable during longer scenes.

## Long-Horizon

### 18. Optional Runtime And Packaging Work (XL)

Why later: these should follow device and voice reliability work unless a
runtime shows a clear app-level benefit.

- Consider an LLM backend abstraction so Ollama remains the default local
  path while other runtimes, such as SGLang, can be evaluated without
  rewriting chat and motion logic.
- Compare optional local runtimes on actual app metrics: first-token
  latency, JSON reliability, model setup friction, GPU memory behavior,
  and recovery after failed requests.
- Consider a packaged Windows launcher only after runtime diagnostics,
  model downloads, voice setup, and device state handling are stable.
- Rework phone-scale control only after the local app is stable, either
  as a LAN-hosted mobile layout or a native Android application.
- Review Android-side local ML options, such as XTTS-v2, Gemini Nano on
  Pixel devices, and open-source PAIOS-style apps, only after the desktop
  voice and motion flows are reliable enough to port.

## Guardrails

- Speed limits, smoothing, stop handling, and user-visible preferences are
  shared reliability constraints. Voice control, story mode, LLM output,
  and pattern playback should all route through the same motion layer.
- Repeated thumbs-down auto-disable must remain opt-in, visible, and
  reversible. Any feedback-driven change to weights or enablement must
  appear immediately in the GUI so the user can see what changed and
  adjust it; nothing should silently disable a pattern or shift a weight
  without a visible control to undo it.
- HAMP continuous motion should remain the recommended default until
  flexible position/script playback has more real-device validation for
  smoothness, pattern fidelity, latency, and recovery behavior.
- The current flexible backend now receives shared smoothing for
  pattern/script playback and plain chat targets, but it should not
  become the default until those paths are validated on the physical
  device without boundary stutter, unexpected stops, or speed-limit
  escapes.
- Voice control should use local speech-to-text models. Hosted
  transcription would change the privacy and setup assumptions of the
  project.
- Always-on voice should wait until push-to-talk, transcript preview,
  latency, and mistaken command handling are reliable.
- Large model downloads should be explicit UI actions with visible
  progress. Startup, settings saves, and setup scripts should not
  silently download multi-GB model weights.
- Reference projects are inputs, not templates. Do not import design
  choices that add unnecessary pauses, stops, or other behavior that
  works against smooth playback, even if they appear in a referenced
  project.
