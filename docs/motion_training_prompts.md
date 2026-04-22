# Motion Training Implementation Prompts

Use these prompts as staged follow-up work. Each PR should stay small enough to
review and test locally before pushing.

## PR 1 - Pattern Files And Import/Export

```text
Continue StrokeGPT-ReVibed motion training work. Read Codex.md, README.md,
ROADMAP.md, Changelog.txt, strokegpt/motion_patterns.py, and the current web
routes first. Implement only the backend foundation for shareable motion
patterns: a dependency-free JSON schema, a user_data/patterns registry,
validation for funscript-style actions, built-in pattern catalog entries, and
Flask routes to list, inspect, import, and export patterns. Do not add training
UI or change live Handy playback yet. Add focused tests and update the
changelog before preparing the PR. Give a local PowerShell validation script
that ends by running the app for manual user testing before pushing.
```

## PR 2 - Settings Pattern List

```text
Continue StrokeGPT-ReVibed motion training work. Build on the pattern library
routes from PR 1. Add a Settings -> Motion pattern list that shows built-in and
user-imported patterns with name, source, duration, action count, and enabled
state. Add checkboxes for enabling/disabling patterns, persist the enabled
state in portable settings, and keep built-in pattern metadata read-only. Do
not add device playback from this list yet. Add static asset tests and focused
settings persistence tests. Update Changelog.txt and provide a local
PowerShell validation script that ends by running the app for manual user
testing before pushing.
```

## PR 3 - Motion Training Player

```text
Continue StrokeGPT-ReVibed motion training work. Add a Motion Training view
that previews one pattern at a time, sends playback through MotionController,
and always keeps stop handling immediate. Add thumbs up, neutral, and thumbs
down feedback buttons that write feedback counts into the pattern's user file
or portable settings without changing LLM behavior yet. Include clear idle,
playing, stopped, and error states. Add tests for routes and stop behavior.
Update Changelog.txt and provide a local PowerShell validation script before
pushing. The script should end by running the app for manual user testing.
```

## PR 4 - Smooth/Harshen Transforms

```text
Continue StrokeGPT-ReVibed motion training work. Add pattern transforms inspired
by funscript tooling: smooth sparse actions, harshen by reducing interpolation,
halve/double timing, repeat without a hard seam, remap position range, and add
small bounded variation. All transforms must preview as a generated variant
before replacing or saving a pattern. Keep the transform pipeline
dependency-free unless a larger importer is deliberately chosen. Add tests for
action timing, continuity, and large-step limits. Update Changelog.txt and
provide a local PowerShell validation script that ends by running the app for
manual user testing before pushing.
```

## PR 5 - LLM Pattern Preference Integration

```text
Continue StrokeGPT-ReVibed motion training work. Use enabled patterns and
thumbs feedback to shape LLM-accessible motion preferences in a visible,
editable way. The model may choose named enabled patterns or soft-anchor
programs, but hardware commands must still pass through MotionController and
HandyController speed/stop constraints. Add a user-visible preference/memory
summary that can be edited or reset. Add tests proving disabled patterns are
not selected and stop commands remain immediate. Update Changelog.txt and
provide a local PowerShell validation script that ends by running the app for
manual user testing before pushing.
```
