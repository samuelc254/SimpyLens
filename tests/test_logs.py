"""
Tests for Lens log buffering – verifies that:
1. The default bounded log capacity is respected.
2. Custom log capacities are applied correctly.
3. Increasing capacity preserves existing buffered entries until new logs arrive.
"""

from simpylens import Lens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def long_model(env):
    def process_a(env):
        for i in range(2000):
            yield env.timeout(1)
            env.step_logs.append({"msg": f"Event {i}", "val": i})

    env.process(process_a(env))


# ---------------------------------------------------------------------------
# Log buffer capacity
# ---------------------------------------------------------------------------


def test_log_capacity():
    """The default log buffer must cap retained entries at 1000 messages."""
    lens = Lens(model=long_model, gui=False)

    lens.run()
    logs = lens.get_logs()

    assert len(logs) <= 1000

    found = any("Event 1999" in str(log) for log in logs[-20:])
    assert found


def test_set_log_capacity():
    """Changing log capacity must affect future buffering without dropping current entries."""
    lens = Lens(model=long_model, gui=False)
    lens.set_log_capacity(50)

    lens.run()
    logs = lens.get_logs()

    assert len(logs) == 50

    lens.set_log_capacity(100)
    logs_after_increase = lens.get_logs()
    assert len(logs_after_increase) == 50

    lens.reset()
    lens.run()
    logs_new = lens.get_logs()
    assert len(logs_new) == 100
