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
- Additive field evolution should remain backward compatible.

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
| `STEP` | `START` | `tracking` | Start of one process wake-up within a SimPy step. Multiple START entries may share the same `step`. |
| `STEP` | `ACTION` | `tracking` | Interaction within the current step (request/release/put/get). |
| `STEP` | `END` | `tracking` | End of one process wake-up within a SimPy step. Multiple END entries may share the same `step`. |
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

### `STEP / START`

```json
"data": {
  "step": 3,
  "sim_event": "Timeout",
  "process": "customer#1",
  "file": "/path/to/model.py",
  "line": 37
}
```

`process` is the unique process label from tracking state (same identity used in Task Viewer).
`file` and `line` are present when the callback resumes a process.
Broadcast events can generate multiple sequential `START` entries for the same `step`.

### `STEP / ACTION`

```json
"data": {
  "step": 3,
  "action_type": "request",
  "resource": "counter",
  "process": "customer#1",
  "from": "<START>",
  "to": "counter",
  "file": "/path/to/model.py",
  "line": 37
}
```

For release actions, `to` should be `"<IDLE>"`.

For Container/Store interactions, include optional fields only when present:

- `amount` for `Container`
- `item` for `Store` / `PriorityStore`
- `filter` for `FilterStore.get(...)`

### `STEP / END`

```json
"data": {
  "step": 3,
  "sim_event": "Timeout",
  "process": "customer#1",
  "target": "Request",
  "file": "/path/to/model.py",
  "line": 41
}
```

If the process terminated, `target` can be omitted and the message states termination.
`file` and `line` are captured after the step completes so they point to the new suspension location.
Broadcast events can generate multiple sequential `END` entries for the same `step`.

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

### `STEP / START`

```json
{
  "schema_version": "1.0",
  "seq": 5,
  "time": 0.0,
  "kind": "STEP",
  "event": "START",
  "level": "DEBUG",
  "source": "tracking",
  "message": "Waking up 'customer#1' (Triggered by: Timeout)",
  "data": {
    "step": 3,
    "sim_event": "Timeout",
    "process": "customer#1",
    "file": "examples/pottery_factory.py",
    "line": 37
  }
}
```

### `STEP / ACTION`

```json
{
  "schema_version": "1.0",
  "seq": 8,
  "time": 0.0,
  "kind": "STEP",
  "event": "ACTION",
  "level": "INFO",
  "source": "tracking",
  "message": "customer#1 requested counter",
  "data": {
    "step": 3,
    "action_type": "request",
    "resource": "counter",
    "process": "customer#1",
    "from": "<START>",
    "to": "counter"
  }
}
```

### `STEP / END`

```json
{
  "schema_version": "1.0",
  "seq": 9,
  "time": 0.0,
  "kind": "STEP",
  "event": "END",
  "level": "DEBUG",
  "source": "tracking",
  "message": "Process 'customer#1' suspended ➔ Yielding on Request",
  "data": {
    "step": 3,
    "sim_event": "Timeout",
    "process": "customer#1",
    "target": "Request",
    "file": "examples/pottery_factory.py",
    "line": 41
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
[TIME] [KIND] MESSAGE\tFILE:LINE
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

- `STEP / START`

```text
[0.00] [STEP 3 ▶] Waking up 'customer#1' (Triggered by: Condition)\tpottery_factory.py:37
[0.00] [STEP 3 ▶] Waking up 'supplier#2' (Triggered by: Condition)\tpottery_factory.py:61
[3.86] [STEP 8 ▶] Processing internal event: Release
```

- `STEP / ACTION`

```text
[0.00] [STEP 3 ↳] customer#1 requested counter\tpottery_factory.py:38
[5.00] [STEP 9 ↳] producer#4 put into warehouse | amount=5\tpottery_factory.py:64
```

- `STEP / END`

```text
[0.00] [STEP 3 ✔] Process 'customer#1' suspended ➔ Yielding on Request\tpottery_factory.py:41
[0.00] [STEP 3 ✔] Process 'supplier#2' suspended ➔ Yielding on Timeout(2)\tpottery_factory.py:66
[3.86] [STEP 8 ✔] Process 'customer#1' terminated\tpottery_factory.py:49
```

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

## 8) Clickable Source Location in Viewer

When `data.file` and `data.line` are available, viewer rendering appends a location token in the format:

```text
<filename>:<line>
```

Example:

```text
[1.00] [STEP 3 ✔] Process 'worker#7' suspended ➔ Yielding on Timeout(1)\tpottery_factory.py:78
```

The location token is clickable in the Tkinter log panel. Clicking it attempts to open the configured editor at the exact line.

Editor command resolution order:

1. Read `SIMPYLENS_EDITOR` (if set), otherwise default to `code`.
2. Invoke the editor via `subprocess`.
3. On failure, copy `file:line` to clipboard and print a terminal warning.

### General Viewer Rules

1. Never show raw JSON in the log panel.
2. Preserve insertion order (`seq`) in display.
