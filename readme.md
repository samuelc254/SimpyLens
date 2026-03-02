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
    manager = simpylens.Manager(model=setup, title="My Simulation")
    manager.viewer.mainloop()
```

## Public API

Main exports:
- `simpylens.Manager`
- `simpylens.Viewer`
- `simpylens.apply_patch`

Recommended entrypoint: `Manager`

```python
manager = simpylens.Manager(model=setup, title="Demo", with_ui=True)
manager.run()
manager.pause()
manager.step()
manager.reset()
```

You can also instantiate `Viewer` directly if preferred:

```python
viewer = simpylens.Viewer(model=setup, title="Demo")
viewer.mainloop()
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
bp_id = manager.add_breakpoint(
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
- `time`: current simulation time (`env.now`).
- `resources`: dictionary of named tracked resources.
- Named resources directly by variable name (when discoverable), for example `oven`, `machine`, etc.

Available safe builtins in expression mode:
- `abs`, `len`, `max`, `min`, `round`, `sum`

### Edge behavior

- `edge="none"`: hits whenever condition is true.
- `edge="rising"`: hits only on false -> true transition.
- `edge="falling"`: hits only on true -> false transition.

### Pause behavior

- `pause_on_hit=True`: simulation pauses when this breakpoint hits.
- `pause_on_hit=False`: hit is counted/logged but simulation keeps running.

You can change this at runtime:

```python
manager.set_breakpoint_pause_on_hit(bp_id, False)
```

### Manage breakpoints

```python
manager.set_breakpoint_enabled(bp_id, True)
manager.remove_breakpoint(bp_id)
manager.clear_breakpoints()
all_bps = manager.list_breakpoints()
```

### Breakpoint logs

The logger emits status events such as:
- `BREAKPOINT_HIT` (includes id, label, condition, hit count, pause_on_hit, edge)
- `BREAKPOINT_ERROR` (expression/callable evaluation errors)

## Running examples

Examples are available in `examples/`:

- `basic_sim.py`
- `medium_sim.py`
- `complex_sim.py`
- `cnc_sim.py`
- `queue_stress_sim.py`

From project root:

```bash
python examples/basic_sim.py
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