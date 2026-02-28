import json
import simpy
import time
from .monkey_patch import pending_transfers, tracked_resources, step_logs


class SimulationController:
    def __init__(self, draw_callback, start_animations_cb, update_time_cb, schedule_cb, speed_getter, on_pause_cb=None, log_callback=None):
        """Controller that manages the SimPy Environment and stepping logic.

        - draw_callback(initial=False): function to ask the GUI to redraw
        - start_animations_cb(transfers, duration_ms, on_complete=None): GUI animation starter
        - update_time_cb(now): updates time display in GUI
        - schedule_cb(ms, func): schedules a callable after ms milliseconds (GUI's after)
        - speed_getter(): returns integer slider value 0..100 used to compute delay
        - on_pause_cb(): function to call when simulation pauses (e.g. target reached)
        - log_callback(messages): function to log messages in the GUI
        """
        self.env = None
        self.running = False
        self.target_time = float("inf")
        self._setup_func = None

        self.draw_callback = draw_callback
        self.start_animations_cb = start_animations_cb
        self.update_time_cb = update_time_cb
        self.schedule_cb = schedule_cb
        self.speed_getter = speed_getter
        self.on_pause_cb = on_pause_cb if on_pause_cb else lambda: None
        self.log_callback = log_callback if log_callback else lambda msg: None

    def _resource_visual_signature(self, resource):
        kind = resource.__class__.__name__
        visual_type = getattr(resource, "visual_type", kind)

        if kind.endswith("Container"):
            return (
                visual_type,
                float(getattr(resource, "level", 0.0)),
                len(getattr(resource, "put_queue", [])),
                len(getattr(resource, "get_queue", [])),
            )

        if kind.endswith("Store"):
            items = getattr(resource, "items", [])
            return (
                visual_type,
                tuple(str(item) for item in items),
                len(getattr(resource, "put_queue", [])),
                len(getattr(resource, "get_queue", [])),
            )

        if kind.endswith("Resource"):
            return (
                visual_type,
                int(getattr(resource, "count", 0)),
                len(getattr(resource, "queue", [])),
            )

        return (visual_type,)

    def _capture_visual_state_signature(self):
        signature = []
        for resource in list(tracked_resources):
            resource_name = getattr(resource, "visual_name", str(id(resource)))
            signature.append((resource_name, self._resource_visual_signature(resource)))
        signature.sort(key=lambda item: item[0])
        return tuple(signature)

    def set_setup_func(self, func):
        self._setup_func = func

    def reset(self, setup_func=None):
        if setup_func is not None:
            self._setup_func = setup_func

        self.running = False
        tracked_resources.clear()
        pending_transfers.clear()
        step_logs.clear()
        self.log_callback([json.dumps({"kind": "STATUS", "event": "RESET", "time": 0.0}, ensure_ascii=False, sort_keys=True)])

        if not self._setup_func:
            self.env = None
            self.update_time_cb(0.0)
            return

        # Create new environment and run user setup
        self.env = simpy.Environment()

        try:
            self._setup_func(self.env)
        except Exception as e:
            # propagate by updating time to 0 and rethrow for GUI to handle if needed
            self.update_time_cb(0.0)
            raise

        # Ensure GUI reflects initial state
        self.update_time_cb(self.env.now)
        self.draw_callback(initial=True)

    def _compute_delay_ms(self):
        val = int(self.speed_getter())
        delay_ms = int(1000 * (0.001 ** (val / 100.0)))
        return max(1, delay_ms)

    def run(self):
        if not self._setup_func:
            return

        if self.env is None:
            self.reset()

        if not self.running:
            self.running = True
            self.step()

    def run_single_step(self):
        if not self.env:
            if self._setup_func:
                self.reset()
            else:
                return

        self.running = False
        try:
            if self.env.peek() != simpy.core.Infinity:
                self.env.step()
                self.update_time_cb(self.env.now)
                self.draw_callback()

                # Process logs
                if step_logs:
                    self.log_callback(list(step_logs))
                    step_logs.clear()

                if pending_transfers:
                    delay_ms = self._compute_delay_ms()
                    transfers = list(pending_transfers)
                    pending_transfers.clear()
                    self.start_animations_cb(transfers, delay_ms)
        except simpy.core.EmptySchedule:
            pass

    def pause(self):
        self.running = False

    def step(self):
        start_time = time.perf_counter()

        if not self.running:
            self.on_pause_cb()
            return
        if not self.env:
            self.running = False
            self.on_pause_cb()
            return

        if self.env.peek() == simpy.core.Infinity or self.env.now >= self.target_time:
            self.running = False
            self.on_pause_cb()
            return

        before_signature = self._capture_visual_state_signature()

        try:
            self.env.step()
        except simpy.core.EmptySchedule:
            self.running = False
            self.on_pause_cb()
            return

        should_pause_after_cycle = self.env.now >= self.target_time

        target_delay_ms = self._compute_delay_ms()
        transfers = []
        if pending_transfers:
            transfers = list(pending_transfers)
            pending_transfers.clear()

        after_signature = self._capture_visual_state_signature()
        visual_state_changed = before_signature != after_signature
        has_visual_change = bool(transfers) or visual_state_changed

        self.update_time_cb(self.env.now)
        if has_visual_change:
            self.draw_callback()

        if step_logs:
            self.log_callback(list(step_logs))
            step_logs.clear()

        def finish_cycle():
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if should_pause_after_cycle or not self.running:
                self.running = False
                self.on_pause_cb()
                return

            if has_visual_change:
                wait_ms = max(1, int(target_delay_ms - elapsed_ms))
            else:
                wait_ms = 0
            self.schedule_cb(wait_ms, self.step)

        if transfers:
            self.start_animations_cb(transfers, target_delay_ms, on_complete=finish_cycle)
        else:
            finish_cycle()
