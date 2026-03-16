# SimpyLens Logging Schema (v1)

This document defines the v1 logging contract, JSON envelope, event taxonomy, and viewer formatting rules.

## 1) Internal Log Contract and Public Output

### Goals

- Internal writes should be efficient for high-frequency appends.
- Public output from `lens.get_logs()` must be stable and JSON-serializable.

### Internal Structure (non-public)

- Bounded circular buffer / queue.
- O(1) append behavior.
- Oldest entries are discarded when capacity is exceeded.
- Serialization is performed at public boundaries (`get_logs()` / export).

### Public Output (`get_logs()`)

- Return type: JSON list of log objects.
- Each object must include a stable envelope with required fields.

### Naming and Compatibility

- Use `snake_case` for keys.
- Use uppercase with `_` for `kind` and `event` values.
- Existing event names must remain stable in v1.
- New fields must be backward-compatible additions only.

### Runtime Behavior

- `lens.set_log_capacity(capacity)` updates max buffer size.
- `lens.get_logs()` returns a snapshot, never mutable internal references.
- Logs must work with and without GUI.
- Breakpoint eval failures emit `BREAKPOINT_ERROR`.
- Breakpoint hits emit `BREAKPOINT_HIT`.

## 2) JSON Standard (v1)

This section defines the canonical JSON shape for all v1 logs.
Every event must follow the envelope fields below and use the approved `kind/event` taxonomy.

## 3) Mandatory Envelope Fields

Every log object must contain exactly these envelope fields at root level:

| Field | Type | Description |
|---|---|---|
| `schema_version` | string | Schema version. Fixed `"1.0"` in v1. |
| `seq` | int | Monotonic per-execution sequence number (reset on `RESET`). |
| `time` | float | Simulation time when event was emitted. |
| `kind` | string | High-level category. |
| `event` | string | Specific event within category. |
| `level` | string | `DEBUG`, `INFO`, `WARN`, `ERROR`. |
| `source` | string | Origin component, such as `lens` or `tracking`. |
| `message` | string | Short human-readable summary. |
| `data` | object or null | Event-specific payload. |

Only envelope fields belong at root level. All event-specific payload data must stay inside `data`.

## 4) v1 Kind/Event Matrix

| `kind` | `event` | Source | Description |
|---|---|---|---|
| `SIM` | `RESET` | `lens` | Simulation reset. |
| `SIM` | `RUN_COMPLETE` | `lens` | Simulation finished (empty schedule). |
| `STEP` | `STEP_BEFORE` | `tracking` | Before one SimPy step. |
| `STEP` | `STEP_AFTER` | `tracking` | After every SimPy step. |
| `RESOURCE` | `REQUEST` | `tracking` | Process requested a resource. |
| `RESOURCE` | `RELEASE` | `tracking` | Process released a resource. |
| `RESOURCE` | `PUT` | `tracking` | Put item/amount into Store/Container. |
| `RESOURCE` | `GET` | `tracking` | Got item/amount from Store/Container. |
| `BREAKPOINT` | `BREAKPOINT_HIT` | `lens` | Breakpoint condition matched. |
| `BREAKPOINT` | `BREAKPOINT_ERROR` | `lens` | Breakpoint evaluation error. |
| `STATUS` | `MESSAGE` | `lens` | Generic fallback message. |

## 5) `data` Schemas by Event

### `SIM / RESET`

```json
"data": {
  "seed": 42
}
```

### `SIM / RUN_COMPLETE`

```json
"data": null
```

### `STEP / STEP_BEFORE`

```json
"data": {
  "step": 3,
  "sim_event": "Timeout",
  "delay": 1.5,
  "resource": "counter",
  "process": "customer",
  "triggering": ["customer", "source"],
  "file": "/path/to/model.py",
  "line": 37
}
```

Optional fields must be included only when applicable.

### `STEP / STEP_AFTER`

```json
"data": {
  "step": 3,
  "active_process": "customer",
  "previous_process": "customer",
  "file": "/path/to/model.py",
  "line": 37
}
```

`active_process` can be `"-"` when no process is active.

### `RESOURCE / REQUEST` and `RESOURCE / RELEASE`

```json
"data": {
  "resource": "counter",
  "process": "customer",
  "from": "<START>",
  "to": "counter",
  "file": "/path/to/model.py",
  "line": 37
}
```

For releases, `to` should be `"<IDLE>"`.

### `RESOURCE / PUT` and `RESOURCE / GET`

```json
"data": {
  "resource": "warehouse",
  "process": "producer",
  "from": "<START>",
  "to": "warehouse",
  "amount": 5,
  "file": "/path/to/model.py",
  "line": 37
}
```

Use `amount` (`Container`), `item` (`Store`), or `filter` (`FilterStore`) only when present.

### `BREAKPOINT / BREAKPOINT_HIT`

```json
"data": {
  "breakpoint_id": 3,
  "label": "fila cheia",
  "condition": "len(resources['Queue'].queue) > 5",
  "hit_count": 2,
  "pause_on_hit": true,
  "edge": "rising"
}
```

### `BREAKPOINT / BREAKPOINT_ERROR`

```json
"data": {
  "breakpoint_id": 3,
  "label": "fila cheia",
  "condition": "len(resources['Queue'].queue) > 5",
  "error": "NameError: name 'resources' is not defined"
}
```

### `STATUS / MESSAGE`

```json
"data": null
```

## 6) Complete Event Examples

### `SIM / RESET`

```json
{
  "schema_version": "1.0",
  "seq": 1,
  "time": 0.0,
  "kind": "SIM",
  "event": "RESET",
  "level": "INFO",
  "source": "lens",
  "message": "Simulation reset with seed 42",
  "data": {"seed": 42}
}
```

### `STEP / STEP_BEFORE`

```json
{
  "schema_version": "1.0",
  "seq": 5,
  "time": 0.0,
  "kind": "STEP",
  "event": "STEP_BEFORE",
  "level": "DEBUG",
  "source": "tracking",
  "message": "Step 3: Timeout | triggering=customer",
  "data": {
    "step": 3,
    "sim_event": "Timeout",
    "delay": 1.5,
    "triggering": ["customer"],
    "file": "examples/pottery_factory.py",
    "line": 37
  }
}
```

### `STEP / STEP_AFTER`

```json
{
  "schema_version": "1.0",
  "seq": 6,
  "time": 1.5,
  "kind": "STEP",
  "event": "STEP_AFTER",
  "level": "DEBUG",
  "source": "tracking",
  "message": "Step 3: active=customer",
  "data": {
    "step": 3,
    "active_process": "customer",
    "previous_process": "customer",
    "file": "examples/pottery_factory.py",
    "line": 37
  }
}
```

### `RESOURCE / REQUEST`

```json
{
  "schema_version": "1.0",
  "seq": 8,
  "time": 0.0,
  "kind": "RESOURCE",
  "event": "REQUEST",
  "level": "INFO",
  "source": "tracking",
  "message": "customer requested counter",
  "data": {
    "resource": "counter",
    "process": "customer",
    "from": "<START>",
    "to": "counter"
  }
}
```

### `RESOURCE / RELEASE`

```json
{
  "schema_version": "1.0",
  "seq": 12,
  "time": 3.86,
  "kind": "RESOURCE",
  "event": "RELEASE",
  "level": "INFO",
  "source": "tracking",
  "message": "customer released counter",
  "data": {
    "resource": "counter",
    "process": "customer",
    "from": "counter",
    "to": "<IDLE>"
  }
}
```

### `BREAKPOINT / BREAKPOINT_HIT`

```json
{
  "schema_version": "1.0",
  "seq": 57,
  "time": 24.0,
  "kind": "BREAKPOINT",
  "event": "BREAKPOINT_HIT",
  "level": "INFO",
  "source": "lens",
  "message": "Breakpoint hit: fila cheia (hits=2)",
  "data": {
    "breakpoint_id": 3,
    "label": "fila cheia",
    "condition": "len(resources['Queue'].queue) > 5",
    "hit_count": 2,
    "pause_on_hit": true,
    "edge": "rising"
  }
}
```

## 7) Viewer Display Contract

Logs must be rendered as formatted text lines, never raw JSON.

Display template:

```text
[TIME] [KIND] MESSAGE | KEY=VALUE | KEY=VALUE
```

### Event-specific line examples

- `SIM / RESET`

```text
[0.00] [SIM] Simulation reset with seed 42
```

- `SIM / RUN_COMPLETE`

```text
[120.50] [SIM] Simulation complete
```

- `STEP / STEP_BEFORE`

```text
[0.00] [STEP 3 ➔] Timeout | triggering=customer | delay=1.5 | pottery_factory.py:37
[0.00] [STEP 4 ➔] Request | resource=counter | triggering=customer | pottery_factory.py:41
[3.86] [STEP 8 ➔] Release | resource=counter | pottery_factory.py:49
[3.86] [STEP 9 ➔] Process | process=customer | pottery_factory.py:50
```

- `STEP / STEP_AFTER`

```text
[3.86] [STEP 8 ✔] active=customer | pottery_factory.py:49
```

- `RESOURCE / REQUEST`

```text
[0.00] [RESOURCE] customer requested counter (<START> -> counter) | pottery_factory.py:41
```

- `RESOURCE / RELEASE`

```text
[3.86] [RESOURCE] customer released counter (counter -> <IDLE>) | pottery_factory.py:49
```

- `RESOURCE / PUT`

```text
[5.00] [RESOURCE] producer put into warehouse (<START> -> warehouse) | amount=5 | pottery_factory.py:64
```

- `RESOURCE / GET`

```text
[6.00] [RESOURCE] consumer got from warehouse (warehouse -> <IDLE>) | pottery_factory.py:71
```

## 8) Clickable Source Location in Viewer

When `data.file` and `data.line` are available, viewer rendering appends a location token in the format:

```text
<filename>:<line>
```

Example:

```text
[1.00] [STEP 3 ✔] active=worker | pottery_factory.py:78
```

The location token is clickable in the Tkinter log panel. Clicking it attempts to open the configured editor at the exact line.

Editor command resolution order:

1. Read `SIMPYLENS_EDITOR` (if set), otherwise default to `code`.
2. Invoke the editor via `subprocess`.
3. On failure, copy `file:line` to clipboard and print a terminal warning.

- `BREAKPOINT / BREAKPOINT_HIT`

```text
[24.00] [BREAKPOINT *] fila cheia | condition=len(resources['Queue'].queue) > 5 | hits=2
```

- `BREAKPOINT / BREAKPOINT_ERROR`

```text
[24.00] [BREAKPOINT X] fila cheia | condition=len(resources['Queue'].queue) > 5 | error=NameError: name 'resources' is not defined
```

- `STATUS / MESSAGE`

```text
[0.00] [STATUS] <free text>
```

### General Viewer Rules

1. Never show raw JSON in the log panel.
2. Preserve insertion order (`seq`) in display.
3. Use envelope `message` as the primary line text.
4. Show internal STEP events (`Condition`, `Initialize`) with lower visual emphasis.
