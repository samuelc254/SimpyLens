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
PROCESS_STATES_ATTR = "process_states"
PROCESS_NAME_COUNTERS_ATTR = "process_name_counters"
PROCESS_CREATION_COUNTER_ATTR = "process_creation_counter"
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
    if not hasattr(env, PROCESS_STATES_ATTR):
        setattr(env, PROCESS_STATES_ATTR, weakref.WeakKeyDictionary())
    if not hasattr(env, PROCESS_NAME_COUNTERS_ATTR):
        setattr(env, PROCESS_NAME_COUNTERS_ATTR, {})
    if not hasattr(env, PROCESS_CREATION_COUNTER_ATTR):
        setattr(env, PROCESS_CREATION_COUNTER_ATTR, 0)
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


def _ensure_process_state(env, process):
    state = _ensure_tracking_state(env)
    if state is None or process is None:
        return None

    process_states = getattr(state, PROCESS_STATES_ATTR)
    tracked_state = process_states.get(process)
    if tracked_state is not None:
        return tracked_state

    process_name = _process_label(process)
    name_counters = getattr(state, PROCESS_NAME_COUNTERS_ATTR)
    next_idx = int(name_counters.get(process_name, -1)) + 1
    name_counters[process_name] = next_idx

    creation_order = int(getattr(state, PROCESS_CREATION_COUNTER_ATTR, 0)) + 1
    setattr(state, PROCESS_CREATION_COUNTER_ATTR, creation_order)

    tracked_state = {
        "process_id": int(id(process)),
        "name": str(process_name),
        "label": f"{process_name}#{next_idx}",
        "creation_order": creation_order,
        "holding": set(),
        "queuing": set(),
    }
    process_states[process] = tracked_state
    return tracked_state


def _queue_entry_text(resource_name, wait_kind):
    resource_text = str(resource_name)
    if wait_kind == "put":
        return f"{resource_text} (Waiting to Put)"
    if wait_kind == "get":
        return f"{resource_text} (Waiting to Get)"
    return resource_text


def _track_process_queuing(env, process, resource_name, wait_kind="request"):
    tracked_state = _ensure_process_state(env, process)
    if tracked_state is None:
        return
    tracked_state["queuing"].add(_queue_entry_text(resource_name, wait_kind))


def _track_process_queue_cleared(env, process, resource_name, wait_kind="request"):
    tracked_state = _ensure_process_state(env, process)
    if tracked_state is None:
        return
    tracked_state["queuing"].discard(_queue_entry_text(resource_name, wait_kind))


def _track_process_request_granted(env, process, resource_name):
    tracked_state = _ensure_process_state(env, process)
    if tracked_state is None:
        return
    resource_text = str(resource_name)
    tracked_state["queuing"].discard(resource_text)
    tracked_state["holding"].add(resource_text)


def _track_process_released(env, process, resource_name):
    tracked_state = _ensure_process_state(env, process)
    if tracked_state is None:
        return
    resource_text = str(resource_name)
    tracked_state["holding"].discard(resource_text)
    tracked_state["queuing"].discard(resource_text)


def _attach_request_grant_tracker(env, resource_instance, request_event):
    state = _ensure_tracking_state(env)
    if state is None or request_event is None:
        return request_event

    resource_name = getattr(resource_instance, "visual_name", str(resource_instance))

    def _on_granted(event):
        process = getattr(event, "proc", None)
        if process is not None:
            _track_process_request_granted(env, process, resource_name)

    callbacks = getattr(request_event, "callbacks", None)
    if callbacks is None:
        _on_granted(request_event)
    else:
        callbacks.append(_on_granted)

    return request_event


def _attach_transaction_queue_tracker(env, resource_instance, event, wait_kind):
    state = _ensure_tracking_state(env)
    if state is None or event is None:
        return event

    process = getattr(event, "proc", None)
    if process is None:
        process = getattr(env, "active_process", None)
    if process is None:
        return event

    resource_name = getattr(resource_instance, "visual_name", str(resource_instance))
    if not bool(getattr(event, "triggered", False)):
        _track_process_queuing(env, process, resource_name, wait_kind=wait_kind)

    def _on_done(done_event):
        done_process = getattr(done_event, "proc", None) or process
        _track_process_queue_cleared(env, done_process, resource_name, wait_kind=wait_kind)

    callbacks = getattr(event, "callbacks", None)
    if callbacks is None:
        _on_done(event)
    else:
        callbacks.append(_on_done)

    return event


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


def _extract_process_source_location(process):
    """Best-effort extraction of user code location from a SimPy process generator."""
    if process is None:
        return {}

    try:
        generator = getattr(process, "_generator", None)
        frame = getattr(generator, "gi_frame", None) if generator is not None else None
        if frame is None:
            return {}

        location = {}
        code = getattr(frame, "f_code", None)
        filename = getattr(code, "co_filename", None) if code is not None else None
        line = getattr(frame, "f_lineno", None)

        if filename:
            location["file"] = str(filename)
        if isinstance(line, int):
            location["line"] = line

        return location
    except Exception:
        return {}


def _describe_process_target(target):
    if target is None:
        return "-"

    try:
        event_name = type(target).__name__
    except Exception:
        return str(target)

    if event_name == "Timeout":
        delay = getattr(target, "_delay", None)
        if delay is not None:
            return f"Timeout({delay})"
        return "Timeout"

    if event_name in {"Request", "PriorityRequest", "PreemptiveRequest"}:
        return "Request"

    if event_name.endswith("Put"):
        return "Put"

    if event_name.endswith("Get"):
        return "Get"

    if event_name == "Condition":
        return "Condition"

    return event_name


def _resolve_process_from_event(event):
    """Best-effort process discovery for the next event queued in the environment."""
    if event is None:
        return None

    process = getattr(event, "proc", None)
    if process is not None:
        return process

    if type(event).__name__ == "Process" and hasattr(event, "_generator"):
        return event

    callbacks = getattr(event, "callbacks", None)
    if callbacks:
        for callback in callbacks:
            owner = getattr(callback, "__self__", None)
            if owner is not None and hasattr(owner, "_generator"):
                return owner

            nested_owner = getattr(owner, "__self__", None) if owner is not None else None
            if nested_owner is not None and hasattr(nested_owner, "_generator"):
                return nested_owner

    return None


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
    tracked_process = _ensure_process_state(env, process) or {}
    process_label = tracked_process.get("label") or _process_label(process)
    source_location = _extract_process_source_location(process)
    setattr(state, LAST_PROCESS_NAME_ATTR, process_label)
    current_name = getattr(resource_instance, "visual_name", str(resource_instance))
    previous_resource = _resolve_process_resource(env, process)
    action_type = str(action).lower()

    if action_type == "request":
        _track_process_queuing(env, process, current_name)
    elif action_type == "release":
        _track_process_released(env, process, current_name)

    if previous_resource is None:
        previous_name = "<START>"
    else:
        previous_name = getattr(previous_resource, "visual_name", str(previous_resource))

    if action_type == "release":
        from_name = previous_name if previous_resource is not None else current_name
        data = {
            "step": int(getattr(env, "step_count", 0)),
            "action_type": action_type,
            "resource": current_name,
            "process": process_label,
            "from": from_name,
            "to": "<IDLE>",
        }
        if source_location:
            data.update(source_location)
        if extra_data:
            data.update(extra_data)
        payload = {
            "schema_version": "1.0",
            "kind": "STEP",
            "event": "ACTION",
            "time": env.now,
            "level": "INFO",
            "source": "tracking",
            "message": f"{process_label} released {current_name}",
            "data": data,
        }
        step_logs.append(_format_payload(payload))
        process_locations[process] = weakref.ref(resource_instance)
        return

    data = {
        "step": int(getattr(env, "step_count", 0)),
        "action_type": action_type,
        "resource": current_name,
        "process": process_label,
        "from": previous_name,
        "to": current_name,
    }
    if source_location:
        data.update(source_location)
    if extra_data:
        data.update(extra_data)

    if action_type == "request":
        message = f"{process_label} requested {current_name}"
    elif action_type == "put":
        message = f"{process_label} put into {current_name}"
    elif action_type == "get":
        message = f"{process_label} got from {current_name}"
    else:
        message = f"{process_label} {action_type} {current_name}"

    payload = {
        "schema_version": "1.0",
        "kind": "STEP",
        "event": "ACTION",
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
            is_get = action_type == "get"
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
                    "item": process_label,
                    "action": action_type,
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
        request_event = super().request(*args, **kwargs)
        register_interaction(self._env, self, "request")
        return _attach_request_grant_tracker(self._env, self, request_event)

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
        request_event = super().request(*args, **kwargs)
        register_interaction(self._env, self, "request")
        return _attach_request_grant_tracker(self._env, self, request_event)

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
        request_event = super().request(*args, **kwargs)
        register_interaction(self._env, self, "request")
        return _attach_request_grant_tracker(self._env, self, request_event)

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
        put_event = super().put(*args, **kwargs)
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, put_event, wait_kind="put")

    def get(self, *args, **kwargs):
        extra = {}
        if args:
            extra["amount"] = _serialize_value(args[0])
        elif "amount" in kwargs:
            extra["amount"] = _serialize_value(kwargs["amount"])
        get_event = super().get(*args, **kwargs)
        register_interaction(self._env, self, "get", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, get_event, wait_kind="get")


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
        put_event = super().put(*args, **kwargs)
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, put_event, wait_kind="put")

    def get(self, *args, **kwargs):
        get_event = super().get(*args, **kwargs)
        register_interaction(self._env, self, "get")
        return _attach_transaction_queue_tracker(self._env, self, get_event, wait_kind="get")


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
        put_event = super().put(*args, **kwargs)
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, put_event, wait_kind="put")

    def get(self, *args, **kwargs):
        get_event = super().get(*args, **kwargs)
        register_interaction(self._env, self, "get")
        return _attach_transaction_queue_tracker(self._env, self, get_event, wait_kind="get")


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
        put_event = super().put(*args, **kwargs)
        register_interaction(self._env, self, "put", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, put_event, wait_kind="put")

    def get(self, *args, **kwargs):
        extra = {}
        if args:
            extra["filter"] = _serialize_value(args[0])
        elif "filter" in kwargs:
            extra["filter"] = _serialize_value(kwargs["filter"])
        get_event = super().get(*args, **kwargs)
        register_interaction(self._env, self, "get", extra_data=extra or None)
        return _attach_transaction_queue_tracker(self._env, self, get_event, wait_kind="get")


class TrackedEnvironment(simpy.Environment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._step_count = 0
        _ensure_tracking_state(self)

    @property
    def step_count(self):
        """Public accessor for the step counter (use in breakpoints: env.step_count >= N)."""
        return self._step_count

    def process(self, generator):
        process = super().process(generator)
        _ensure_process_state(self, process)
        return process

    def step(self):
        self._step_count += 1

        _ensure_tracking_state(self)
        step_logs = self.step_logs
        step_num = self._step_count

        event = None
        sim_event_name = "EMPTY_QUEUE"
        event_queue = getattr(self, "_queue", [])
        if event_queue:
            try:
                event = event_queue[0][3]
                sim_event_name = type(event).__name__
            except Exception:
                event = None
                sim_event_name = "UNKNOWN"
        self.last_event_name = sim_event_name

        callbacks = getattr(event, "callbacks", None)
        has_process_callbacks = False

        if callbacks:
            original_callbacks = list(callbacks)
            wrapped_callbacks = []

            for _cb in original_callbacks:
                owner = getattr(_cb, "__self__", None)
                process_obj = owner if isinstance(owner, simpy.Process) else None

                if process_obj is None:
                    wrapped_callbacks.append(_cb)
                    continue

                has_process_callbacks = True

                def _wrapped(evt, _cb=_cb, _process=process_obj, _event_name=sim_event_name):
                    tracked_state = _ensure_process_state(self, _process) or {}
                    process_label = tracked_state.get("label") or _process_label(_process)

                    start_data = {
                        "step": step_num,
                        "sim_event": _event_name,
                        "process": process_label,
                    }
                    start_location = _extract_process_source_location(_process)
                    if start_location:
                        start_data.update(start_location)

                    step_logs.append(
                        _format_payload(
                            {
                                "schema_version": "1.0",
                                "kind": "STEP",
                                "event": "START",
                                "time": self.now,
                                "level": "DEBUG",
                                "source": "tracking",
                                "message": f"Waking up '{process_label}' (Triggered by: {_event_name})",
                                "data": start_data,
                            }
                        )
                    )

                    _cb(evt)

                    end_data = {
                        "step": step_num,
                        "sim_event": _event_name,
                        "process": process_label,
                    }
                    if not bool(getattr(_process, "is_alive", False)):
                        end_message = f"Process '{process_label}' terminated"
                    else:
                        target_description = _describe_process_target(getattr(_process, "target", None))
                        end_data["target"] = target_description
                        end_message = f"Suspending '{process_label}' (Yielding on: {target_description})"

                    end_location = _extract_process_source_location(_process)
                    if end_location:
                        end_data.update(end_location)

                    self.last_process_name = process_label
                    step_logs.append(
                        _format_payload(
                            {
                                "schema_version": "1.0",
                                "kind": "STEP",
                                "event": "END",
                                "time": self.now,
                                "level": "DEBUG",
                                "source": "tracking",
                                "message": end_message,
                                "data": end_data,
                            }
                        )
                    )

                wrapped_callbacks.append(_wrapped)

            callbacks[:] = wrapped_callbacks

        if not has_process_callbacks:
            step_logs.append(
                _format_payload(
                    {
                        "schema_version": "1.0",
                        "kind": "STEP",
                        "event": "START",
                        "time": self.now,
                        "level": "DEBUG",
                        "source": "tracking",
                        "message": f"Processing internal event: {sim_event_name}",
                        "data": {"step": step_num, "sim_event": sim_event_name},
                    }
                )
            )

        super().step()

        if not has_process_callbacks:
            self.last_process_name = None
            step_logs.append(
                _format_payload(
                    {
                        "schema_version": "1.0",
                        "kind": "STEP",
                        "event": "END",
                        "time": self.now,
                        "level": "DEBUG",
                        "source": "tracking",
                        "message": "Step completed",
                        "data": {"step": step_num, "sim_event": sim_event_name},
                    }
                )
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
