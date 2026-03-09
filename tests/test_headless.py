import pytest
import simpy
from simpylens import Lens


def dummy_model(env):
    def process_a(env):
        yield env.timeout(10)
        env.step_logs.append("Event at 10")
        yield env.timeout(10)
        env.step_logs.append("Event at 20")

    env.process(process_a(env))


def test_headless_execution_finishes():
    lens = Lens(model=dummy_model, gui=False)
    lens.run()

    logs = lens.get_logs()

    # Verify events
    events_at_10 = [log for log in logs if log.get("message") == "Event at 10"]
    events_at_20 = [log for log in logs if log.get("message") == "Event at 20"]

    assert len(events_at_10) == 1
    assert len(events_at_20) == 1
    assert lens.sim_ctrl.env.now == 20


def test_headless_breakpoints():
    lens = Lens(model=dummy_model, gui=False)

    # Setting breakpoint at env.now > 15
    bp_id = lens.add_breakpoint("env.now > 15", pause_on_hit=True)
    lens.run()

    # Should stop before the second timeout finishes, exactly when stepping over time 15?
    # Actually env.now jumps from 10 to 20. Breakpoint hits at 20.
    assert lens.sim_ctrl.env.now == 20

    logs = lens.get_logs()
    # verify breakpoint hit in logs
    bp_hits = [log for log in logs if log.get("event") == "BREAKPOINT_HIT"]
    assert len(bp_hits) == 1

    # Run again should finish
    lens.run()
    assert not lens.sim_ctrl.running


def test_multiple_breakpoints_same_step_all_counted():
    lens = Lens(model=dummy_model, gui=False)

    # Both conditions become true at env.now == 20 (same simulation step).
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
