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
