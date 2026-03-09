import ast
import inspect
import json
import re
import textwrap
import weakref

import simpy

TRACKED_RESOURCES_ATTR = "tracked_resources"
PENDING_TRANSFERS_ATTR = "pending_transfers"
STEP_LOGS_ATTR = "step_logs"
PROCESS_LOCATIONS_ATTR = "process_locations"
LAST_EVENT_NAME_ATTR = "last_event_name"
LAST_PROCESS_NAME_ATTR = "last_process_name"


def _ensure_tracking_state(env):
    if env is None:
        return None

    if not hasattr(env, TRACKED_RESOURCES_ATTR):
        setattr(env, TRACKED_RESOURCES_ATTR, weakref.WeakSet())
    if not hasattr(env, PENDING_TRANSFERS_ATTR):
        setattr(env, PENDING_TRANSFERS_ATTR, [])
    if not hasattr(env, STEP_LOGS_ATTR):
        setattr(env, STEP_LOGS_ATTR, [])
    if not hasattr(env, PROCESS_LOCATIONS_ATTR):
        setattr(env, PROCESS_LOCATIONS_ATTR, weakref.WeakKeyDictionary())
    if not hasattr(env, LAST_EVENT_NAME_ATTR):
        setattr(env, LAST_EVENT_NAME_ATTR, None)
    if not hasattr(env, LAST_PROCESS_NAME_ATTR):
        setattr(env, LAST_PROCESS_NAME_ATTR, None)

    return env


def _resolve_process_resource(env, process):
    state = _ensure_tracking_state(env)
    if state is None:
        return None

    process_locations = getattr(state, PROCESS_LOCATIONS_ATTR)
    ref_obj = process_locations.get(process)
    if ref_obj is None:
        return None
    if isinstance(ref_obj, weakref.ReferenceType):
        return ref_obj()
    try:
        process_locations[process] = weakref.ref(ref_obj)
    except Exception:
        pass
    return ref_obj


def _process_label(process):
    return getattr(process, "name", None) or str(process)


def _clean_text(text):
    if text is None:
        return None
    return re.sub(r"\s*object at 0x[0-9a-fA-F]+", "", str(text))


def _serialize_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]

    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}

    value_type = value.__class__.__name__
    payload = {"type": value_type}

    if hasattr(value, "name"):
        payload["name"] = _clean_text(getattr(value, "name", None))

    if hasattr(value, "resource"):
        resource_obj = getattr(value, "resource", None)
        if resource_obj is not None:
            payload["resource"] = getattr(resource_obj, "visual_name", _clean_text(resource_obj))

    if hasattr(value, "proc"):
        process_obj = getattr(value, "proc", None)
        if process_obj is not None:
            payload["process"] = _process_label(process_obj)

    if hasattr(value, "priority"):
        payload["priority"] = getattr(value, "priority", None)

    if hasattr(value, "preempt"):
        payload["preempt"] = getattr(value, "preempt", None)

    if hasattr(value, "key"):
        payload["key"] = _serialize_value(getattr(value, "key", None))

    return payload


def _format_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalize_target_name(name):
    if not name:
        return None
    if name.startswith("self."):
        return name[5:]
    return name


def _lookup_local_identity_name(frame, instance):
    for local_name, local_value in frame.f_locals.items():
        if local_value is instance:
            return _normalize_target_name(local_name)

    for local_name, local_value in frame.f_locals.items():
        try:
            attrs = vars(local_value)
        except Exception:
            continue
        for attr_name, attr_value in attrs.items():
            if attr_value is instance:
                return _normalize_target_name(f"{local_name}.{attr_name}")

    return None


def _extract_call_target_from_frame_source(frame):
    try:
        lines, start_line = inspect.getsourcelines(frame)
        source_text = textwrap.dedent("".join(lines))
        tree = ast.parse(source_text)
        current_line = frame.f_lineno
    except Exception:
        return None

    def _resolve_name_node(name_node):
        if not isinstance(name_node, ast.Name):
            raise ValueError("Unsupported name node")
        if name_node.id in frame.f_locals:
            return frame.f_locals[name_node.id]
        if name_node.id in frame.f_globals:
            return frame.f_globals[name_node.id]
        raise KeyError(name_node.id)

    def _resolve_expr_value(node):
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            return _resolve_name_node(node)

        if isinstance(node, ast.Attribute):
            base = _resolve_expr_value(node.value)
            return getattr(base, node.attr)

        if isinstance(node, ast.Tuple):
            return tuple(_resolve_expr_value(elt) for elt in node.elts)

        if isinstance(node, ast.List):
            return [_resolve_expr_value(elt) for elt in node.elts]

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _resolve_expr_value(node.operand)
            return +value if isinstance(node.op, ast.UAdd) else -value

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            left = _resolve_expr_value(node.left)
            right = _resolve_expr_value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            return left % right

        raise ValueError("Unsupported expression node")

    def _resolve_index_text(index_node):
        try:
            value = _resolve_expr_value(index_node)
            return repr(value)
        except Exception:
            try:
                return ast.unparse(index_node)
            except Exception:
                return "?"

    def target_to_name(target_node):
        try:
            if isinstance(target_node, ast.Subscript):
                try:
                    base_name = target_to_name(target_node.value)
                except Exception:
                    base_name = None

                if not base_name:
                    base_name = _normalize_target_name(ast.unparse(target_node.value))

                index_text = _resolve_index_text(target_node.slice)
                return _normalize_target_name(f"{base_name}[{index_text}]")

            return _normalize_target_name(ast.unparse(target_node))
        except Exception:
            return None

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        value_node = node.value
        if not isinstance(value_node, ast.Call):
            continue

        node_start = start_line + getattr(node, "lineno", 1) - 1
        node_end = start_line + getattr(node, "end_lineno", getattr(node, "lineno", 1)) - 1
        if not (node_start <= current_line <= node_end):
            continue

        if isinstance(node, ast.Assign):
            if not node.targets:
                continue
            return target_to_name(node.targets[0])

        return target_to_name(node.target)

    return None


def _action_to_event(action_name):
    """Maps a lowercased action string to its log event name."""
    return {
        "request": "REQUEST",
        "release": "RELEASE",
        "put": "PUT",
        "get": "GET",
    }.get(action_name, action_name.upper())


def register_interaction(env, resource_instance, action, extra_data=None):
    if not env or not hasattr(env, "active_process") or env.active_process is None:
        return

    state = _ensure_tracking_state(env)
    if state is None:
        return

    process_locations = getattr(state, PROCESS_LOCATIONS_ATTR)
    step_logs = getattr(state, STEP_LOGS_ATTR)
    pending_transfers = getattr(state, PENDING_TRANSFERS_ATTR)

    process = env.active_process
    process_name = _process_label(process)
    setattr(state, LAST_PROCESS_NAME_ATTR, process_name)
    current_name = getattr(resource_instance, "visual_name", str(resource_instance))
    previous_resource = _resolve_process_resource(env, process)
    action_name = str(action).lower()
    event_name = _action_to_event(action_name)

    if previous_resource is None:
        previous_name = "<START>"
    else:
        previous_name = getattr(previous_resource, "visual_name", str(previous_resource))

    if action_name == "release":
        from_name = previous_name if previous_resource is not None else current_name
        data = {
            "resource": current_name,
            "process": process_name,
            "from": from_name,
            "to": "<IDLE>",
        }
        if extra_data:
            data.update(extra_data)
        payload = {
            "schema_version": "1.0",
            "kind": "RESOURCE",
            "event": event_name,
            "time": env.now,
            "level": "INFO",
            "source": "tracking",
            "message": f"{process_name} released {current_name}",
            "data": data,
        }
        step_logs.append(_format_payload(payload))
        process_locations[process] = weakref.ref(resource_instance)
        return

    data = {
        "resource": current_name,
        "process": process_name,
        "from": previous_name,
        "to": current_name,
    }
    if extra_data:
        data.update(extra_data)

    if action_name == "request":
        message = f"{process_name} requested {current_name}"
    elif action_name == "put":
        message = f"{process_name} put into {current_name}"
    elif action_name == "get":
        message = f"{process_name} got from {current_name}"
    else:
        message = f"{process_name} {action_name} {current_name}"

    payload = {
        "schema_version": "1.0",
        "kind": "RESOURCE",
        "event": event_name,
        "time": env.now,
        "level": "INFO",
        "source": "tracking",
        "message": message,
        "data": data,
    }
    step_logs.append(_format_payload(payload))

    if previous_resource is not None:
        if previous_resource != resource_instance:
            transfer_from = previous_resource
            transfer_to = resource_instance

            # A get operation moves data/item from the resource back to where the
            # process previously was represented, so invert the animation direction.
            is_get = action_name == "get"
            is_store_or_container = bool(
                getattr(resource_instance, "visual_type", "") in {"STORE", "PRIORITY_STORE", "FILTER_STORE", "CONTAINER"}
                or resource_instance.__class__.__name__.endswith("Store")
                or resource_instance.__class__.__name__.endswith("Container")
            )
            if is_get and is_store_or_container:
                transfer_from, transfer_to = resource_instance, previous_resource

            pending_transfers.append(
                {
                    "from": transfer_from,
                    "to": transfer_to,
                    "item": process_name,
                    "action": action_name,
                }
            )

    process_locations[process] = weakref.ref(resource_instance)


def try_discover_name(instance):
    frame = None
    try:
        frame = inspect.currentframe()
        if not frame:
            return None

        frame = frame.f_back
        max_depth = 10
        depth = 0
        this_file = __file__

        while frame is not None and depth < max_depth:
            frame_file = inspect.getsourcefile(frame) or ""
            if frame_file != this_file:
                name = _lookup_local_identity_name(frame, instance)
                if name:
                    return name

                name = _extract_call_target_from_frame_source(frame)
                if name:
                    return name

            frame = frame.f_back
            depth += 1
    except Exception:
        pass
    finally:
        del frame

    return None


OriginalResource = simpy.Resource
OriginalPriorityResource = simpy.PriorityResource
OriginalPreemptiveResource = simpy.PreemptiveResource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store
OriginalPriorityStore = simpy.PriorityStore
OriginalFilterStore = simpy.FilterStore


class TrackedResource(OriginalResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Resource_{id(self)}"
        self.visual_type = "RESOURCE"
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def request(self, *args, **kwargs):
        register_interaction(self._env, self, "request")
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        register_interaction(self._env, self, "release")
        return super().release(*args, **kwargs)


class TrackedPriorityResource(OriginalPriorityResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"PriorityResource_{id(self)}"
        self.visual_type = "PRIORITY_RESOURCE"
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def request(self, *args, **kwargs):
        register_interaction(self._env, self, "request")
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        register_interaction(self._env, self, "release")
        return super().release(*args, **kwargs)


class TrackedPreemptiveResource(OriginalPreemptiveResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"PreemptiveResource_{id(self)}"
        self.visual_type = "PREEMPTIVE_RESOURCE"
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def request(self, *args, **kwargs):
        register_interaction(self._env, self, "request")
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        register_interaction(self._env, self, "release")
        return super().release(*args, **kwargs)


class TrackedContainer(OriginalContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Container_{id(self)}"
        self.visual_type = "CONTAINER"
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def put(self, *args, **kwargs):
        extra = {}
        if args:
            extra["amount"] = _serialize_value(args[0])
        elif "amount" in kwargs:
            extra["amount"] = _serialize_value(kwargs["amount"])
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        extra = {}
        if args:
            extra["amount"] = _serialize_value(args[0])
        elif "amount" in kwargs:
            extra["amount"] = _serialize_value(kwargs["amount"])
        register_interaction(self._env, self, "get", extra_data=extra or None)
        return super().get(*args, **kwargs)


class TrackedStore(OriginalStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Store_{id(self)}"
        self.visual_type = "STORE"
        self.is_expanded = False
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def put(self, *args, **kwargs):
        extra = {}
        if args:
            extra["item"] = _serialize_value(args[0])
        elif "item" in kwargs:
            extra["item"] = _serialize_value(kwargs["item"])
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        register_interaction(self._env, self, "get")
        return super().get(*args, **kwargs)


class TrackedPriorityStore(OriginalPriorityStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"PriorityStore_{id(self)}"
        self.visual_type = "PRIORITY_STORE"
        self.is_expanded = False
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def put(self, *args, **kwargs):
        extra = {}
        if args:
            extra["item"] = _serialize_value(args[0])
        elif "item" in kwargs:
            extra["item"] = _serialize_value(kwargs["item"])
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        register_interaction(self._env, self, "get")
        return super().get(*args, **kwargs)


class TrackedFilterStore(OriginalFilterStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"FilterStore_{id(self)}"
        self.visual_type = "FILTER_STORE"
        self.is_expanded = False
        _ensure_tracking_state(self._env)
        self._env.tracked_resources.add(self)

    def put(self, *args, **kwargs):
        extra = {}
        if args:
            extra["item"] = _serialize_value(args[0])
        elif "item" in kwargs:
            extra["item"] = _serialize_value(kwargs["item"])
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        extra = {}
        if args:
            extra["filter"] = _serialize_value(args[0])
        elif "filter" in kwargs:
            extra["filter"] = _serialize_value(kwargs["filter"])
        register_interaction(self._env, self, "get", extra_data=extra or None)
        return super().get(*args, **kwargs)


class TrackedEnvironment(simpy.Environment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._step_count = 0
        _ensure_tracking_state(self)

    @property
    def step_count(self):
        """Public accessor for the step counter (use in breakpoints: env.step_count >= N)."""
        return self._step_count

    def step(self):
        self._step_count += 1

        _ensure_tracking_state(self)
        step_logs = self.step_logs
        step_num = self._step_count

        # --- Inspect the next event before executing it ---
        data_before = {"step": step_num}
        triggering_processes = []
        event_queue = getattr(self, "_queue", [])

        if event_queue:
            try:
                next_item = event_queue[0]
                event = next_item[3]

                sim_event_name = type(event).__name__
                data_before["sim_event"] = sim_event_name
                self.last_event_name = sim_event_name

                if sim_event_name == "Timeout":
                    data_before["delay"] = getattr(event, "_delay", None)

                if hasattr(event, "resource"):
                    resource = event.resource
                    resource_name = getattr(resource, "visual_name", str(resource))
                    data_before["resource"] = resource_name

                if sim_event_name == "Process" and hasattr(event, "name"):
                    data_before["process"] = event.name

                if hasattr(event, "callbacks") and event.callbacks:
                    waiting_processes = []
                    for callback in event.callbacks:
                        obj = getattr(callback, "__self__", None)
                        if hasattr(obj, "name"):
                            process_name = obj.name
                            if not process_name and hasattr(obj, "__self__"):
                                owner = obj.__self__
                                if hasattr(owner, "name"):
                                    process_name = owner.name
                            if process_name:
                                waiting_processes.append(process_name)

                    if waiting_processes:
                        triggering_processes = list(waiting_processes)
                        data_before["triggering"] = waiting_processes
            except Exception as exc:
                data_before["sim_event"] = "UNKNOWN"
                data_before["inspect_error"] = str(exc)
                self.last_event_name = "UNKNOWN"
        else:
            data_before["sim_event"] = "EMPTY_QUEUE"
            self.last_event_name = "EMPTY_QUEUE"

        # Build human-readable message for STEP_BEFORE
        sim_ev = data_before.get("sim_event", "?")
        msg_parts = [f"Step {step_num}: {sim_ev}"]
        if "triggering" in data_before:
            msg_parts.append(f"triggering={','.join(data_before['triggering'])}")
        if "delay" in data_before:
            msg_parts.append(f"delay={data_before['delay']}")
        if "resource" in data_before:
            msg_parts.append(f"resource={data_before['resource']}")
        if "process" in data_before and "triggering" not in data_before:
            msg_parts.append(f"process={data_before['process']}")

        step_logs.append(
            _format_payload({
                "schema_version": "1.0",
                "kind": "STEP",
                "event": "STEP_BEFORE",
                "time": self.now,
                "level": "DEBUG",
                "source": "tracking",
                "message": " | ".join(msg_parts),
                "data": data_before,
            })
        )

        super().step()

        # --- After-step: check if active process differs from expected ---
        active_process_name = None
        if self.active_process:
            active_process_name = self.active_process.name
        elif triggering_processes:
            active_process_name = ",".join(triggering_processes)

        before_expected_process = None
        if triggering_processes:
            before_expected_process = ",".join(triggering_processes)
        elif data_before.get("process"):
            before_expected_process = str(data_before["process"])

        effective_after_process = active_process_name or "-"
        effective_before_process = before_expected_process or "-"
        self.last_process_name = None if effective_after_process == "-" else effective_after_process

        should_log_after = effective_after_process != effective_before_process
        if should_log_after:
            step_logs.append(
                _format_payload({
                    "schema_version": "1.0",
                    "kind": "STEP",
                    "event": "STEP_AFTER",
                    "time": self.now,
                    "level": "DEBUG",
                    "source": "tracking",
                    "message": f"Step {step_num}: active={effective_after_process}",
                    "data": {"step": step_num, "active_process": effective_after_process},
                })
            )


def _apply_tracking_patch():
    def _compose(patch_cls, current_cls):
        # Already includes tracking behavior.
        if issubclass(current_cls, patch_cls):
            return current_cls

        # Patch class already extends the current base.
        if issubclass(patch_cls, current_cls):
            return patch_cls

        class _Composed(patch_cls, current_cls):
            pass

        _Composed.__name__ = f"{patch_cls.__name__}With{current_cls.__name__}"
        return _Composed

    simpy.Resource = _compose(TrackedResource, simpy.Resource)
    simpy.PriorityResource = _compose(TrackedPriorityResource, simpy.PriorityResource)
    simpy.PreemptiveResource = _compose(TrackedPreemptiveResource, simpy.PreemptiveResource)
    simpy.Container = _compose(TrackedContainer, simpy.Container)
    simpy.Store = _compose(TrackedStore, simpy.Store)
    simpy.PriorityStore = _compose(TrackedPriorityStore, simpy.PriorityStore)
    simpy.FilterStore = _compose(TrackedFilterStore, simpy.FilterStore)
    simpy.Environment = _compose(TrackedEnvironment, simpy.Environment)


class TrackingPatch:
    _applied = False

    @classmethod
    def apply(cls):
        if cls._applied:
            return
        _apply_tracking_patch()
        cls._applied = True
