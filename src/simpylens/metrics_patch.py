import weakref

import simpy


class _MetricsAccessor:
    __slots__ = ("_owner", "_names")

    def __init__(self, owner, names):
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_names", tuple(names))

    def __getattr__(self, name):
        if name in self._names:
            return getattr(self._owner, name)
        raise AttributeError(name)

    def __setattr__(self, _name, _value):
        raise AttributeError("metrics accessor is read-only")

    def __dir__(self):
        return sorted(set(self._names))


class _SampleStats:
    __slots__ = ("count", "total", "minimum", "maximum")

    def __init__(self):
        self.count = 0
        self.total = 0.0
        self.minimum = None
        self.maximum = None

    def add(self, value):
        v = float(value)
        self.count += 1
        self.total += v
        self.minimum = v if self.minimum is None else min(self.minimum, v)
        self.maximum = v if self.maximum is None else max(self.maximum, v)

    @property
    def avg(self):
        return 0.0 if self.count == 0 else self.total / self.count

    @property
    def min(self):
        return 0.0 if self.minimum is None else self.minimum

    @property
    def max(self):
        return 0.0 if self.maximum is None else self.maximum


class _TimeWeightedStats:
    __slots__ = ("start_time", "last_time", "current", "integral", "minimum", "maximum")

    def __init__(self, now, initial_value):
        initial = float(initial_value)
        start = float(now)
        self.start_time = start
        self.last_time = start
        self.current = initial
        self.integral = 0.0
        self.minimum = initial
        self.maximum = initial

    def observe(self, now, new_value):
        ts = float(now)
        dt = ts - self.last_time
        if dt > 0:
            self.integral += self.current * dt
        self.last_time = ts
        self.current = float(new_value)
        self.minimum = min(self.minimum, self.current)
        self.maximum = max(self.maximum, self.current)

    def average(self, now):
        ts = float(now)
        dt = ts - self.last_time
        integral = self.integral + (self.current * dt if dt > 0 else 0.0)
        total = ts - self.start_time
        if total <= 0:
            return self.current
        return integral / total

    def minimum_value(self):
        return self.minimum

    def maximum_value(self):
        return self.maximum


def _attach_event_callback(event, callback):
    callbacks = getattr(event, "callbacks", None)
    if callbacks is None:
        callback(event)
        return event

    def _wrapped(evt):
        callback(evt)

    callbacks.append(_wrapped)
    return event


def _read_amount(args, kwargs):
    if args:
        return float(args[0])
    if "amount" in kwargs:
        return float(kwargs["amount"])
    return 1.0


class _ResourceMetricsMixin:
    _metrics_names = (
        "queue_wait_time_min",
        "queue_wait_time_avg",
        "queue_wait_time_max",
        "request_queue_min",
        "request_queue_avg",
        "request_queue_max",
        "usage_time_min",
        "usage_time_avg",
        "usage_time_max",
        "total_acquisitions",
        "total_releases",
        "idle_time_pct",
        "busy_time_pct",
        "concurrent_users_min",
        "concurrent_users_avg",
        "concurrent_users_max",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = getattr(self._env, "now", 0.0)
        current_users = int(getattr(self, "count", 0))

        self._metrics_queue_wait = _SampleStats()
        self._metrics_usage_time = _SampleStats()
        self._metrics_total_acquisitions = 0
        self._metrics_total_releases = 0

        self._metrics_concurrent = _TimeWeightedStats(now, current_users)
        self._metrics_busy = _TimeWeightedStats(now, 1.0 if current_users > 0 else 0.0)
        self._metrics_request_queue = _TimeWeightedStats(now, float(len(getattr(self, "queue", []))))

        self._metrics_request_started_at = weakref.WeakKeyDictionary()
        self._metrics_active_since = weakref.WeakKeyDictionary()

    def request(self, *args, **kwargs):
        request_event = super().request(*args, **kwargs)
        self._metrics_request_started_at[request_event] = float(self._env.now)
        self._metrics_request_queue.observe(float(self._env.now), float(len(getattr(self, "queue", []))))

        def _on_request_granted(event):
            now = float(self._env.now)
            started_at = self._metrics_request_started_at.pop(event, None)
            if started_at is not None:
                self._metrics_queue_wait.add(now - started_at)

            process = getattr(event, "proc", None)
            if process is not None:
                self._metrics_active_since[process] = now

            self._metrics_total_acquisitions += 1
            current_users = int(getattr(self, "count", 0))
            self._metrics_concurrent.observe(now, current_users)
            self._metrics_busy.observe(now, 1.0 if current_users > 0 else 0.0)
            self._metrics_request_queue.observe(now, float(len(getattr(self, "queue", []))))

        return _attach_event_callback(request_event, _on_request_granted)

    def release(self, *args, **kwargs):
        request_event = args[0] if args else kwargs.get("request")
        process = getattr(request_event, "proc", None) if request_event is not None else None
        release_event = super().release(*args, **kwargs)

        def _on_release_done(_event):
            now = float(self._env.now)
            self._metrics_total_releases += 1
            if process is not None:
                acquired_at = self._metrics_active_since.pop(process, None)
                if acquired_at is not None:
                    self._metrics_usage_time.add(now - acquired_at)

            current_users = int(getattr(self, "count", 0))
            self._metrics_concurrent.observe(now, current_users)
            self._metrics_busy.observe(now, 1.0 if current_users > 0 else 0.0)
            self._metrics_request_queue.observe(now, float(len(getattr(self, "queue", []))))

        return _attach_event_callback(release_event, _on_release_done)

    @property
    def queue_wait_time_min(self):
        return self._metrics_queue_wait.min

    @property
    def queue_wait_time_avg(self):
        return self._metrics_queue_wait.avg

    @property
    def queue_wait_time_max(self):
        return self._metrics_queue_wait.max

    @property
    def request_queue_min(self):
        return self._metrics_request_queue.minimum_value()

    @property
    def request_queue_avg(self):
        return self._metrics_request_queue.average(float(self._env.now))

    @property
    def request_queue_max(self):
        return self._metrics_request_queue.maximum_value()

    @property
    def usage_time_min(self):
        return self._metrics_usage_time.min

    @property
    def usage_time_avg(self):
        return self._metrics_usage_time.avg

    @property
    def usage_time_max(self):
        return self._metrics_usage_time.max

    @property
    def total_acquisitions(self):
        return self._metrics_total_acquisitions

    @property
    def total_releases(self):
        return self._metrics_total_releases

    @property
    def idle_time_pct(self):
        busy_pct = self.busy_time_pct
        return max(0.0, 100.0 - busy_pct)

    @property
    def busy_time_pct(self):
        busy_ratio = self._metrics_busy.average(float(self._env.now))
        return max(0.0, min(100.0, busy_ratio * 100.0))

    @property
    def concurrent_users_min(self):
        return int(round(self._metrics_concurrent.minimum_value()))

    @property
    def concurrent_users_avg(self):
        return self._metrics_concurrent.average(float(self._env.now))

    @property
    def concurrent_users_max(self):
        return int(round(self._metrics_concurrent.maximum_value()))

    @property
    def metrics(self):
        return _MetricsAccessor(self, self._metrics_names)


class _StoreMetricsMixin:
    _metrics_names = (
        "get_wait_time_min",
        "get_wait_time_avg",
        "get_wait_time_max",
        "get_queue_min",
        "get_queue_avg",
        "get_queue_max",
        "put_wait_time_min",
        "put_wait_time_avg",
        "put_wait_time_max",
        "put_queue_min",
        "put_queue_avg",
        "put_queue_max",
        "total_items_put",
        "total_items_got",
        "level_min",
        "level_avg",
        "level_max",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = float(getattr(self._env, "now", 0.0))
        self._metrics_get_wait = _SampleStats()
        self._metrics_put_wait = _SampleStats()
        self._metrics_total_items_put = 0
        self._metrics_total_items_got = 0
        self._metrics_level = _TimeWeightedStats(now, float(len(getattr(self, "items", []))))
        self._metrics_get_queue = _TimeWeightedStats(now, float(len(getattr(self, "get_queue", []))))
        self._metrics_put_queue = _TimeWeightedStats(now, float(len(getattr(self, "put_queue", []))))

    def put(self, *args, **kwargs):
        put_event = super().put(*args, **kwargs)
        started_at = float(self._env.now)
        self._metrics_put_queue.observe(started_at, float(len(getattr(self, "put_queue", []))))
        self._metrics_get_queue.observe(started_at, float(len(getattr(self, "get_queue", []))))

        def _on_put_done(_event):
            now = float(self._env.now)
            self._metrics_put_wait.add(now - started_at)
            self._metrics_total_items_put += 1
            self._metrics_level.observe(now, float(len(getattr(self, "items", []))))
            self._metrics_put_queue.observe(now, float(len(getattr(self, "put_queue", []))))
            self._metrics_get_queue.observe(now, float(len(getattr(self, "get_queue", []))))

        return _attach_event_callback(put_event, _on_put_done)

    def get(self, *args, **kwargs):
        get_event = super().get(*args, **kwargs)
        started_at = float(self._env.now)
        self._metrics_put_queue.observe(started_at, float(len(getattr(self, "put_queue", []))))
        self._metrics_get_queue.observe(started_at, float(len(getattr(self, "get_queue", []))))

        def _on_get_done(_event):
            now = float(self._env.now)
            self._metrics_get_wait.add(now - started_at)
            self._metrics_total_items_got += 1
            self._metrics_level.observe(now, float(len(getattr(self, "items", []))))
            self._metrics_put_queue.observe(now, float(len(getattr(self, "put_queue", []))))
            self._metrics_get_queue.observe(now, float(len(getattr(self, "get_queue", []))))

        return _attach_event_callback(get_event, _on_get_done)

    @property
    def get_wait_time_min(self):
        return self._metrics_get_wait.min

    @property
    def get_wait_time_avg(self):
        return self._metrics_get_wait.avg

    @property
    def get_wait_time_max(self):
        return self._metrics_get_wait.max

    @property
    def get_queue_min(self):
        return self._metrics_get_queue.minimum_value()

    @property
    def get_queue_avg(self):
        return self._metrics_get_queue.average(float(self._env.now))

    @property
    def get_queue_max(self):
        return self._metrics_get_queue.maximum_value()

    @property
    def put_wait_time_min(self):
        return self._metrics_put_wait.min

    @property
    def put_wait_time_avg(self):
        return self._metrics_put_wait.avg

    @property
    def put_wait_time_max(self):
        return self._metrics_put_wait.max

    @property
    def put_queue_min(self):
        return self._metrics_put_queue.minimum_value()

    @property
    def put_queue_avg(self):
        return self._metrics_put_queue.average(float(self._env.now))

    @property
    def put_queue_max(self):
        return self._metrics_put_queue.maximum_value()

    @property
    def total_items_put(self):
        return self._metrics_total_items_put

    @property
    def total_items_got(self):
        return self._metrics_total_items_got

    @property
    def level_min(self):
        return self._metrics_level.minimum_value()

    @property
    def level_avg(self):
        return self._metrics_level.average(float(self._env.now))

    @property
    def level_max(self):
        return self._metrics_level.maximum_value()

    @property
    def metrics(self):
        return _MetricsAccessor(self, self._metrics_names)


class _ContainerMetricsMixin:
    _metrics_names = (
        "get_wait_time_per_unit_min",
        "get_wait_time_per_unit_avg",
        "get_wait_time_per_unit_max",
        "get_queue_min",
        "get_queue_avg",
        "get_queue_max",
        "put_wait_time_per_unit_min",
        "put_wait_time_per_unit_avg",
        "put_wait_time_per_unit_max",
        "put_queue_min",
        "put_queue_avg",
        "put_queue_max",
        "total_amount_put",
        "total_amount_got",
        "level_min",
        "level_avg",
        "level_max",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = float(getattr(self._env, "now", 0.0))
        self._metrics_get_wait_per_unit = _SampleStats()
        self._metrics_put_wait_per_unit = _SampleStats()
        self._metrics_total_amount_put = 0.0
        self._metrics_total_amount_got = 0.0
        self._metrics_level = _TimeWeightedStats(now, float(getattr(self, "level", 0.0)))
        self._metrics_get_queue = _TimeWeightedStats(now, float(len(getattr(self, "get_queue", []))))
        self._metrics_put_queue = _TimeWeightedStats(now, float(len(getattr(self, "put_queue", []))))

    def put(self, *args, **kwargs):
        amount = _read_amount(args, kwargs)
        put_event = super().put(*args, **kwargs)
        started_at = float(self._env.now)
        self._metrics_put_queue.observe(started_at, float(len(getattr(self, "put_queue", []))))
        self._metrics_get_queue.observe(started_at, float(len(getattr(self, "get_queue", []))))

        def _on_put_done(_event):
            now = float(self._env.now)
            wait_time = now - started_at
            per_unit = wait_time / amount if amount > 0 else wait_time
            self._metrics_put_wait_per_unit.add(per_unit)
            self._metrics_total_amount_put += amount
            self._metrics_level.observe(now, float(getattr(self, "level", 0.0)))
            self._metrics_put_queue.observe(now, float(len(getattr(self, "put_queue", []))))
            self._metrics_get_queue.observe(now, float(len(getattr(self, "get_queue", []))))

        return _attach_event_callback(put_event, _on_put_done)

    def get(self, *args, **kwargs):
        amount = _read_amount(args, kwargs)
        get_event = super().get(*args, **kwargs)
        started_at = float(self._env.now)
        self._metrics_put_queue.observe(started_at, float(len(getattr(self, "put_queue", []))))
        self._metrics_get_queue.observe(started_at, float(len(getattr(self, "get_queue", []))))

        def _on_get_done(_event):
            now = float(self._env.now)
            wait_time = now - started_at
            per_unit = wait_time / amount if amount > 0 else wait_time
            self._metrics_get_wait_per_unit.add(per_unit)
            self._metrics_total_amount_got += amount
            self._metrics_level.observe(now, float(getattr(self, "level", 0.0)))
            self._metrics_put_queue.observe(now, float(len(getattr(self, "put_queue", []))))
            self._metrics_get_queue.observe(now, float(len(getattr(self, "get_queue", []))))

        return _attach_event_callback(get_event, _on_get_done)

    @property
    def get_wait_time_per_unit_min(self):
        return self._metrics_get_wait_per_unit.min

    @property
    def get_wait_time_per_unit_avg(self):
        return self._metrics_get_wait_per_unit.avg

    @property
    def get_wait_time_per_unit_max(self):
        return self._metrics_get_wait_per_unit.max

    @property
    def get_queue_min(self):
        return self._metrics_get_queue.minimum_value()

    @property
    def get_queue_avg(self):
        return self._metrics_get_queue.average(float(self._env.now))

    @property
    def get_queue_max(self):
        return self._metrics_get_queue.maximum_value()

    @property
    def put_wait_time_per_unit_min(self):
        return self._metrics_put_wait_per_unit.min

    @property
    def put_wait_time_per_unit_avg(self):
        return self._metrics_put_wait_per_unit.avg

    @property
    def put_wait_time_per_unit_max(self):
        return self._metrics_put_wait_per_unit.max

    @property
    def put_queue_min(self):
        return self._metrics_put_queue.minimum_value()

    @property
    def put_queue_avg(self):
        return self._metrics_put_queue.average(float(self._env.now))

    @property
    def put_queue_max(self):
        return self._metrics_put_queue.maximum_value()

    @property
    def total_amount_put(self):
        return self._metrics_total_amount_put

    @property
    def total_amount_got(self):
        return self._metrics_total_amount_got

    @property
    def level_min(self):
        return self._metrics_level.minimum_value()

    @property
    def level_avg(self):
        return self._metrics_level.average(float(self._env.now))

    @property
    def level_max(self):
        return self._metrics_level.maximum_value()

    @property
    def metrics(self):
        return _MetricsAccessor(self, self._metrics_names)


OriginalResource = simpy.Resource
OriginalPriorityResource = simpy.PriorityResource
OriginalPreemptiveResource = simpy.PreemptiveResource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store
OriginalPriorityStore = simpy.PriorityStore
OriginalFilterStore = simpy.FilterStore


class MetricsResource(_ResourceMetricsMixin, OriginalResource):
    pass


class MetricsPriorityResource(_ResourceMetricsMixin, OriginalPriorityResource):
    pass


class MetricsPreemptiveResource(_ResourceMetricsMixin, OriginalPreemptiveResource):
    pass


class MetricsStore(_StoreMetricsMixin, OriginalStore):
    pass


class MetricsPriorityStore(_StoreMetricsMixin, OriginalPriorityStore):
    pass


class MetricsFilterStore(_StoreMetricsMixin, OriginalFilterStore):
    pass


class MetricsContainer(_ContainerMetricsMixin, OriginalContainer):
    pass


def _apply_metrics_patch():
    def _compose(patch_cls, current_cls):
        # Already includes metrics behavior.
        if issubclass(current_cls, patch_cls):
            return current_cls

        # Patch class already extends the current base.
        if issubclass(patch_cls, current_cls):
            return patch_cls

        class _Composed(patch_cls, current_cls):
            pass

        _Composed.__name__ = f"{patch_cls.__name__}With{current_cls.__name__}"
        return _Composed

    simpy.Resource = _compose(MetricsResource, simpy.Resource)
    simpy.PriorityResource = _compose(MetricsPriorityResource, simpy.PriorityResource)
    simpy.PreemptiveResource = _compose(MetricsPreemptiveResource, simpy.PreemptiveResource)
    simpy.Store = _compose(MetricsStore, simpy.Store)
    simpy.PriorityStore = _compose(MetricsPriorityStore, simpy.PriorityStore)
    simpy.FilterStore = _compose(MetricsFilterStore, simpy.FilterStore)
    simpy.Container = _compose(MetricsContainer, simpy.Container)


class MetricsPatch:
    _applied = False

    @classmethod
    def apply(cls):
        if cls._applied:
            return
        _apply_metrics_patch()
        cls._applied = True
