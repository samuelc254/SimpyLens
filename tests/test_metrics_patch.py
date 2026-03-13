"""
Tests for MetricsPatch – verifies that:
1. Native SimPy functionality is NOT broken after patching.
2. Metrics are calculated correctly for all resource families.
3. MetricsPatch.apply() is idempotent.
"""

import pytest
import simpy
from simpylens.metrics_patch import MetricsPatch

# Ensure patch is applied before any test in this module runs.
MetricsPatch.apply()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _sim(model_fn):
    """Create a fresh environment, run model_fn, run to completion, return env."""
    env = simpy.Environment()
    model_fn(env)
    env.run()
    return env


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_metrics_patch_is_idempotent():
    """Calling MetricsPatch.apply() multiple times must not raise or double-patch."""
    MetricsPatch.apply()
    MetricsPatch.apply()
    env = simpy.Environment()
    res = simpy.Resource(env, capacity=1)
    assert hasattr(res, "metrics")


# ---------------------------------------------------------------------------
# Resource – native behaviour
# ---------------------------------------------------------------------------


def test_resource_native_request_release():
    """A patched Resource must still complete a simple request/release cycle."""
    finished = []

    def model(env):
        res = simpy.Resource(env, capacity=1)

        def worker(env):
            req = res.request()
            yield req
            yield env.timeout(5)
            res.release(req)
            finished.append(env.now)

        env.process(worker(env))

    env = _sim(model)
    assert env.now == 5
    assert finished == [5]


def test_resource_capacity_respected():
    """Capacity 1 must serialise two concurrent requests."""
    order = []

    def model(env):
        res = simpy.Resource(env, capacity=1)

        def worker(env, name, start):
            yield env.timeout(start)
            req = res.request()
            yield req
            order.append((name, env.now))
            yield env.timeout(3)
            res.release(req)

        env.process(worker(env, "A", 0))
        env.process(worker(env, "B", 0))

    _sim(model)
    # A and B both start at t=0 but only one holds at a time
    times = [t for _, t in order]
    assert times[0] == 0  # first gets in immediately
    assert times[1] == 3  # second must wait for A to finish


# ---------------------------------------------------------------------------
# Resource – metrics correctness
# ---------------------------------------------------------------------------


def test_resource_metrics_total_acquisitions_and_releases():
    def model(env):
        env._res = simpy.Resource(env, capacity=2)

        def worker(env):
            req = env._res.request()
            yield req
            yield env.timeout(1)
            env._res.release(req)

        for _ in range(3):
            env.process(worker(env))

    env = _sim(model)
    assert env._res.total_acquisitions == 3
    assert env._res.total_releases == 3


def test_resource_queue_wait_time():
    """2nd requester on capacity-1 resource must accumulate wait time."""

    def model(env):
        env._res = simpy.Resource(env, capacity=1)

        def holder(env):
            req = env._res.request()
            yield req
            yield env.timeout(10)
            env._res.release(req)

        def waiter(env):
            yield env.timeout(1)  # arrives after holder
            req = env._res.request()
            yield req
            env._res.release(req)

        env.process(holder(env))
        env.process(waiter(env))

    env = _sim(model)
    # holder gets resource at t=0 (wait=0); waiter gets it at t=10 (wait=9)
    # queue_wait_time_min is the minimum across ALL requests, including the
    # holder whose wait was 0. The relevant assertion is on max and avg.
    assert env._res.queue_wait_time_max == pytest.approx(9.0)
    assert env._res.queue_wait_time_avg == pytest.approx(4.5)
    assert env._res.total_acquisitions == 2


def test_resource_busy_time_pct_full():
    """Resource held for its entire lifetime → busy_time_pct ≈ 100."""

    def model(env):
        env._res = simpy.Resource(env, capacity=1)

        def worker(env):
            req = env._res.request()
            yield req
            yield env.timeout(10)
            env._res.release(req)

        env.process(worker(env))

    env = _sim(model)
    assert env._res.busy_time_pct == pytest.approx(100.0, abs=1.0)
    assert env._res.idle_time_pct == pytest.approx(0.0, abs=1.0)


def test_resource_metrics_accessor_is_read_only():
    env = simpy.Environment()
    res = simpy.Resource(env, capacity=1)
    with pytest.raises(AttributeError):
        res.metrics.total_acquisitions = 999


def test_resource_concurrent_users_max():
    """Two simultaneous users on capacity-2 resource → concurrent_users_max == 2."""

    def model(env):
        env._res = simpy.Resource(env, capacity=2)

        def worker(env):
            req = env._res.request()
            yield req
            yield env.timeout(5)
            env._res.release(req)

        env.process(worker(env))
        env.process(worker(env))

    env = _sim(model)
    assert env._res.concurrent_users_max == 2


# ---------------------------------------------------------------------------
# PriorityResource – native behaviour + metrics
# ---------------------------------------------------------------------------


def test_priority_resource_native_priority_order():
    """Lower priority number → served first when capacity becomes available."""
    served = []

    def model(env):
        res = simpy.PriorityResource(env, capacity=1)

        def holder(env):
            req = res.request(priority=0)
            yield req
            yield env.timeout(10)
            res.release(req)

        def waiter(env, priority, name):
            yield env.timeout(1)  # arrive while holder is running
            req = res.request(priority=priority)
            yield req
            served.append(name)
            res.release(req)

        env.process(holder(env))
        env.process(waiter(env, priority=5, name="low"))
        env.process(waiter(env, priority=1, name="high"))

    _sim(model)
    assert served == ["high", "low"]


def test_priority_resource_metrics():
    def model(env):
        env._res = simpy.PriorityResource(env, capacity=1)

        def worker(env):
            req = env._res.request(priority=1)
            yield req
            yield env.timeout(3)
            env._res.release(req)

        env.process(worker(env))

    env = _sim(model)
    assert env._res.total_acquisitions == 1
    assert env._res.total_releases == 1
    assert env._res.usage_time_min == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# PreemptiveResource – native preemption + metrics not broken
# ---------------------------------------------------------------------------


def test_preemptive_resource_native_preemption():
    """Higher-priority (lower number) process must preempt a running one."""
    log = []

    def model(env):
        res = simpy.PreemptiveResource(env, capacity=1)

        def low(env):
            req = res.request(priority=10)
            yield req
            try:
                yield env.timeout(20)
                log.append("low_done")
            except simpy.Interrupt:
                log.append("low_preempted")
                res.release(req)

        def high(env):
            yield env.timeout(5)
            req = res.request(priority=1, preempt=True)
            yield req
            yield env.timeout(5)
            res.release(req)
            log.append("high_done")

        env.process(low(env))
        env.process(high(env))

    _sim(model)
    assert "low_preempted" in log
    assert "high_done" in log
    assert "low_done" not in log


def test_preemptive_resource_metrics_not_broken():
    """Metrics attributes must exist and be accessible after preemption."""

    def model(env):
        env._res = simpy.PreemptiveResource(env, capacity=1)

        def low(env):
            req = env._res.request(priority=10)
            yield req
            try:
                yield env.timeout(20)
            except simpy.Interrupt:
                pass
            env._res.release(req)

        def high(env):
            yield env.timeout(5)
            req = env._res.request(priority=1, preempt=True)
            yield req
            yield env.timeout(5)
            env._res.release(req)

        env.process(low(env))
        env.process(high(env))

    env = _sim(model)
    assert env._res.total_acquisitions >= 1
    assert env._res.total_releases >= 1
    assert hasattr(env._res, "metrics")


# ---------------------------------------------------------------------------
# FilterStore – native filter + metrics
# ---------------------------------------------------------------------------


def test_filter_store_native_filter():
    """FilterStore.get(filter=...) must still honour the filter after patching."""
    result = []

    def model(env):
        store = simpy.FilterStore(env)

        def producer(env):
            yield store.put("apple")
            yield store.put("banana")
            yield store.put("cherry")

        def consumer(env):
            yield env.timeout(1)
            item = yield store.get(lambda x: x.startswith("b"))
            result.append(item)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == ["banana"]


def test_filter_store_metrics():
    def model(env):
        env._store = simpy.FilterStore(env)

        def producer(env):
            yield env._store.put("x")
            yield env._store.put("y")

        def consumer(env):
            yield env.timeout(1)
            yield env._store.get(lambda _: True)
            yield env._store.get(lambda _: True)

        env.process(producer(env))
        env.process(consumer(env))

    env = _sim(model)
    assert env._store.total_items_put == 2
    assert env._store.total_items_got == 2


def test_filter_store_get_waits_for_matching_item():
    """Consumer waiting for an even number must block until 2 arrives."""
    result = []

    def model(env):
        store = simpy.FilterStore(env)

        def producer(env):
            yield store.put(1)
            yield env.timeout(5)
            yield store.put(2)

        def consumer(env):
            item = yield store.get(lambda x: x % 2 == 0)
            result.append((item, env.now))

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == [(2, 5)]


# ---------------------------------------------------------------------------
# PriorityStore – native priority order + metrics
# ---------------------------------------------------------------------------


def test_priority_store_native_priority_order():
    """Items retrieved from PriorityStore must come out in priority order."""
    result = []

    def model(env):
        store = simpy.PriorityStore(env)

        def producer(env):
            yield store.put(simpy.PriorityItem(priority=3, item="c"))
            yield store.put(simpy.PriorityItem(priority=1, item="a"))
            yield store.put(simpy.PriorityItem(priority=2, item="b"))

        def consumer(env):
            yield env.timeout(1)
            for _ in range(3):
                pitem = yield store.get()
                result.append(pitem.item)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == ["a", "b", "c"]


def test_priority_store_metrics():
    def model(env):
        env._store = simpy.PriorityStore(env)

        def producer(env):
            for i in range(4):
                yield env._store.put(simpy.PriorityItem(priority=i, item=str(i)))

        def consumer(env):
            yield env.timeout(1)
            for _ in range(4):
                yield env._store.get()

        env.process(producer(env))
        env.process(consumer(env))

    env = _sim(model)
    assert env._store.total_items_put == 4
    assert env._store.total_items_got == 4


# ---------------------------------------------------------------------------
# Container – native put/get + metrics
# ---------------------------------------------------------------------------


def test_container_native_put_get():
    levels = []

    def model(env):
        env._cont = simpy.Container(env, capacity=100, init=0)

        def producer(env):
            yield env._cont.put(50)
            levels.append(env._cont.level)

        def consumer(env):
            yield env.timeout(1)
            yield env._cont.get(30)
            levels.append(env._cont.level)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert levels[0] == pytest.approx(50.0)
    assert levels[1] == pytest.approx(20.0)


def test_container_metrics():
    def model(env):
        env._cont = simpy.Container(env, capacity=100, init=0)

        def worker(env):
            yield env._cont.put(40)
            yield env.timeout(5)
            yield env._cont.get(20)

        env.process(worker(env))

    env = _sim(model)
    assert env._cont.total_amount_put == pytest.approx(40.0)
    assert env._cont.total_amount_got == pytest.approx(20.0)


def test_container_get_blocks_until_level_available():
    """get() on empty container must block until put() provides enough level."""
    result = []

    def model(env):
        cont = simpy.Container(env, capacity=100, init=0)

        def consumer(env):
            yield cont.get(10)
            result.append(env.now)

        def producer(env):
            yield env.timeout(7)
            yield cont.put(10)

        env.process(consumer(env))
        env.process(producer(env))

    _sim(model)
    assert result == [7]


# ---------------------------------------------------------------------------
# Store – native behaviour + metrics
# ---------------------------------------------------------------------------


def test_store_native_fifo_order():
    """Plain Store must return items in FIFO order."""
    result = []

    def model(env):
        store = simpy.Store(env)

        def producer(env):
            for item in ["first", "second", "third"]:
                yield store.put(item)

        def consumer(env):
            yield env.timeout(1)
            for _ in range(3):
                item = yield store.get()
                result.append(item)

        env.process(producer(env))
        env.process(consumer(env))

    _sim(model)
    assert result == ["first", "second", "third"]


def test_store_metrics():
    def model(env):
        env._store = simpy.Store(env)

        def producer(env):
            for i in range(5):
                yield env._store.put(i)

        def consumer(env):
            yield env.timeout(1)
            for _ in range(3):
                yield env._store.get()

        env.process(producer(env))
        env.process(consumer(env))

    env = _sim(model)
    assert env._store.total_items_put == 5
    assert env._store.total_items_got == 3
    assert env._store.level_max == pytest.approx(5.0)
