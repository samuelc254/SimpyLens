"""
Tests for TrackingPatch – verifies that:
1. Native SimPy functionality is NOT broken after patching.
2. Resources are registered in the environment's tracked_resources set.
3. Interaction logs (REQUEST, RELEASE, PUT, GET) are generated correctly.
4. Special cases such as FilterStore filters, PriorityResource ordering, and
   PreemptiveResource preemption all continue to work as expected.
5. TrackingPatch.apply() is idempotent.
"""

import json
import pytest
import simpy
from simpylens.tracking_patch import (
    TrackingPatch,
    TRACKED_RESOURCES_ATTR,
    STEP_LOGS_ATTR,
)

# Ensure patch is applied before any test in this module runs.
TrackingPatch.apply()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sim(model_fn):
    """Create a fresh environment, run model_fn, run to completion, return env."""
    env = simpy.Environment()
    model_fn(env)
    env.run()
    return env


def _parse_logs(env) -> list:
    """Return step_logs as a list of dicts (logs accumulate in env.step_logs
    when running without SimulationController)."""
    raw = getattr(env, STEP_LOGS_ATTR, [])
    result = []
    for entry in raw:
        if isinstance(entry, str):
            try:
                result.append(json.loads(entry))
            except json.JSONDecodeError:
                pass
        elif isinstance(entry, dict):
            result.append(entry)
    return result


def _events_of_kind(env, event_name: str) -> list:
    return [log for log in _parse_logs(env) if log.get("event") == event_name]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_tracking_patch_is_idempotent():
    """Calling TrackingPatch.apply() multiple times must not raise."""
    TrackingPatch.apply()
    TrackingPatch.apply()
    env = simpy.Environment()
    assert hasattr(env, TRACKED_RESOURCES_ATTR)
    assert hasattr(env, STEP_LOGS_ATTR)


# ---------------------------------------------------------------------------
# Environment initialisation
# ---------------------------------------------------------------------------


def test_new_environment_has_tracking_state():
    env = simpy.Environment()
    assert hasattr(env, TRACKED_RESOURCES_ATTR)
    assert hasattr(env, STEP_LOGS_ATTR)
    assert hasattr(env, "pending_transfers")
    assert hasattr(env, "process_locations")


def test_step_count_starts_at_zero():
    env = simpy.Environment()
    assert env.step_count == 0


def test_step_count_increments():
    steps = []

    def model(env):
        def proc(env):
            yield env.timeout(1)
            steps.append(env.step_count)
            yield env.timeout(1)
            steps.append(env.step_count)

        env.process(proc(env))

    env = _sim(model)
    assert len(steps) == 2
    assert steps[1] > steps[0]
    assert env.step_count >= 2


# ---------------------------------------------------------------------------
# Resource registration in tracked_resources
# ---------------------------------------------------------------------------


def test_resource_registered_in_tracked_resources():
    env = simpy.Environment()
    res = simpy.Resource(env, capacity=1)
    assert res in list(env.tracked_resources)


def test_priority_resource_registered():
    env = simpy.Environment()
    res = simpy.PriorityResource(env, capacity=2)
    assert res in list(env.tracked_resources)


def test_preemptive_resource_registered():
    env = simpy.Environment()
    res = simpy.PreemptiveResource(env, capacity=1)
    assert res in list(env.tracked_resources)


def test_container_registered():
    env = simpy.Environment()
    cont = simpy.Container(env, capacity=100)
    assert cont in list(env.tracked_resources)


def test_store_registered():
    env = simpy.Environment()
    store = simpy.Store(env)
    assert store in list(env.tracked_resources)


def test_filter_store_registered():
    env = simpy.Environment()
    store = simpy.FilterStore(env)
    assert store in list(env.tracked_resources)


def test_priority_store_registered():
    env = simpy.Environment()
    store = simpy.PriorityStore(env)
    assert store in list(env.tracked_resources)


def test_multiple_resources_all_tracked():
    env = simpy.Environment()
    r1 = simpy.Resource(env, capacity=1)
    r2 = simpy.Resource(env, capacity=2)
    tracked = list(env.tracked_resources)
    assert r1 in tracked
    assert r2 in tracked


# ---------------------------------------------------------------------------
# Visual name assignment
# ---------------------------------------------------------------------------


def test_resource_has_visual_name():
    env = simpy.Environment()
    res = simpy.Resource(env, capacity=1)
    assert isinstance(res.visual_name, str)
    assert len(res.visual_name) > 0


def test_container_has_visual_type():
    env = simpy.Environment()
    cont = simpy.Container(env, capacity=50)
    assert cont.visual_type == "CONTAINER"


def test_store_has_visual_type():
    env = simpy.Environment()
    store = simpy.Store(env)
    assert store.visual_type == "STORE"


def test_filter_store_has_visual_type():
    env = simpy.Environment()
    store = simpy.FilterStore(env)
    assert store.visual_type == "FILTER_STORE"


# ---------------------------------------------------------------------------
# Interaction log generation (REQUEST / RELEASE)
# ---------------------------------------------------------------------------


def test_resource_request_generates_log():
    def model(env):
        res = simpy.Resource(env, capacity=1)

        def worker(env):
            req = res.request()
            yield req
            res.release(req)

        env.process(worker(env))

    env = _sim(model)
    assert len(_events_of_kind(env, "REQUEST")) >= 1


def test_resource_release_generates_log():
    def model(env):
        res = simpy.Resource(env, capacity=1)

        def worker(env):
            req = res.request()
            yield req
            yield env.timeout(1)
            res.release(req)

        env.process(worker(env))

    env = _sim(model)
    assert len(_events_of_kind(env, "RELEASE")) >= 1


def test_request_log_contains_resource_and_process():
    def model(env):
        env._res = simpy.Resource(env, capacity=1)

        def worker(env):
            req = env._res.request()
            yield req
            env._res.release(req)

        env.process(worker(env))

    env = _sim(model)
    request_logs = _events_of_kind(env, "REQUEST")
    assert len(request_logs) >= 1
    entry = request_logs[0]
    assert "resource" in entry.get("data", {})
    assert "process" in entry.get("data", {})


# ---------------------------------------------------------------------------
# Interaction log generation (PUT / GET)
# ---------------------------------------------------------------------------


def test_store_put_generates_log():
    def model(env):
        store = simpy.Store(env)

        def producer(env):
            yield store.put("item")

        env.process(producer(env))

    env = _sim(model)
    assert len(_events_of_kind(env, "PUT")) >= 1


def test_store_get_generates_log():
    def model(env):
        store = simpy.Store(env)

        def producer(env):
            yield store.put("item")

        def consumer(env):
            yield env.timeout(1)
            yield store.get()

        env.process(producer(env))
        env.process(consumer(env))

    env = _sim(model)
    assert len(_events_of_kind(env, "GET")) >= 1


def test_container_put_and_get_generate_logs():
    def model(env):
        cont = simpy.Container(env, capacity=100, init=0)

        def producer(env):
            yield cont.put(50)

        def consumer(env):
            yield env.timeout(1)
            yield cont.get(20)

        env.process(producer(env))
        env.process(consumer(env))

    env = _sim(model)
    assert len(_events_of_kind(env, "PUT")) >= 1
    assert len(_events_of_kind(env, "GET")) >= 1


# ---------------------------------------------------------------------------
# Native SimPy behaviour preserved after patching
# ---------------------------------------------------------------------------


def test_resource_native_request_release_preserved():
    """Tracking patch must not break the fundamental request/release cycle."""
    acquired = []

    def model(env):
        res = simpy.Resource(env, capacity=1)

        def worker(env, name):
            req = res.request()
            yield req
            acquired.append(name)
            yield env.timeout(2)
            res.release(req)

        env.process(worker(env, "A"))
        env.process(worker(env, "B"))

    env = _sim(model)
    assert set(acquired) == {"A", "B"}
    assert env.now == 4  # A runs 0-2, B runs 2-4


def test_filter_store_native_filter_preserved():
    """TrackingPatch must not interfere with FilterStore's filter callable."""
    result = []

    def model(env):
        store = simpy.FilterStore(env)

        def producer(env):
            for v in [1, 2, 3, 4]:
                yield store.put(v)

        def consumer(env):
            yield env.timeout(1)
            item = yield store.get(lambda x: x % 2 == 0)
            result.append(item)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == [2]


def test_filter_store_get_blocks_until_match():
    """Consumer waiting for a specific item must block until it appears."""
    result = []

    def model(env):
        store = simpy.FilterStore(env)

        def producer(env):
            yield store.put("odd")
            yield env.timeout(5)
            yield store.put("even2")

        def consumer(env):
            item = yield store.get(lambda x: "even" in x)
            result.append((item, env.now))

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == [("even2", 5)]


def test_priority_resource_priority_order_preserved():
    order = []

    def model(env):
        res = simpy.PriorityResource(env, capacity=1)

        def holder(env):
            req = res.request(priority=0)
            yield req
            yield env.timeout(10)
            res.release(req)

        def waiter(env, priority, name):
            yield env.timeout(1)
            req = res.request(priority=priority)
            yield req
            order.append(name)
            res.release(req)

        env.process(holder(env))
        env.process(waiter(env, 5, "low"))
        env.process(waiter(env, 1, "high"))

    _sim(model)
    assert order == ["high", "low"]


def test_preemptive_resource_preemption_preserved():
    log = []

    def model(env):
        res = simpy.PreemptiveResource(env, capacity=1)

        def low(env):
            req = res.request(priority=10)
            yield req
            try:
                yield env.timeout(20)
            except simpy.Interrupt:
                log.append("preempted")
                res.release(req)

        def high(env):
            yield env.timeout(5)
            req = res.request(priority=1, preempt=True)
            yield req
            yield env.timeout(1)
            res.release(req)
            log.append("high_done")

        env.process(low(env))
        env.process(high(env))

    _sim(model)
    assert "preempted" in log
    assert "high_done" in log


def test_store_fifo_order_preserved():
    result = []

    def model(env):
        store = simpy.Store(env)

        def producer(env):
            for item in ["alpha", "beta", "gamma"]:
                yield store.put(item)

        def consumer(env):
            yield env.timeout(1)
            for _ in range(3):
                item = yield store.get()
                result.append(item)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == ["alpha", "beta", "gamma"]


def test_container_level_integrity():
    """put/get must keep Container.level consistent after patching."""
    snapshots = []

    def model(env):
        cont = simpy.Container(env, capacity=100, init=10)

        def worker(env):
            yield cont.put(30)
            snapshots.append(cont.level)  # should be 40
            yield env.timeout(1)
            yield cont.get(15)
            snapshots.append(cont.level)  # should be 25

        env.process(worker(env))

    _sim(model)
    assert snapshots == [pytest.approx(40.0), pytest.approx(25.0)]


# ---------------------------------------------------------------------------
# Step log structure
# ---------------------------------------------------------------------------


def test_step_before_event_logged():
    def model(env):
        def proc(env):
            yield env.timeout(1)

        env.process(proc(env))

    env = _sim(model)
    step_befores = _events_of_kind(env, "STEP_BEFORE")
    assert len(step_befores) >= 1


def test_step_after_event_always_logged():
    def model(env):
        def proc(env):
            yield env.timeout(1)

        env.process(proc(env))

    env = _sim(model)
    step_afters = _events_of_kind(env, "STEP_AFTER")
    assert len(step_afters) >= 1


def test_step_after_includes_source_location_when_process_resumes():
    def model(env):
        def proc(env):
            yield env.timeout(1)
            yield env.timeout(1)

        env.process(proc(env))

    env = _sim(model)
    step_afters = _events_of_kind(env, "STEP_AFTER")
    entries_with_location = [entry for entry in step_afters if isinstance(entry.get("data", {}).get("line"), int) and entry.get("data", {}).get("file")]

    assert entries_with_location
    assert any(str(entry["data"]["file"]).endswith("test_tracking_patch.py") for entry in entries_with_location)


def test_step_logs_have_required_schema_fields():
    def model(env):
        def proc(env):
            yield env.timeout(1)

        env.process(proc(env))

    env = _sim(model)
    for entry in _parse_logs(env):
        assert "schema_version" in entry
        assert "kind" in entry
        assert "event" in entry
        assert "time" in entry
        assert "level" in entry
