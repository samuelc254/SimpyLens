# SimpyLens Architecture (v1)

This document describes the target architecture boundaries for SimpyLens v1.

## 1) Core Architecture

- Core library entry point: `simpylens.Lens`.
- `Lens` orchestrates breakpoint management, log access, optional viewer lifecycle, and model execution flow.
- `Lens` must support both GUI and headless operation.
- `seed` must remain deterministic and reproducible.

## 2) Viewer Boundary (Internal Component)

- `Viewer` is an internal component and is not a public API entry point.
- Only `Lens` should create and manage `Viewer`.
- `Viewer` must not change business rules of the user simulation model.
- Examples and public docs should point users to `Lens` as the main entry point.

### Inspector Panel and Tabs

- The right-side Inspector panel is a GUI-only internal component.
- Inspector contains two tabs: `Breakpoints` and `Task Viewer`.
- `Task Viewer` is read-only and observational; it must never mutate simulation state.
- `Task Viewer` data comes from tracking state attached to `env` (`process_states`) and scheduler queue snapshots.
- Sorting and row selection behavior in `Task Viewer` are UI-only concerns and must not affect model execution.

### Viewer Log Interaction

- Log rendering in the Tkinter `Text` widget may enrich event lines with source locations (`file:line`).
- Source locations are clickable and routed through an internal editor opener utility.
- Click behavior must be non-blocking and must never crash the UI when editor launch fails.

## 3) Patch Independence

### `MetricsPatch`

- Public API: `simpylens.MetricsPatch.apply()`.
- Must be independent from `Lens`.
- Must work without viewer and without breakpoints.
- Must be idempotent.

### `TrackingPatch`

- Public API: `simpylens.TrackingPatch.apply()`.
- Must be independent from `Lens`.
- Must work without viewer and without breakpoints.
- Must be idempotent.

### Combined Use

- `MetricsPatch` and `TrackingPatch` must be usable together.
- Combined use should be possible but neither patch should require the other.

## 4) Public API Stability Rules

- Official user function name is `model`.
- Avoid legacy aliases in public v1 API.
- Public methods should include short docstrings and minimal examples.
- Breaking API changes are deferred to v2+.

## 5) Runtime Behavior Expectations

- `run()` and `show()` without a model should fail safely (no hard crash).
- `reset()` always recreates environment and reapplies seed.
- Breakpoints must work in GUI and headless modes.
- When `gui=True`, `Lens` manages viewer lifecycle and mainloop delegation.
- `STEP_AFTER` logs are emitted for every processed simulation step.

## 6) Editor Integration Boundary

- Editor launching is an internal viewer concern (not part of public `Lens` API).
- Default editor command is `code`, overridable via `SIMPYLENS_EDITOR`.
- Launch attempts must follow EAFP with `subprocess` and guarded exceptions.
- If the editor cannot be launched, fallback behavior is clipboard copy of `file:line` plus a terminal warning.
- The fallback is silent with respect to GUI stability (no fatal dialog, no crash).
