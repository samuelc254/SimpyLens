import json
import random
import simpy
import time
from collections import deque
from typing import Iterable, Optional

from .breakpoint import Breakpoint
from .metrics_patch import MetricsPatch
from .tracking_patch import TrackingPatch


class _LogBuffer:
    def __init__(self, capacity=1000):
        self._capacity = 1
        self._events = deque(maxlen=1)
        self._next_seq = 1
        self.set_capacity(capacity)

    def set_capacity(self, capacity):
        try:
            value = int(capacity)
        except (TypeError, ValueError) as exc:
            raise ValueError("log capacity must be an integer") from exc

        if value <= 0:
            raise ValueError("log capacity must be greater than zero")

        self._capacity = value
        existing = list(self._events)
        self._events = deque(existing[-value:], maxlen=value)

    def append_many(self, messages: Iterable, now=None):
        for message in messages:
            event = self._normalize(message, now=now)
            self._events.append(event)

    def snapshot(self):
        return [dict(event) for event in self._events]

    def _normalize(self, message, now=None):
        payload = None

        if isinstance(message, dict):
            payload = dict(message)
        elif isinstance(message, str):
            text = message.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    loaded = json.loads(text)
                    if isinstance(loaded, dict):
                        payload = loaded
                except json.JSONDecodeError:
                    payload = None
            if payload is None:
                payload = {
                    "kind": "STATUS",
                    "event": "MESSAGE",
                    "level": "INFO",
                    "source": "lens",
                    "message": message,
                    "data": None,
                }
        else:
            payload = {
                "kind": "STATUS",
                "event": "MESSAGE",
                "level": "INFO",
                "source": "lens",
                "message": str(message),
                "data": None,
            }

        event = dict(payload)

        # Ensure required envelope fields exist
        event.setdefault("schema_version", "1.0")
        event.setdefault("kind", "STATUS")
        event.setdefault("event", "MESSAGE")
        event.setdefault("level", "INFO")
        event.setdefault("source", "lens")
        event.setdefault("message", "")
        event.setdefault("data", None)

        if "time" not in event:
            event["time"] = float(now) if now is not None else 0.0

        # Strip legacy fields that no longer belong in the schema
        event.pop("detail", None)
        event.pop("phase", None)
        event.pop("step", None)
        event.pop("action", None)

        event["seq"] = self._next_seq
        self._next_seq += 1
        return event


class SimulationController:
    def __init__(
        self,
        draw_callback,
        start_animations_cb,
        update_time_cb,
        schedule_cb,
        speed_getter,
        log_callback=None,
        on_breakpoint_cb=None,
        seed=None,
        log_buffer=None,
    ):
        """Controller that manages the SimPy Environment and stepping logic.

        - draw_callback(initial=False): function to ask the GUI to redraw
        - start_animations_cb(transfers, duration_ms, on_complete=None): GUI animation starter
        - update_time_cb(now): updates time display in GUI
        - schedule_cb(ms, func): schedules a callable after ms milliseconds (GUI's after)
        - speed_getter(): returns integer slider value 0..100 used to compute delay
        - log_callback(messages): function to log messages in the GUI
        """
        self.env = None
        self.running = False
        self._model = None

        self.draw_callback = draw_callback
        self.start_animations_cb = start_animations_cb
        self.update_time_cb = update_time_cb
        self.schedule_cb = schedule_cb
        self.speed_getter = speed_getter
        self.log_callback = log_callback if log_callback else lambda msg: None
        self.on_breakpoint_cb = on_breakpoint_cb
        self.seed = 42 if seed is None else seed
        self._log_buffer = log_buffer if log_buffer is not None else _LogBuffer(capacity=1000)

        self._next_breakpoint_id = 1
        self._breakpoints = []
        self._breakpoint_eval_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "len": len,
            "max": max,
            "min": min,
            "round": round,
            "sum": sum,
        }

    def _tracked_resources(self):
        if self.env is None:
            return ()
        return getattr(self.env, "tracked_resources", ())

    def _pending_transfers(self):
        if self.env is None:
            return []
        return getattr(self.env, "pending_transfers", [])

    def _step_logs(self):
        if self.env is None:
            return []
        return getattr(self.env, "step_logs", [])

    def _emit_logs(self, messages):
        now = None
        if self.env is not None:
            now = self.env.now
        self._log_buffer.append_many(messages, now=now)
        self.log_callback(messages)

    def _emit_event(self, payload):
        message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._emit_logs([message])

    def get_logs(self):
        return self._log_buffer.snapshot()

    def set_log_capacity(self, capacity):
        self._log_buffer.set_capacity(capacity)

    def add_breakpoint(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        if isinstance(condition, Breakpoint):
            breakpoint = Breakpoint(
                condition=condition.condition,
                label=condition.label,
                enabled=condition.enabled,
                pause_on_hit=condition.pause_on_hit,
                edge=condition.edge,
            )
        else:
            breakpoint = Breakpoint(
                condition=condition,
                label=label,
                enabled=enabled,
                pause_on_hit=pause_on_hit,
                edge=edge,
            )

        breakpoint_id = self._next_breakpoint_id
        self._next_breakpoint_id += 1

        breakpoint.assign_id(breakpoint_id)
        self._breakpoints.append(breakpoint)
        return breakpoint_id

    def remove_breakpoint(self, breakpoint_id):
        for idx, breakpoint in enumerate(self._breakpoints):
            if breakpoint.id == breakpoint_id:
                del self._breakpoints[idx]
                return True
        return False

    def clear_breakpoints(self):
        self._breakpoints.clear()

    def set_breakpoint_enabled(self, breakpoint_id, enabled):
        for breakpoint in self._breakpoints:
            if breakpoint.id == breakpoint_id:
                breakpoint.enabled = bool(enabled)
                return True
        return False

    def set_breakpoint_pause_on_hit(self, breakpoint_id, pause_on_hit):
        for breakpoint in self._breakpoints:
            if breakpoint.id == breakpoint_id:
                breakpoint.pause_on_hit = bool(pause_on_hit)
                return True
        return False

    def list_breakpoints(self):
        return [breakpoint.clone_public() for breakpoint in self._breakpoints]

    def _build_breakpoint_context(self):
        resources = {}
        for resource in list(self._tracked_resources()):
            name = getattr(resource, "visual_name", None)
            if not name or name in resources:
                continue
            resources[str(name)] = resource

        context = {
            "env": self.env,
            "resources": resources,
        }
        context.update(resources)
        return context

    def _evaluate_breakpoint(self, breakpoint, context):
        return breakpoint.evaluate(context, self._breakpoint_eval_builtins)

    def _check_breakpoints(self):
        if not self._breakpoints or self.env is None:
            return None

        context = self._build_breakpoint_context()
        hit_events = []
        should_pause = False

        for breakpoint in self._breakpoints:
            if not breakpoint.enabled:
                continue

            try:
                matched = self._evaluate_breakpoint(breakpoint, context)
                breakpoint.last_error = None
            except Exception as exc:
                err_text = f"{type(exc).__name__}: {exc}"
                self._emit_event(
                    {
                        "kind": "BREAKPOINT",
                        "event": "BREAKPOINT_ERROR",
                        "time": self.env.now,
                        "level": "ERROR",
                        "source": "lens",
                        "message": f"Breakpoint error: {breakpoint.label or breakpoint.expression}",
                        "data": {
                            "breakpoint_id": breakpoint.id,
                            "label": breakpoint.label,
                            "condition": breakpoint.expression,
                            "error": err_text,
                        },
                    }
                )
                breakpoint.last_error = err_text
                continue

            hit = breakpoint.compute_hit(matched)

            if not hit:
                continue

            breakpoint.record_hit()
            hit_label = breakpoint.label or breakpoint.expression
            hit_data = {
                "breakpoint_id": breakpoint.id,
                "label": breakpoint.label,
                "condition": breakpoint.expression,
                "hit_count": breakpoint.hit_count,
                "pause_on_hit": breakpoint.pause_on_hit,
                "edge": breakpoint.edge,
            }
            event = {
                "breakpoint_id": breakpoint.id,
                "label": breakpoint.label,
                "condition": breakpoint.expression,
                "time": self.env.now,
                "hit_count": breakpoint.hit_count,
                "pause_on_hit": breakpoint.pause_on_hit,
                "edge": breakpoint.edge,
            }

            self._emit_event(
                {
                    "kind": "BREAKPOINT",
                    "event": "BREAKPOINT_HIT",
                    "time": self.env.now,
                    "level": "INFO",
                    "source": "lens",
                    "message": f"Breakpoint hit: {hit_label} (hits={breakpoint.hit_count})",
                    "data": hit_data,
                }
            )
            event["step"] = getattr(self.env, "step_count", None)
            if self.on_breakpoint_cb:
                try:
                    self.on_breakpoint_cb(event)
                except Exception:
                    pass

            hit_events.append(event)
            if breakpoint.pause_on_hit:
                should_pause = True

        if hit_events:
            return {
                "hits": hit_events,
                "pause": should_pause,
            }

        return None

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
        for resource in list(self._tracked_resources()):
            resource_name = getattr(resource, "visual_name", str(id(resource)))
            signature.append((resource_name, self._resource_visual_signature(resource)))
        signature.sort(key=lambda item: item[0])
        return tuple(signature)

    def set_model(self, func):
        self._model = func

    def set_seed(self, seed):
        self.seed = 42 if seed is None else seed

    def reset(self, model=None):
        if model is not None:
            self._model = model

        random.seed(self.seed)

        self.running = False

        # Reset hit statistics of all breakpoints so counts start fresh
        for bp in self._breakpoints:
            bp.hit_count = 0
            bp._last_matched = None

        seed = self.seed
        self._emit_event(
            {
                "kind": "SIM",
                "event": "RESET",
                "time": 0.0,
                "level": "INFO",
                "source": "lens",
                "message": f"Simulation reset with seed {seed}",
                "data": {"seed": seed},
            }
        )

        if not self._model:
            self.env = None
            self.update_time_cb(0.0)
            return

        # Create new environment and run user setup
        self.env = simpy.Environment()

        try:
            self._model(self.env)
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
        if not self._model:
            return

        if self.env is None:
            self.reset()

        if not self.running:
            self.running = True
            self.step()

    def run_single_step(self):
        if not self.env:
            if self._model:
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
                step_logs = self._step_logs()
                if step_logs:
                    self._emit_logs(list(step_logs))
                    step_logs.clear()

                breakpoint_result = self._check_breakpoints()
                if breakpoint_result and breakpoint_result.get("pause", False):
                    return

                pending_transfers = self._pending_transfers()
                if pending_transfers:
                    delay_ms = self._compute_delay_ms()
                    transfers = list(pending_transfers)
                    pending_transfers.clear()
                    self.start_animations_cb(transfers, delay_ms)
        except simpy.core.EmptySchedule:
            pass

    def run_headless(self):
        if not self._model:
            return

        if self.env is None:
            self.reset()

        self.running = True
        while self.running and self.env.peek() != simpy.core.Infinity:
            try:
                self.env.step()
                self.update_time_cb(self.env.now)

                # Process logs
                step_logs = self._step_logs()
                if step_logs:
                    self._emit_logs(list(step_logs))
                    step_logs.clear()

                breakpoint_result = self._check_breakpoints()
                if breakpoint_result and breakpoint_result.get("pause", False):
                    self.running = False
                    return

                pending_transfers = self._pending_transfers()
                if pending_transfers:
                    pending_transfers.clear()
            except simpy.core.EmptySchedule:
                self.running = False
                break

        self.running = False
        self._emit_event(
            {
                "kind": "SIM",
                "event": "RUN_COMPLETE",
                "time": self.env.now if self.env is not None else 0.0,
                "level": "INFO",
                "source": "lens",
                "message": "Simulation complete",
                "data": None,
            }
        )

    def pause(self):
        self.running = False

    def step(self):
        start_time = time.perf_counter()

        if not self.running:
            return
        if not self.env:
            self.running = False
            return

        if self.env.peek() == simpy.core.Infinity:
            self.running = False
            return

        before_signature = self._capture_visual_state_signature()

        try:
            self.env.step()
        except simpy.core.EmptySchedule:
            self.running = False
            return

        target_delay_ms = self._compute_delay_ms()
        transfers = []
        pending_transfers = self._pending_transfers()
        if pending_transfers:
            transfers = list(pending_transfers)
            pending_transfers.clear()

        after_signature = self._capture_visual_state_signature()
        visual_state_changed = before_signature != after_signature
        has_visual_change = bool(transfers) or visual_state_changed

        self.update_time_cb(self.env.now)
        if has_visual_change:
            self.draw_callback()

        step_logs = self._step_logs()
        if step_logs:
            self._emit_logs(list(step_logs))
            step_logs.clear()

        breakpoint_result = self._check_breakpoints()
        if breakpoint_result and breakpoint_result.get("pause", False):
            self.running = False
            return

        def finish_cycle():
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if not self.running:
                self.running = False
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


class Lens:
    def __init__(self, model=None, title="SimPyLens", gui=True, metrics=True, seed=42):
        if metrics:
            MetricsPatch.apply()
        TrackingPatch.apply()

        self._model = model
        self._title = title
        self._gui = bool(gui)
        self._metrics = bool(metrics)
        self._seed = 42 if seed is None else seed

        self.viewer = None
        self._sim_ctrl: Optional[SimulationController] = None

        if self._gui:
            from .viewer import Viewer

            self.viewer = Viewer(model=self._model, title=title, seed=self._seed)
            self._sim_ctrl = self.viewer.sim_ctrl
        else:
            self._sim_ctrl = SimulationController(
                draw_callback=lambda initial=False: None,
                start_animations_cb=lambda transfers, duration_ms, on_complete=None: (on_complete() if on_complete else None),
                update_time_cb=lambda now: None,
                schedule_cb=lambda ms, fn: None,
                speed_getter=lambda: 50,
                log_callback=lambda messages: None,
                seed=self._seed,
            )
            self._sim_ctrl.set_model(self._model)
            if self._model:
                self._sim_ctrl.reset(self._model)

    @property
    def model(self):
        return self._model

    @property
    def seed(self):
        return self._seed

    @property
    def title(self):
        return self._title

    @property
    def gui(self):
        return self._gui

    @property
    def metrics(self):
        return self._metrics

    @property
    def sim_ctrl(self):
        return self._sim_ctrl

    def show(self):
        if self.viewer is None:
            return None
        return self.viewer.mainloop()

    def set_seed(self, seed):
        self._seed = 42 if seed is None else seed
        if self._sim_ctrl is not None:
            self._sim_ctrl.set_seed(self._seed)

    def set_model(self, model):
        self._model = model
        if self.viewer is not None:
            self.viewer.current_model = model
        if self._sim_ctrl is not None:
            self._sim_ctrl.set_model(model)

    def add_breakpoint(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        if self.viewer is not None:
            return self.viewer.add_breakpoint(
                condition=condition,
                label=label,
                enabled=enabled,
                pause_on_hit=pause_on_hit,
                edge=edge,
            )

        return self._sim_ctrl.add_breakpoint(
            condition=condition,
            label=label,
            enabled=enabled,
            pause_on_hit=pause_on_hit,
            edge=edge,
        )

    def remove_breakpoint(self, breakpoint_id):
        return self._sim_ctrl.remove_breakpoint(breakpoint_id)

    def clear_breakpoints(self):
        self._sim_ctrl.clear_breakpoints()

    def set_breakpoint_enabled(self, breakpoint_id, enabled):
        return self._sim_ctrl.set_breakpoint_enabled(breakpoint_id, enabled)

    def set_breakpoint_pause_on_hit(self, breakpoint_id, pause_on_hit):
        return self._sim_ctrl.set_breakpoint_pause_on_hit(breakpoint_id, pause_on_hit)

    def list_breakpoints(self):
        return self._sim_ctrl.list_breakpoints()

    def get_logs(self):
        if self._sim_ctrl is None:
            return []
        return self._sim_ctrl.get_logs()

    def set_log_capacity(self, capacity):
        if self._sim_ctrl is None:
            return
        self._sim_ctrl.set_log_capacity(capacity)

    def run(self):
        if self._sim_ctrl is None:
            return
        self._sim_ctrl.set_model(self._model)
        if self._gui:
            self._sim_ctrl.run()
        else:
            self._sim_ctrl.run_headless()

    def pause(self):
        if self._sim_ctrl is None:
            return
        self._sim_ctrl.pause()

    def step(self):
        if self._sim_ctrl is None:
            return
        self._sim_ctrl.set_model(self._model)
        self._sim_ctrl.run_single_step()

    def reset(self):
        if self._sim_ctrl is None:
            return
        self._sim_ctrl.reset(self._model)


Lens.Breakpoint = Breakpoint
