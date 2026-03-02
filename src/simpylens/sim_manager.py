import json
import simpy
import time
from .monkey_patch import pending_transfers, tracked_resources, step_logs


class SimulationController:
    def __init__(self, draw_callback, start_animations_cb, update_time_cb, schedule_cb, speed_getter, log_callback=None, on_breakpoint_cb=None):
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
        self._setup_func = None

        self.draw_callback = draw_callback
        self.start_animations_cb = start_animations_cb
        self.update_time_cb = update_time_cb
        self.schedule_cb = schedule_cb
        self.speed_getter = speed_getter
        self.log_callback = log_callback if log_callback else lambda msg: None
        self.on_breakpoint_cb = on_breakpoint_cb

        self._next_breakpoint_id = 1
        self._breakpoints = []
        self._breakpoint_eval_builtins = {
            "abs": abs,
            "len": len,
            "max": max,
            "min": min,
            "round": round,
            "sum": sum,
        }

    def add_breakpoint(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        if isinstance(condition, str):
            expr = condition.strip()
            if not expr:
                raise ValueError("Breakpoint condition cannot be empty")

            try:
                compiled = compile(expr, "<breakpoint>", "eval")
            except Exception as exc:
                raise ValueError(f"Invalid breakpoint expression: {exc}") from exc

            kind = "expression"
            expression = expr
            callback = None
        elif callable(condition):
            compiled = None
            kind = "callable"
            expression = getattr(condition, "__name__", repr(condition))
            callback = condition
        else:
            raise TypeError("Breakpoint condition must be a string expression or a callable")

        edge_mode = str(edge).strip().lower()
        if edge_mode not in {"none", "rising", "falling"}:
            raise ValueError("edge must be one of: 'none', 'rising', 'falling'")

        breakpoint_id = self._next_breakpoint_id
        self._next_breakpoint_id += 1

        label_text = str(label).strip() if label is not None else ""
        if not label_text:
            label_text = expression

        self._breakpoints.append(
            {
                "id": breakpoint_id,
                "label": label_text,
                "enabled": bool(enabled),
                "kind": kind,
                "expression": expression,
                "compiled": compiled,
                "callable": callback,
                "hit_count": 0,
                "last_error": None,
                "pause_on_hit": bool(pause_on_hit),
                "edge": edge_mode,
                "_last_matched": None,
            }
        )
        return breakpoint_id

    def remove_breakpoint(self, breakpoint_id):
        for idx, breakpoint in enumerate(self._breakpoints):
            if breakpoint["id"] == breakpoint_id:
                del self._breakpoints[idx]
                return True
        return False

    def clear_breakpoints(self):
        self._breakpoints.clear()

    def set_breakpoint_enabled(self, breakpoint_id, enabled):
        for breakpoint in self._breakpoints:
            if breakpoint["id"] == breakpoint_id:
                breakpoint["enabled"] = bool(enabled)
                return True
        return False

    def set_breakpoint_pause_on_hit(self, breakpoint_id, pause_on_hit):
        for breakpoint in self._breakpoints:
            if breakpoint["id"] == breakpoint_id:
                breakpoint["pause_on_hit"] = bool(pause_on_hit)
                return True
        return False

    def list_breakpoints(self):
        return [
            {
                "id": breakpoint["id"],
                "label": breakpoint["label"],
                "enabled": breakpoint["enabled"],
                "kind": breakpoint["kind"],
                "expression": breakpoint["expression"],
                "hit_count": breakpoint["hit_count"],
                "last_error": breakpoint["last_error"],
                "pause_on_hit": breakpoint["pause_on_hit"],
                "edge": breakpoint["edge"],
            }
            for breakpoint in self._breakpoints
        ]

    def _build_breakpoint_context(self):
        resources = {}
        for resource in list(tracked_resources):
            name = getattr(resource, "visual_name", None)
            if not name or name in resources:
                continue
            resources[str(name)] = resource

        context = {
            "env": self.env,
            "time": self.env.now,
            "resources": resources,
        }
        context.update(resources)
        return context

    def _evaluate_breakpoint(self, breakpoint, context):
        if breakpoint["kind"] == "expression":
            return bool(eval(breakpoint["compiled"], {"__builtins__": self._breakpoint_eval_builtins}, context))

        return bool(breakpoint["callable"](context))

    def _check_breakpoints(self):
        if not self._breakpoints or self.env is None:
            return None

        context = self._build_breakpoint_context()

        for breakpoint in self._breakpoints:
            if not breakpoint["enabled"]:
                continue

            try:
                matched = self._evaluate_breakpoint(breakpoint, context)
                breakpoint["last_error"] = None
            except Exception as exc:
                err_text = f"{type(exc).__name__}: {exc}"
                if breakpoint["last_error"] != err_text:
                    self.log_callback(
                        [
                            json.dumps(
                                {
                                    "kind": "STATUS",
                                    "event": "BREAKPOINT_ERROR",
                                    "time": self.env.now,
                                    "breakpoint_id": breakpoint["id"],
                                    "label": breakpoint["label"],
                                    "condition": breakpoint["expression"],
                                    "expression": breakpoint["expression"],
                                    "error": err_text,
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                        ]
                    )
                breakpoint["last_error"] = err_text
                continue

            previous = breakpoint.get("_last_matched")
            edge_mode = breakpoint.get("edge", "none")

            if edge_mode == "rising":
                hit = bool(matched) and previous is not True
            elif edge_mode == "falling":
                hit = previous is True and not bool(matched)
            else:
                hit = bool(matched)

            breakpoint["_last_matched"] = bool(matched)

            if not hit:
                continue

            breakpoint["hit_count"] += 1
            event = {
                "breakpoint_id": breakpoint["id"],
                "label": breakpoint["label"],
                "condition": breakpoint["expression"],
                "expression": breakpoint["expression"],
                "time": self.env.now,
                "hit_count": breakpoint["hit_count"],
                "pause_on_hit": breakpoint["pause_on_hit"],
                "edge": breakpoint["edge"],
            }

            self.log_callback([json.dumps({"kind": "STATUS", "event": "BREAKPOINT_HIT", **event}, ensure_ascii=False, sort_keys=True)])
            if self.on_breakpoint_cb:
                try:
                    self.on_breakpoint_cb(event)
                except Exception:
                    pass
            return event

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

                breakpoint_event = self._check_breakpoints()
                if breakpoint_event and breakpoint_event.get("pause_on_hit", True):
                    return

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

        breakpoint_event = self._check_breakpoints()
        if breakpoint_event and breakpoint_event.get("pause_on_hit", True):
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


class Manager:
    def __init__(self, setup_func=None, title="SimPyLens", with_ui=True):
        self.setup_func = setup_func
        self.title = title
        self.with_ui = bool(with_ui)

        self.viewer = None
        self.sim_ctrl = None

        if self.with_ui:
            from .gui import Viewer

            self.viewer = Viewer(setup_func=setup_func, title=title)
            self.sim_ctrl = self.viewer.sim_ctrl
        else:
            self.sim_ctrl = SimulationController(
                draw_callback=lambda initial=False: None,
                start_animations_cb=lambda transfers, duration_ms, on_complete=None: (on_complete() if on_complete else None),
                update_time_cb=lambda now: None,
                schedule_cb=lambda ms, fn: None,
                speed_getter=lambda: 50,
                log_callback=lambda messages: None,
            )
            self.sim_ctrl.set_setup_func(self.setup_func)
            if self.setup_func:
                self.sim_ctrl.reset(self.setup_func)

    def add_breakpoint(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        return self.sim_ctrl.add_breakpoint(
            condition=condition,
            label=label,
            enabled=enabled,
            pause_on_hit=pause_on_hit,
            edge=edge,
        )

    def remove_breakpoint(self, breakpoint_id):
        return self.sim_ctrl.remove_breakpoint(breakpoint_id)

    def clear_breakpoints(self):
        self.sim_ctrl.clear_breakpoints()

    def set_breakpoint_enabled(self, breakpoint_id, enabled):
        return self.sim_ctrl.set_breakpoint_enabled(breakpoint_id, enabled)

    def set_breakpoint_pause_on_hit(self, breakpoint_id, pause_on_hit):
        return self.sim_ctrl.set_breakpoint_pause_on_hit(breakpoint_id, pause_on_hit)

    def list_breakpoints(self):
        return self.sim_ctrl.list_breakpoints()

    def run(self):
        self.sim_ctrl.set_setup_func(self.setup_func)
        self.sim_ctrl.run()

    def pause(self):
        self.sim_ctrl.pause()

    def step(self):
        self.sim_ctrl.set_setup_func(self.setup_func)
        self.sim_ctrl.run_single_step()

    def reset(self):
        self.sim_ctrl.reset(self.setup_func)
