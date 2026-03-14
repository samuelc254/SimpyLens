# SimpyLens: Simpy Visualization and Debugging Toolkit

[![PyPI version](https://img.shields.io/pypi/v/simpylens.svg)](https://pypi.org/project/simpylens/)
[![Python versions](https://img.shields.io/pypi/pyversions/simpylens.svg)](https://pypi.org/project/simpylens/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/samuelc254/SimpyLens/blob/main/LICENSE)

SimpyLens is a low-intrusion toolkit for SimPy model visualization, debugging, and runtime inspection. It helps developers understand queueing behavior, resource contention, and process flow in real time without rewriting simulation business logic.

## SimPy Visual Demos

### Full Simulation Debugging Workflow

![SimPy discrete-event simulation visualization and debugging workflow in SimpyLens](https://raw.githubusercontent.com/samuelc254/simpylens/main/assets/pottery_factory.gif)

`assets/pottery_factory.gif` shows the full SimpyLens interface for discrete-event simulation debugging: runtime controls, process flow, resource movement, and live inspection.
It is useful for users searching for a SimPy visual debugger, queueing simulation viewer, or simulation runtime inspection tool.

### Manual Resource Layout for Process Storytelling

![Manual resource layout for SimPy process flow visualization in SimpyLens](https://raw.githubusercontent.com/samuelc254/simpylens/main/assets/manual_layout.gif)

`assets/manual_layout.gif` demonstrates manual resource positioning so teams can present and analyze process flow with a clearer mental model.
This is especially relevant for simulation demos, teaching, and operations reviews where layout readability matters.

## Key Features

- Real-time visualization for SimPy resources and process interactions.
- Runtime controls for play, step, pause, reset, and speed.
- Breakpoints with expression/callable conditions and edge modes.
- Structured logs for simulation, step lifecycle, resources, and breakpoints.
- Headless mode for tests and CI.
- Optional metrics collection with read-only resource metrics.

## Installation

```bash
pip install simpylens
```

## Quickstart

```python
import simpy
import simpylens


def model(env):
    server = simpy.Resource(env, capacity=1)

    def customer():
        with server.request() as req:
            yield req
            yield env.timeout(3)

    env.process(customer())


lens = simpylens.Lens(model=model, gui=True, seed=42)
lens.show()
```

## SimPy Examples Included

Examples are in `examples/` and grouped by origin.

Adapted from official [simpy](https://simpy.readthedocs.io/) examples/tutorial lineage:
- `examples/bank_renege.py`
- `examples/gas_station_refueling.py`

Original SimpyLens examples:
- `examples/pottery_factory.py`
- `examples/wafer_fabrication.py`

## FAQ

### Is SimpyLens a SimPy debugger?

Yes. SimpyLens provides breakpoint-based debugging, structured event logs, and step-by-step runtime inspection for SimPy simulations.

### Can I visualize SimPy resources in real time?

Yes. SimpyLens visualizes `Resource`, `Container`, and `Store` families, including queue/load behavior and process flow.

### Can SimpyLens run in headless mode for automated testing?

Yes. Use `Lens(gui=False)` to run simulations and assertions in tests or CI pipelines.

### Does SimpyLens require rewriting my simulation model?

No. SimpyLens is designed for low-intrusion integration with your existing SimPy setup function.

## Contributing

Contributions are welcome.

Suggested workflow:
1. Fork the repository.
2. Create a feature branch.
3. Add or update tests and examples.
4. Submit a pull request with a clear change description.

## Documentation

- [Architecture](https://github.com/samuelc254/SimpyLens/blob/main/docs/architecture.md)
- [API Reference](https://github.com/samuelc254/SimpyLens/blob/main/docs/api_reference.md)
- [Logging Schema](https://github.com/samuelc254/SimpyLens/blob/main/docs/logging_schema.md)