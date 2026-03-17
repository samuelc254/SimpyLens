# SimpyLens API Reference (v1)

This document defines the public API contract for SimpyLens v1.

## Public Entry Point

- Main class: `simpylens.Lens`
- Additional public objects: `simpylens.Breakpoint`, `simpylens.TrackingPatch`, `simpylens.MetricsPatch`

## `Lens`

### Constructor

```python
Lens(model=None, title="SimPyLens", gui=True, metrics=True, seed=42, lens_json_path=None)
```

- `model`: callable that receives a single `simpy.Environment` argument.
- `title`: UI title when GUI is enabled.
- `gui`: if `True`, creates and manages the viewer lifecycle.
- `metrics`: if `True`, applies `MetricsPatch` automatically.
- `seed`: deterministic simulation seed.
- `lens_json_path`: optional path (`str` or `Path`) to the layout JSON file used
  by the GUI to persist and restore manual resource positions.  
  When omitted, SimpyLens automatically infers the path as
  `.<model_file>.lens.json` placed next to the model's source file.  
  Supplying an explicit path is useful when you want to version multiple
  distinct layouts for the same model:

  ```python
  lens = Lens(model=my_model, lens_json_path="layouts/production.lens.json")
  ```

### Model Contract

Expected signature:

```python
def model(env: simpy.Environment):
    ...
```

## Official `Lens` Methods

- `set_model(model)`
- `set_seed(seed)`
- `run()`
- `step()`
- `reset()`
- `add_breakpoint(condition, label=None, enabled=True, pause_on_hit=True, edge="none")`
- `add_breakpoint(breakpoint)`
- `remove_breakpoint(breakpoint_id)`
- `clear_breakpoints()`
- `set_breakpoint_enabled(breakpoint_id, enabled)`
- `set_breakpoint_pause_on_hit(breakpoint_id, pause_on_hit)`
- `list_breakpoints()`
- `show()`
- `get_logs()`
- `set_log_capacity(capacity)`

### Method Behavior Notes

- `run()` is blocking in both GUI and headless modes.
- `step()` advances one simulation step regardless of GUI mode.
- `reset()` always rebuilds the environment and reapplies the configured seed.
- `show()` starts Tkinter mainloop when GUI is enabled.
- `list_breakpoints()` returns a copy of registered breakpoints.
- `get_logs()` returns a JSON-serializable list snapshot.
- `set_log_capacity(capacity)` updates bounded log capacity (default `1000`).

## GUI Inspector Tabs (Internal Viewer UI)

When `gui=True`, the internal Inspector panel contains two tabs:

- `Breakpoints`: visual state and controls for registered breakpoints.
- `Task Viewer`: live, read-only snapshot of active processes.

### Task Viewer Columns

- `#`: scheduler queue order for the process target event when available.
- `Process`: process display label with stable process identifier.
- `Yielding On`: current SimPy target type (for example `Timeout`, `Request`, `Put`, `Get`, `Condition`).
- `Holding`: resources currently held by that process.
- `Waiting On`: resource/store/container currently being awaited.

### Task Viewer Behavior

- Only alive processes are displayed.
- Clicking a column header cycles sort mode: ascending, descending, then unsorted.
- Unsorted mode keeps the original process creation order.
- Queue order values are derived from SimPy scheduler queue position when the current target is present in `env._queue`.
- Empty-state values are rendered as `-`.
- Selection state is preserved across panel refreshes when possible.

### Data Source Contract (Internal)

Task Viewer reads tracking data maintained by `TrackingPatch` in `env.process_states` with process-scoped fields:

- `process_id`
- `label`
- `creation_order`
- `holding` (set)
- `queuing` (set)

These fields are internal implementation details that support GUI inspection and are not a separate public API surface.

## `Breakpoint`

`add_breakpoint()` accepts either:

- A `Breakpoint` instance.
- Parameters for direct creation.

### Parameters

- `condition`: expression string or callable.
- `label`: optional display label.
- `enabled`: enables/disables evaluation.
- `pause_on_hit`: pause simulation when matched.
- `edge`: one of `"none"`, `"rising"`, `"falling"`.

### Public Fields

- `id`: unique auto-generated immutable identifier.
- `condition`: original condition.
- `label`: display label.
- `enabled`: active status.
- `pause_on_hit`: pause behavior.
- `edge`: edge mode.

## Public `Lens` Attributes

- `lens.model` (read-only, use `set_model` to update)
- `lens.seed` (read-only, use `set_seed` to update)
- `lens.title` (read-only)
- `lens.gui` (read-only)

## Viewer Log Source Links (GUI)

When `gui=True`, logs shown in the internal viewer can include a source location token in the form `filename:line`.

- Location token is appended when event payload provides `data.file` and `data.line`.
- Location token is clickable in the log panel.
- Clicking attempts to open the editor at the exact file and line.

### Editor Configuration

Environment variable:

- `SIMPYLENS_EDITOR`: optional override for the editor command.
- Default when unset: `code`.

Examples:

```bash
# VS Code
SIMPYLENS_EDITOR="code"

# PyCharm command-line launcher
SIMPYLENS_EDITOR="pycharm"

# Neovim
SIMPYLENS_EDITOR="nvim"

# Custom command with placeholders
SIMPYLENS_EDITOR="my-editor --open {file} --line {line}"
```

Supported placeholders in `SIMPYLENS_EDITOR`:

- `{file}`: absolute file path
- `{line}`: line number
- `{location}`: `file:line`

### Fallback Behavior

If editor launch fails (for example, command not in `PATH`), SimpyLens:

1. Copies `file:line` to system clipboard.
2. Prints a warning message in terminal.
3. Continues running without crashing the GUI.

## Layout File

When `gui=True`, SimpyLens persists the manual positions of resource blocks in a
JSON file so that layouts survive restarts.

**Default file name:** `.<model_file>.lens.json`, placed in the same directory as
the Python file that defines the model function.

**Custom path:** pass `lens_json_path` to `Lens(...)` to use
any path, enabling multiple named layouts for the same model:

```python
# Development layout
lens_dev = Lens(model=factory, lens_json_path=".factory.dev.lens.json")

# Production layout stored inside a layouts/ folder
lens_prod = Lens(model=factory, lens_json_path="layouts/factory_prod.lens.json")
```

## Metrics API

Metrics are exposed in real time through `resource.metrics.<metric_name>`.

### Resource Family Metrics

- `queue_wait_time_min`
- `queue_wait_time_avg`
- `queue_wait_time_max`
- `request_queue_min`
- `request_queue_avg`
- `request_queue_max`
- `usage_time_min`
- `usage_time_avg`
- `usage_time_max`
- `total_acquisitions`
- `total_releases`
- `idle_time_pct`
- `busy_time_pct`
- `concurrent_users_min`
- `concurrent_users_avg`
- `concurrent_users_max`

### Store Family Metrics

- `get_wait_time_min`
- `get_wait_time_avg`
- `get_wait_time_max`
- `get_queue_min`
- `get_queue_avg`
- `get_queue_max`
- `put_wait_time_min`
- `put_wait_time_avg`
- `put_wait_time_max`
- `put_queue_min`
- `put_queue_avg`
- `put_queue_max`
- `total_items_put`
- `total_items_got`
- `level_min`
- `level_avg`
- `level_max`

### Container Family Metrics

- `get_wait_time_per_unit_min`
- `get_wait_time_per_unit_avg`
- `get_wait_time_per_unit_max`
- `get_queue_min`
- `get_queue_avg`
- `get_queue_max`
- `put_wait_time_per_unit_min`
- `put_wait_time_per_unit_avg`
- `put_wait_time_per_unit_max`
- `put_queue_min`
- `put_queue_avg`
- `put_queue_max`
- `total_amount_put`
- `total_amount_got`
- `level_min`
- `level_avg`
- `level_max`

### Metrics Contract Rules

- Metrics are read-only in public API.
- `MetricsPatch.apply()` is idempotent.
- Metrics patch can be used independently of `Lens`, tracking, viewer, and breakpoints.

## Compatibility Conventions (v1)

- Official user entry function name: `model`.
- Avoid legacy aliases in public API.
- Public methods should have short docstrings with examples.
- Breaking changes are reserved for v2+.
