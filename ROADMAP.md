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

Latest cleanup note:

- The 2026-05-15 audit cleared items that were plainly shipped in
  `Changelog.txt`, especially placeholder voice-input UI, first streaming chat
  rendering, fenced-code rendering, copyable diagnostics, Handy connection
  visibility, and LAN/HTTPS setup docs.
- Items marked with a Status note are intentionally retained because the
  changelog or current code shows partial implementation, but real-device,
  real-microphone, real-mobile-browser, or product-direction confirmation is
  still missing.

## Up Next

### 1. Freestyle Diagnostics And Mode Control Reliability (S/M)

Why next: the Freestyle and motion diagnostics surfaces are now in place, but
the on-device Freestyle stop has not been confirmed fixed, and the surrounding
mode controls still have rough edges that block daily use.

Status note: Partial. Trace/status diagnostics, continuous-motion metadata,
motion transport capture, sanitized Handy command history, and HSP/HDSP/HAMP
summary reporting have landed. The remaining work is real-device verification
and planner/control fixes, not more basic instrumentation.

- Use the PR #42 trace fields and the expanded status/debug diagnostics UI
  during manual Freestyle testing to identify whether stops are planner-side,
  API-side, or Handy position-mode behavior.
- When validating Continuous position speed, compare semantic intent speed,
  HSP point spacing / HDSP per-sample command speed, effective cycle timing,
  and the final Handy command metadata instead of treating any one of those
  fields as "the speed."
- Include non-pattern LLM and Legacy Auto targets in that validation. Their
  default-backend path should stay on live stroke control, while named patterns
  and anchor programs use the continuous position/script transport.
- Treat regular Freestyle stops, end-of-sequence stalls, and the
  Auto-to-Freestyle no-action case as the current major reliability bug
  cluster. Reproduce the cases where the motion indicator advances but the
  device does not move before tuning planner behavior.
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
### 2. Adapter Boundary Guardrails And Translation Audit (S/M)

Why next: PRs #48-#75 paid down most of the compatibility-shim surface by
splitting the biggest modules, moving web runtime state into `AppState`,
typing the mode service/callback boundary, and migrating routine tests away
from direct `strokegpt.web` runtime-state bridge writes. The remaining work is
smaller: preserve the real schema/safety adapters, prevent new compatibility
bridge usage from creeping back in, and audit any remaining hand-written
translation layers before the next motion-backend changes.

Status note: Mostly complete as guardrails. The module splits, bridge tests,
payload guardrails, and adapter documentation have landed. This item remains
because the external-consumer need for the `strokegpt.web` AppState bridge is
unclear and future schema translations still need review before they are
flattened or removed.

Adapter audit findings:

- Preserve the real safety boundaries:
  `MotionSanitizer.from_llm_move()` parses LLM JSON into `MotionTarget`,
  `MotionController.apply_generated_target()` chooses continuous sampled
  control, finite position playback, or legacy HAMP while preserving
  smoothing/stop behavior, and
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
- Keep the PR #48 `background_modes` re-exports from `freestyle.py` and
  `mode_decisions.py` frozen as compatibility shims. New tests and internal
  callers should import canonical modules directly.
- Treat the remaining ``strokegpt.web`` payload wrappers
  (``settings_payload``, ``_ollama_status_payload``,
  ``_motion_pattern_catalog_payload``, ``_motion_pattern_summary``) as the
  canonical service-binding adapter for the runtime ``settings``/``llm``/
  ``audio``/pattern-library services rather than as shims slated for removal.
  New code should still extend ``strokegpt.payloads`` and bind services via
  these adapters, not introduce additional ``web.*`` payload wrappers.
- Keep the PR #50 `strokegpt.web` module-level `AppState` attribute bridge as
  legacy compatibility only. Dedicated bridge tests may cover it, but routine
  route and mode tests should use `web.app_state` or explicit dependencies.
  This boundary is enforced by `tests/test_web_bridge_guardrails.py`, which
  AST-walks every `test_*.py` and fails on plain assigns, augmented assigns,
  annotated assigns, tuple/list unpacking, and `setattr()` calls that target
  `strokegpt.web.<APP_STATE_EXPORTS-name>`; only `test_web_runtime_state.py`
  is allowlisted. Likewise, `tests/test_web_payload_guardrails.py` pins the
  set of `web.py` functions that may reference `payloads.*` to an explicit
  allowlist so new payload work has to extend `strokegpt.payloads` instead
  of growing a new `web.*` wrapper. Extend either allowlist only when
  intentionally adding new compatibility-bridge or service-binding coverage.
- Do not preserve the `strokegpt.web` `AppState` bridge indefinitely by
  default. Before expanding bridge coverage, confirm whether any external
  consumer still imports or writes `strokegpt.web.<AppState-field>`; if not,
  plan a clean removal path instead of defending the bridge only because guard
  tests exist.
- Audit code that translates between app-specific schemas, LLM JSON, pattern
  actions, UI payloads, and Handy API calls. Delete redundant wrappers only
  when they do not enforce validation, migration, user limits, smoothing, or
  persistence boundaries; otherwise document the boundary so future work does
  not flatten a real safety adapter by mistake.

### 3. Motion Vocabulary And Preset Semantics (S/M)

Why next: consistent terms make both deterministic commands and LLM outputs
less surprising before deeper pattern generation work, and several of these
items are short follow-ups to PR #38 / PR #41 / PR #43.

- Define remaining named motion semantics for deterministic speed ranges,
  full-range behavior, and adaptive timing in Freestyle or a successor mode.
- Do not add LLM-controlled timing to the old Auto loop. If adaptive timing is
  implemented, keep it bounded, visible, and reversible in Freestyle or a
  successor planner, and expose the current timing/mood bias in diagnostics
  instead of hiding it in prompt text.
- Confirm Milk Me and natural-language milk requests actually use most or
  all of the safe calibrated range unless the user explicitly asks for
  short/tight motion. PR #38 added milk vocabulary; the on-device check
  that this still holds across Continuous position and HAMP legacy is open.
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
- Keep Freestyle on the shared continuous motion path by default instead of
  falling back to HAMP/current scripted Auto arcs.
- Allow users to replace or import Edge/Milk mode scripts through the same
  visible pattern-management surface used for fixed and trained patterns.
- Finish the visible-mode action audit after the hands-free and typed-chat
  gates. Hands-free voice and ordinary typed chat can expose a guarded
  `mode_action` field only through their explicit settings toggles; reviewed
  voice transcript sends still need a separate decision before they can request
  model-selected mode changes.
- If the old Auto loop stays visible, keep labeling it as Legacy Auto and
  treat it as a scripted takeover mode, not Freestyle legacy. Avoid expanding
  it toward adaptive behavior; new autonomous/adaptive work should prefer
  Freestyle or a successor mode with visible planner controls.
- Let preset modes speak occasionally without turning mode timers into
  repeated narration.
- Keep future preset-mode narration natural-language by default. Planner
  diagnostics such as pattern ids, weights, scores, counters, and timing should
  stay in trace/debug surfaces unless a user-visible debug verbosity option is
  deliberately added.

### 4. Motion Style Preferences (M)

Why next: this is a clean way to steer model behavior without hidden prompt
drift, and it slots in after the persona audit so style preferences and
persona prompts stay separable.

- Validate whether the visible Motion Style selector's current choices map to
  useful behavior in real chat and mode-control sessions, then rename or prune
  styles that do not produce distinct enough motion.
- Decide whether Freestyle and preset-mode planners should consume the saved
  style directly in deterministic scoring, rather than relying only on the LLM
  prompt/context bias.
- Let users reset learned motion feedback and style preferences without a
  full settings reset.

### 5. Chat And Responsive UI Refactor (M)

Why next: the chat shell has gained responsive foundations, scrollback
affordances, top-bar controls, compact motion panels, voice input controls,
streamed rendering, fenced-code rendering, and several mobile-browser fixes.
The remaining work is follow-through: keep the visible app stable across
laptop, desktop, high-DPI, and real phone browsers while preserving
chat-driven motion behavior.

Status note: Partial. The first responsive/chat slices have landed, so this
entry no longer tracks placeholder voice-input controls, first streaming
rendering, or first fenced-code rendering as future work. Real Android Chrome
keyboard/no-keyboard behavior and compact motion/status ergonomics remain
watch items after recent regressions.

- Continue hardening the behavior-preserving responsive foundation started in
  PR #84: shared spacing, control-height, chat-width, motion-strip tokens,
  dynamic viewport height, centered chat/input/status surfaces, and breakpoints
  that stack controls before they crowd the chat input.
- Prefer rem/token-based dimensions and explicit min/max constraints over
  fixed-pixel layout assumptions. Do not scale font size with viewport
  width; text should remain readable and controls should remain stable on
  high-DPI displays.
- Refine the chat surface before behavior work: labeled conversation/log
  regions, stable full-width message rows with bounded text measure,
  tokenized bubble/avatar sizing, and a composer that keeps predictable hit
  targets across desktop and phone layouts.
- Keep the central chat area visually dense before changing behavior:
  prefer wider chat/composer/status surfaces, compact chat-only gutters, and
  subtle borders/fill around the scrollback and motion strip so the primary
  workspace uses available space without adding pressure to the already full
  right sidebar.
- Treat the composer, status text, and motion indicators as one responsive
  chat control shelf: use horizontal space on desktop, stack before controls
  crowd each other, and keep live-status feedback visible without consuming
  a separate full-width row when the message is short.
- Build on the initial scrollback/autoscroll pass: new background messages
  should not yank the user away from older content, the local "Latest" jump
  affordance should stay visible and keyboard reachable, and later streaming
  work should reuse the same near-bottom stickiness contract.
- Continue app-shell top-bar work only where real visual review shows
  regressions. The title, timer/mood chips, profile menu, sidebar toggle, and
  top-bar voice controls now have stable grid areas, but compact/mobile
  wrapping still needs watch as controls evolve.
- Refactor the visible app shell in small stages: top bar, chat scrollback,
  bottom composer, motion/status strip, and right-side controls should each
  have clear layout responsibilities before deeper visual restyling.
- Audit the existing chat panel against modern local-LLM front-ends
  (Ollama UI, Open WebUI, LM Studio, etc.) for layout, message styling,
  scroll/auto-scroll behavior, streaming render, and accessible focus
  handling. Use them as references for ergonomics, not as templates to
  copy whole-cloth.
- Redo the chat toolbar and indicator strip so the speed/depth meter,
  motion sequence log, feedback buttons, mode/timer indicators, and
  Pause/Resume/Stop controls share one consistent layout grammar instead
  of being individually retrofitted around the legacy chat panel.
- Validate streamed and non-streamed Ollama rendering now that the first
  streaming slice exists. The chat-emit path still needs to stay in lockstep
  with the TTS-enqueue path (see KNOWN_PROBLEMS "Local LLM Chat Text Sometimes
  Missing While Voice Plays"), especially when motion repair replaces streamed
  draft text, slow models delay final JSON validation, or a browser falls back
  to the non-streaming path.
- Continue investigating provider-specific or rapid-mode TTS cutoffs after the
  local Chatterbox WAV encoder's trailing silence cushion has been validated
  during real playback.
- Preserve the fenced-code rendering and copy action while restyling; do not
  regress literal markdown text, copy/paste, scrollback, or screen-reader
  behavior.
- Preserve the existing chat-driven motion contract (chat-driven
  Pause/Resume, chat edge-blocking, motion-target language) while moving
  the visible surface into the new layout.

## Queued

### 6. Soft-Anchor Pattern Authoring (M/L)

Why later: it addresses the gap between fixed scripts and raw LLM numeric
control while staying inspectable, but should follow the code reorg so it
can land cleanly inside the new motion blueprints/modules.

Status note: Partial. Backend soft-anchor programs landed earlier, including
LLM-facing waypoint semantics and compiler behavior. This item is specifically
for visible authoring, preview, saved soft-anchor patterns, and editing
controls that do not exist yet.

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
- Explore whether three- and four-point soft waypoint loops feel less jerky
  than simple two-point bouncing, while still giving the LLM a small,
  inspectable control surface.
- Ignore long inactive gaps from video-synced example funscripts when using
  them as pattern examples; those gaps usually describe source media timing,
  not useful standalone motion intent.

### 7. Architecture Audit And Strategic Refactor (M)

Why later: the immediate code reorg in Up Next #2, the recently completed
`static/js/motion-control.js` module split (PRs #64-#67 plus the training
editor extraction), and the chat shell refactor in Up Next #5 cover the
obvious splits. This entry is for the deeper, design-level audits that need
a clean tree first.

- Validate the new Continuous position default against chat control,
  Freestyle, motion training, Edge/Milk mode scripts, stop behavior, and
  real-device smoothness.
- Keep HAMP visible as a legacy fallback until real-device testing proves the
  continuous backend is at least as recoverable for basic strokes and stop
  behavior.
- Preserve the current shared backend guard rails: user-speed-relative XAVA
  velocity caps, speed-scaled continuous sample intervals, authored
  action-timing and slope preservation for HSP plus Flexible Position,
  Flexible Position duration stretching when authored timing exceeds the
  configured velocity cap, no hidden HSP timestamp stretching, depth-jump
  splitting, turn-apex smoothing for finite position/script callers, and
  uninterrupted stop/pause generation changes for continuous sampled planners.
- Prototype inertia-aware direction changes and stops for the continuous
  schema, so sampled output does not expose obvious step boundaries or abrupt
  reversals.
- Review current Handy API and firmware behavior, including Handy 2 and
  Handy 2 Pro-specific constraints, before raising speed limits or adding
  overclock-style settings.
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
  into focused modules. Do the voice-generation refactor after the chat/UI
  refactor so TTS cutoffs and text/voice mismatch bugs can be separated from
  chat-pipeline bugs first.
- Evaluate local voice-cloning TTS replacements only after the provider
  boundary exists. Keep Chatterbox Turbo as the latency baseline; compare
  F5-TTS and CosyVoice only if they preserve reference-audio cloning, explicit
  model downloads, and local/offline operation. CosyVoice should be treated as
  a poor default choice unless it can install and run cleanly on Windows without
  requiring Docker, WSL, or a Linux-only Triton/TensorRT stack as the normal
  path. If it works only through that heavier deployment shape, keep it as an
  optional advanced NVIDIA-runtime experiment at most. Any candidate benchmark
  should measure cold load, warm first-audio latency, real-time factor, VRAM
  use, and coexistence with Ollama plus voice input on an 8 GB RTX 5060-class
  machine before changing the recommended local TTS provider.
- Treat frontend source-text tests as static contract coverage, not behavioral
  proof. When a future bug depends on DOM mutation, state transitions, or
  handler outcomes, prefer a `tests/js/*.test.mjs` behavioral test and avoid
  adding new substring pins for branch shape unless the assertion is truly
  about an export, compatibility boundary, or markup invariant.
- Keep the local runtime assumption explicit: one trusted local operator, one
  active browser session, one Handy controller, and one shared settings file.
  Do not introduce multi-user/session architecture without a deliberate product
  decision; document the assumption and only add a tab warning if real use
  shows confusion.
- Pattern-library lazy-load parking lot: defer lazy-loading the JSON pattern
  library and prepared-action cache until pattern count grows enough to justify
  it; the cache exists, but eager loading is still simpler and cheap at the
  current catalog size.
- Prefer practical maintainability refactors when they improve
  editability, recoverability, or safety.

### 8. Motion Training Editor Depth (M)

Why later: the training workspace already exists, so richer editing can
build on the current surface without crowding Settings.

Status note: Partial. Motion Pattern Studio, funscript import/crop preview,
freehand drawing, smoothing/harshening, tempo/duration controls, range remap,
and Save As New Pattern have landed. Remaining work is deeper editing:
direct point manipulation, undo/redo history, unimplemented transforms, and
multi-pattern sequencing.

- Add point dragging on the motion graph with snap/undo and validation
  before playback.
- Add transform history with per-step undo/redo.
- Add remaining pattern transforms: repeat a stroke shape, simplify noisy
  points, mirror timing, and apply subtle randomized variation.
- Add pattern sequencing: alternate multiple patterns in order with small
  blends between segments to avoid stutter.
- Keep compact Motion settings limited to management: enablement, weights,
  import/export, and status.

### 9. User Profile And Preference Setup (M)

Why later: identity and preference setup affects persona prompts and model
context, so it should follow runtime diagnostics, motion vocabulary
cleanup, and the persona naming audit.

- Add a custom user display name and keep it separate from the current
  persona/profile-picture controls.
- Add Personality Presets to Settings and include the GLaDOS-style prompt as
  a selectable preset. Keep persona presets separate from motion style and
  user identity preferences.
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
- Keep identity/preferences inspectable and resettable; do not bury them
  inside natural-language memory.

### 10. Runtime And Setup Diagnostics (M)

Why later: the Settings > Diagnostics tab now covers setup checks and basic
latency probes, copyable system/app status, motion transport capture, Ollama
GPU preflight, and a visible Handy connection panel. The remaining runtime
diagnostics should still avoid turning the compact status UI into a setup
console.

Status note: Partial. The broad Diagnostics tab/status/reporting work is
mostly shipped. Retained items below are either not implemented, still need
manual browser/device smoke, or are guardrails for future diagnostics changes.

- Keep future diagnostics additions in Settings > Diagnostics when the
  information changes user action; avoid spreading setup/debug reports back
  into Model, Voice, Motion, or the sidebar unless they are primary controls.
- Add device-profile controls for Handy 1 versus Handy 2 speed-limit behavior,
  and only expose Handy 2 Pro overclock options if current documentation
  supports a clear warning, limit, and fallback path.
- Keep backend-shutdown browser smoke on the manual checklist so the
  connection-lost banner, backend-required control lock, and per-control
  rejection copy stay aligned with the runtime tests. Keep the user-facing
  failure model simple: persistent red banner for network/backend loss, one
  inline status near the affected control for reachable-but-rejected writes,
  and handler-specific treatment for action endpoints that already have mode,
  chat, or toast feedback. Extend the shared status-tone helper if the failure
  model needs new severity states; do not mechanically add handler-specific
  color writes if they produce duplicate or conflicting messages.
- Continue tightening spacing in the right-side/collapsible UI, settings
  panels, and compact control rows only when visual review or user reports show
  a regression; several spacing fixes have landed, but compact layouts remain
  easy to break.
- Add a test button beside initial-setup and Settings min/max speed sliders
  that moves the device at the selected speed over the configured safe range
  for a short, bounded duration.
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
- Add a Python 3.12 compatibility lane before changing the Windows installer
  default away from Python 3.11. Use 3.12 as the first newer-version target
  because it is far enough ahead to expose 3.11-only assumptions while still
  being less likely than 3.13/3.14 to trip over fresh ML wheel gaps. The first
  slice should run the normal unit/compile suite on 3.11 and 3.12, then add a
  Windows install/import smoke for `chatterbox-tts`, `faster-whisper`, Torch,
  torchaudio, and the isolated Parakeet runtime path. Keep 3.11 as the main
  app default until local Chatterbox, faster-whisper, CUDA Torch, and the
  optional Parakeet worker all install and import cleanly on 3.12. Consider
  3.13/3.14 only after that baseline is stable.
- Add cancel/retry behavior for long model downloads where the provider
  supports it.
- Add startup checks that warn without blocking when optional dependencies
  are missing.
- Track noisy third-party deprecation warnings, such as the diffusers LoRA to
  PEFT warning, only when they are user-visible or indicate a future breakage
  risk. Do not add new dependencies just to silence a warning.

## Backlog

### 11. Tip And Base Calibration Research And Restoration (M/L)

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
- Keep Continuous position, finite position/script playback, and HAMP legacy
  honoring the same calibration mapping without bypassing smoothing, stop
  behavior, or user speed limits.

### 12. Reference Research Backlog (S/M)

Why later: the external projects are useful inputs, but each needs
licensing, scope, and architecture review before implementation.

- Review Handy-control references:
  https://github.com/defucilis/thehandy,
  https://github.com/fredtungsten/scriptplayerthe,
  https://github.com/Yazui1/handy-companion,
  https://github.com/KarilChan/handy-koikatsu-server,
  https://github.com/Glavi0us/scripts-control,
  https://thehandyapp.ddns.net/#/voice-commands-page, and
  https://www.reddit.com/r/theHandy/comments/upuo98/create_a_slider_for_live_control/.
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
- Review feature and UX ideas from https://theedgy.app/changelog#v1.5.1
  only for workflow inspiration; do not copy interaction patterns that add
  avoidable playback stops or hidden state.
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

### 13. Local Voice Control Hardening (L)

Why later: PR #89 landed the provider-neutral service, browser
`MediaRecorder` capture, faster-whisper transcription route, explicit
model-load action, transcript preview, and initial hands-free mode. Follow-up
PRs added useful diagnostics and tuning, but the Settings > Voice surface now
exposes too many implementation knobs as normal user choices. The remaining
work is reliability and ergonomics: validate real defaults, simplify the
routine UI, and keep voice control flowing through the existing chat, motion,
and stop safety paths.

Status note: Partial. Flexible voice input, faster-whisper, optional NVIDIA
Parakeet, microphone selection, LAN/HTTPS microphone guidance, diagnostics,
confidence gates, and collapsed advanced controls have landed. Real microphone
testing is still unclear, so this item stays focused on proving defaults and
pruning routine controls rather than adding more knobs.

- Verify push-to-talk and hands-free recognition with real microphones on a
  slow Windows laptop and a faster desktop, including empty/noisy clips,
  short commands, and longer natural-language movement requests.
- Use the current advanced capture and recognition controls during real
  microphone testing as instrumentation first, including browser audio
  preprocessing and silence trimming. Promote only the controls that users
  actually need during normal operation; move the rest to diagnostics or
  remove them from Settings > Voice after the baseline is measured.
- Keep the default Voice tab centered on provider, recording mode, transcript
  handling, model preset/path, language, and one clear calibration/sensitivity
  path. Do not move beam size, condition-previous, VAD threshold, VAD silence,
  VAD padding, and raw noise-floor values back into the routine path unless
  the real-mic baseline proves they are necessary recovery tools.
- Use the faster-whisper model presets during recognition testing:
  `tiny.en` for lowest latency, `base.en` as the first balanced laptop target,
  `small.en` for better noise tolerance, and `distil-large-v3` for faster
  desktops or GPU setups. Keep the custom model field available for converted
  or externally hosted compatible models, and use the local folder picker for
  converted CTranslate2 model directories.
- Treat faster-whisper baseline tuning as backend behavior first, not another
  Settings > Voice expansion. The live mic path should keep using tuned
  defaults such as English-for-`auto`, a short command vocabulary prompt,
  beam-1 fast pass with configured-beam fallback, and confidence rejection
  before any threshold becomes a visible user choice.
- Keep recognized movement requests routed through the existing
  `/send_message` path and deterministic motion layer. Do not bypass speed
  limits, smoothing, stop handling, chat edge-blocking, or user-visible
  preferences.
- Keep the physical stop button and explicit stop command independent from
  recording, upload, transcription, LLM response, TTS generation, and motion
  dispatch latency.
- Continue from the Settings > Diagnostics latency tests by adding audio
  playback and motion-dispatch timings only after real hands-free testing
  shows that those downstream delays are still hard to explain.
- Continue failure-state tuning after real microphone testing: refine
  browser-specific permission handling, noisy/empty clip copy, calibrated
  threshold guidance, model-load recovery guidance, and CPU-latency thresholds.
- Decide whether the microphone menu should expose sensitivity, clip length,
  language, and submit-mode controls directly or keep those in Settings >
  Voice once real hands-free testing shows which controls users need during
  operation.
- Compare the tuned faster-whisper baseline and the optional NVIDIA Parakeet
  provider with the same real microphone clips. Faster-whisper remains the
  CPU/portable path; Parakeet is the GPU-focused comparison path behind the
  provider toggle and optional isolated NeMo install. Use those measurements
  to decide whether routine users need a simpler provider recommendation, not
  more visible ASR knobs.
- Defer whisperX to long-form audio import or funscript-alignment work. Its
  word alignment, diarization, and batching strengths do not pay for short
  live voice commands.
- Defer whisper.cpp to packaged Windows launcher work, where a small external
  runtime may matter more than Python ML dependency reuse.
- Keep streaming/chunked upload as a later phase after the tuned baseline and
  provider abstraction decisions land.
  It has a larger state/concurrency surface than the quick latency wins and
  should not be mixed into the first tuning slice.

### 14. Story Mode (L/XL)

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

### 15. Internet-Exposed Remote Control And Multi-User Sessions (XL)

Why later: the app is currently designed for one trusted local operator, one
active browser session, and one Handy controller. Opening control to the public
internet changes the threat model, credential handling, device-safety model,
and runtime/session architecture, so it should wait until the local and LAN
flows are reliable.

- Add an explicitly enabled internet-exposed remote-control mode with HTTPS,
  authentication, hardened sessions, rate limiting, CSRF protection, and a
  clear warning that this is different from trusted LAN access.
- Support individual user accounts or per-user passcodes so each remote
  participant has their own login identity instead of sharing one global
  secret.
- Define same-device multi-user control semantics before implementing them:
  active operator ownership, host approval or handoff, command queuing or
  voting, visible participant state, and conflict resolution when two users
  request incompatible movement.
- Keep emergency stop, pause, speed limits, stroke-range limits, and motion
  smoothing global and authoritative. A stop from the host or any permitted
  participant should interrupt device motion regardless of who currently owns
  the session.
- Add role/permission levels such as host/admin, active controller, invited
  participant, and view-only observer before exposing remote controls broadly.
- Keep remote commands routed through the same chat, motion controller, Handy
  controller, and deterministic safety layers as local commands; do not add a
  bypass path for remote users.
- Add audit/debug visibility for remote sessions: connected users, recent
  commands, active controller, rejected commands, failed login attempts, and
  current public-exposure status.
- Treat credential storage, password/passcode hashing, recovery, lockout,
  session expiry, and token invalidation as first-class requirements. Do not
  store remote-login secrets in repo files or reuse local Handy/device keys as
  web-login credentials.
- Document safe deployment options only after the security model exists:
  reverse proxy, tunnel, certificate, firewall, and port-forwarding guidance
  should all explain the risks of exposing a motion-control device to the
  internet.
- Preserve the current single-operator local runtime until this work begins as
  an intentional architecture change; do not let ordinary LAN/mobile fixes
  accidentally create a partial multi-user control model.

### 16. Optional Runtime And Packaging Work (XL)

Why later: these should follow device and voice reliability work unless a
runtime shows a clear app-level benefit.

- Consider an LLM backend abstraction so Ollama remains the default local
  path while other runtimes, such as SGLang, TurboQuant, or vLLM-backed
  TurboQuant experiments, can be evaluated without rewriting chat and motion
  logic.
- Compare optional local runtimes on actual app metrics: first-token
  latency, JSON reliability, model setup friction, GPU memory behavior,
  and recovery after failed requests.
- Consider a packaged Windows launcher only after runtime diagnostics,
  model downloads, voice setup, and device state handling are stable.
- Continue phone-scale control only after the local/LAN mobile layout is
  stable in real mobile browsers. The LAN-hosted mobile layout is partial; a
  native Android application remains a later alternative if browser ergonomics
  keep blocking normal use.
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
- Continuous position is now the recommended default, but HAMP must remain a
  user-visible legacy fallback until physical-device testing confirms
  smoothness, pattern fidelity, latency, and recovery behavior.
- Any motion-backend switch must stay user-visible and reversible until the
  continuous schema clearly beats HAMP reliability on physical hardware.
- Settings saves, feedback actions, reconnect attempts, and mode starts should
  report success or failure in the UI. A browser tab that remains open after
  the app shuts down must not appear to keep saving settings silently.
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
