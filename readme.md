# SimpyLens

simpyLens is a zero-invasion visualization and debugging toolkit for simpy models.
It helps you inspect simulation behavior visually, without rewriting your business logic.

![simpyLens running](https://raw.githubusercontent.com/samuelc254/simpylens/main/assets/basic_sim.gif?v=20260302)

## What simpyLens does

- Visualizes simpy resources and flows in real time.
- Adds an interactive desktop UI (Tkinter) for run control and inspection.
- Supports programmatic and UI-driven breakpoints.
- Preserves your original simulation structure (monkey patching is internal).

## Project scope

simpyLens focuses on **model understanding, debugging, and presentation** for simpy simulations.

In scope:
- Resource-focused visualization (`Resource`, `PriorityResource`, `PreemptiveResource`, `Container`, `Store`, `PriorityStore`, `FilterStore`).
- Runtime controls (play, pause, step, reset, speed).
- Breakpoint engine with advanced behavior (`edge`, `pause_on_hit`, callable/expression conditions).
- Event logs for simulation/resource/breakpoint activity.

Out of scope (for now):
- 3D rendering.
- Graphical editing of the simulation structure.

## Requirements

- Python 3.8+
- simpy 4+
- Tkinter available in your Python installation (standard in most desktop Python distributions)

## Installation

Install from the project root:

```bash
pip install .
```

Development mode:

```bash
pip install -e .
```

## Quick start

```python
import simpy
import simpylens


def setup(env):
    machine = simpy.Resource(env, capacity=2)

    def worker(name):
        while True:
            with machine.request() as req:
                yield req
                yield env.timeout(2)

    env.process(worker("A"))
    env.process(worker("B"))


if __name__ == "__main__":
    lens = simpylens.Lens(model=setup, title="My Simulation")
    lens.show()
```

## Public API

Main exports:
- `simpylens.Lens`
- `simpylens.TrackingPatch`
- `simpylens.MetricsPatch`

Metrics patch activation:

```python
import simpylens

simpylens.MetricsPatch.apply()
```

Public readonly metrics exposed after applying `MetricsPatch`:

- Access pattern: `resource.metrics.<metric_name>`
- `Resource`, `PriorityResource`, `PreemptiveResource`:
`resource.metrics.queue_wait_time_min`, `resource.metrics.queue_wait_time_avg`, `resource.metrics.queue_wait_time_max`, `resource.metrics.usage_time_min`, `resource.metrics.usage_time_avg`, `resource.metrics.usage_time_max`, `resource.metrics.total_acquisitions`, `resource.metrics.idle_time_pct`, `resource.metrics.busy_time_pct`, `resource.metrics.concurrent_users_min`, `resource.metrics.concurrent_users_avg`, `resource.metrics.concurrent_users_max`
- `Store`, `PriorityStore`, `FilterStore`:
`resource.metrics.get_wait_time_min`, `resource.metrics.get_wait_time_avg`, `resource.metrics.get_wait_time_max`, `resource.metrics.put_wait_time_min`, `resource.metrics.put_wait_time_avg`, `resource.metrics.put_wait_time_max`, `resource.metrics.total_items_put`, `resource.metrics.total_items_got`, `resource.metrics.level_min`, `resource.metrics.level_avg`, `resource.metrics.level_max`
- `Container`:
`resource.metrics.get_wait_time_per_unit_min`, `resource.metrics.get_wait_time_per_unit_avg`, `resource.metrics.get_wait_time_per_unit_max`, `resource.metrics.put_wait_time_per_unit_min`, `resource.metrics.put_wait_time_per_unit_avg`, `resource.metrics.put_wait_time_per_unit_max`, `resource.metrics.total_amount_put`, `resource.metrics.total_amount_got`, `resource.metrics.level_min`, `resource.metrics.level_avg`, `resource.metrics.level_max`

Recommended entrypoint: `Lens`

```python
lens = simpylens.Lens(model=setup, title="Demo", gui=True, metrics=True)
lens.run()
lens.pause()
lens.step()
lens.reset()
```

## Interface guide

### Top controls

- **Play**: starts continuous execution.
- **Step**: executes one simpy event/tick.
- **Pause**: pauses execution.
- **Reset**: recreates environment and reruns `setup(env)`.
- **Speed slider**: controls pacing of updates/animations.

### Canvas interactions

- Mouse wheel: zoom in/out.
- Right button drag: pan viewport.
- Left button drag on resource block: manual reposition.
- Bottom-right button: center view.
- Right click on resource block: details popup and return-to-auto-layout option.

### Logs panel

- Toggle visibility (collapse/expand).
- Enable/disable logging.
- Clear logs.
- Search with next/previous navigation.
- Vertical resize handle.

### Breakpoints panel

- Resizable right-side panel.
- Collapsible side tab.
- Columns include id, label, pause flag, hit count, edge mode, and condition.
- Per-row pause toggle (`pause_on_hit`) directly in the table.
- Row highlight when simulation pauses due to that breakpoint.

## Breakpoints

Breakpoints can be created from Python and inspected/controlled in the UI.

### Add breakpoint

```python
bp_id = lens.add_breakpoint(
    condition="shipping.level >= 10",
    label="Shipping reached 10",
    enabled=True,
    pause_on_hit=True,
    edge="rising",  # one of: "none", "rising", "falling"
)
```

`condition` can be:
- `str`: evaluated as expression.
- `callable`: receives `context` dict and must return truthy/falsy.

If `label` is omitted/empty, it defaults to the condition text.

### Breakpoint context

Expression/callable context includes:
- `env`: simpy environment.
- `resources`: dictionary of named tracked resources.
- Named resources directly by variable name (when discoverable), for example `oven`, `machine`, etc.

Available safe builtins in expression mode:
- `abs`, `all`, `any`, `len`, `max`, `min`, `round`, `sum`

### Edge behavior

- `edge="none"`: hits whenever condition is true.
- `edge="rising"`: hits only on false -> true transition.
- `edge="falling"`: hits only on true -> false transition.

### Pause behavior

- `pause_on_hit=True`: simulation pauses when this breakpoint hits.
- `pause_on_hit=False`: hit is counted/logged but simulation keeps running.

You can change this at runtime:

```python
lens.set_breakpoint_pause_on_hit(bp_id, False)
```

### Manage breakpoints

```python
lens.set_breakpoint_enabled(bp_id, True)
lens.remove_breakpoint(bp_id)
lens.clear_breakpoints()
all_bps = lens.list_breakpoints()
```

### Breakpoint logs

The logger emits status events such as:
- `BREAKPOINT_HIT` (includes id, label, condition, hit count, pause_on_hit, edge)
- `BREAKPOINT_ERROR` (expression/callable evaluation errors)

## Running examples

Examples are available in `examples/`:

- `gas_station_refueling.py`
- `pottery_factory.py`
- `wafer_fabrication.py`

From project root:

```bash
python examples/pottery_factory.py
```

## Limitations and notes

- Visualization is tied to tracked simpy primitives and discovered names.
- Very high event rates can make GUI rendering the bottleneck.
- Breakpoint expressions should stay lightweight for best runtime performance.

## Contributing

Contributions are welcome.

Suggested workflow:
- Fork and create a feature branch.
- Add/adjust examples when behavior changes.
- Keep public API changes documented in this README.

## Credits

simpyLens is built on top of the [simpy](https://simpy.readthedocs.io/) library, an open-source discrete-event simulation framework for Python.  

## License

MIT. See `LICENSE`.