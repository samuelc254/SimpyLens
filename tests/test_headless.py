"""
Tests for headless Lens execution – verifies that:
1. Headless execution runs the model to completion.
2. Breakpoints pause execution correctly in headless mode.
3. Multiple breakpoints triggered in the same step are all counted.
"""

from simpylens import Lens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def dummy_model(env):
    def process_a(env):
        yield env.timeout(10)
        env.step_logs.append("Event at 10")
        yield env.timeout(10)
        env.step_logs.append("Event at 20")

    env.process(process_a(env))


# ---------------------------------------------------------------------------
# Headless execution
# ---------------------------------------------------------------------------


def test_headless_execution_finishes():
    """Headless execution must run the model to completion and preserve logs."""
    lens = Lens(model=dummy_model, gui=False)
    lens.run()

    logs = lens.get_logs()

    events_at_10 = [log for log in logs if log.get("message") == "Event at 10"]
    events_at_20 = [log for log in logs if log.get("message") == "Event at 20"]

    assert len(events_at_10) == 1
    assert len(events_at_20) == 1
    assert lens.sim_ctrl.env.now == 20


def test_headless_breakpoints():
    """A breakpoint in headless mode must pause execution on the matching step."""
    lens = Lens(model=dummy_model, gui=False)

    lens.add_breakpoint("env.now > 15", pause_on_hit=True)
    lens.run()

    # The simulation jumps from t=10 to t=20, so the breakpoint triggers at 20.
    assert lens.sim_ctrl.env.now == 20

    logs = lens.get_logs()
    bp_hits = [log for log in logs if log.get("event") == "BREAKPOINT_HIT"]
    assert len(bp_hits) == 1

    lens.run()
    assert not lens.sim_ctrl.running


def test_multiple_breakpoints_same_step_all_counted():
    """All breakpoints matched in the same simulation step must be recorded."""
    lens = Lens(model=dummy_model, gui=False)

    bp_first = lens.add_breakpoint("env.now >= 20", label="Now 20", pause_on_hit=False)
    bp_second = lens.add_breakpoint("env.now > 15", label="Now > 15", pause_on_hit=True)

    lens.run()

    assert lens.sim_ctrl.env.now == 20

    bp_state = {bp.id: bp for bp in lens.list_breakpoints()}
    assert bp_state[bp_first].hit_count == 1
    assert bp_state[bp_second].hit_count == 1

    hit_logs = [log for log in lens.get_logs() if log.get("event") == "BREAKPOINT_HIT"]
    ids = {entry.get("data", {}).get("breakpoint_id") for entry in hit_logs}
    assert bp_first in ids
    assert bp_second in ids
