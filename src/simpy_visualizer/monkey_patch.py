import inspect
import re
import weakref

import simpy


tracked_resources = weakref.WeakSet()
pending_transfers = []
step_logs = []
process_locations = weakref.WeakKeyDictionary()


def register_interaction(env, resource_instance):
    """Registers process-resource interaction for logs and transfer animations."""
    if not env or not hasattr(env, "active_process") or env.active_process is None:
        return

    process = env.active_process
    resource_name = getattr(resource_instance, "visual_name", str(resource_instance))
    step_logs.append(f"[{env.now:.2f}] [RESOURCE] Process '{process}' accessed '{resource_name}'")

    if process in process_locations:
        previous_resource = process_locations[process]
        if previous_resource != resource_instance:
            pending_transfers.append({"from": previous_resource, "to": resource_instance, "item": str(process)})

    process_locations[process] = resource_instance


def try_discover_name(instance):
    """Tries to discover the variable name receiving this instance."""
    try:
        frame = inspect.currentframe().f_back.f_back
        if not frame:
            return None

        source_file = inspect.getsourcefile(frame)
        if not source_file:
            return None

        lines, start_line = inspect.getsourcelines(frame)
        relative_line = frame.f_lineno - start_line
        if 0 <= relative_line < len(lines):
            code_line = lines[relative_line].strip()
            match = re.search(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=", code_line)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None


OriginalResource = simpy.Resource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store


class TrackedResource(OriginalResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Resource_{id(self)}"
        self.visual_type = "RESOURCE"
        tracked_resources.add(self)

    def request(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().release(*args, **kwargs)


class TrackedContainer(OriginalContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Container_{id(self)}"
        self.visual_type = "CONTAINER"
        tracked_resources.add(self)

    def put(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().get(*args, **kwargs)


class TrackedStore(OriginalStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.visual_name = try_discover_name(self) or f"Store_{id(self)}"
        self.visual_type = "STORE"
        self.is_expanded = False
        tracked_resources.add(self)

    def put(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        register_interaction(self._env, self)
        return super().get(*args, **kwargs)


class TrackedEnvironment(simpy.Environment):
    def step(self):
        if not hasattr(self, "_step_count"):
            self._step_count = 0
        self._step_count += 1

        details = []
        event_queue = getattr(self, "_queue", [])

        if event_queue:
            try:
                next_item = event_queue[0]
                event = next_item[3]

                event_name = type(event).__name__
                details.append(f"Event: {event_name}")

                if event_name == "Timeout":
                    details.append(f"Delay: {event.value}")

                if hasattr(event, "resource"):
                    resource = event.resource
                    resource_name = getattr(resource, "visual_name", str(resource))
                    details.append(f"Resource: {resource_name}")

                if event_name == "Process" and hasattr(event, "name"):
                    details.append(f"Process: {event.name}")

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
                        details.append(f"Triggering: {', '.join(waiting_processes)}")
            except Exception as exc:
                details.append(f"(Error inspecting event: {exc})")
        else:
            details.append("No scheduled events (EmptySchedule incoming?)")

        step_logs.append(f"[{self.now:.2f}] [STEP {self._step_count}] {' | '.join(details)}")

        super().step()

        if self.active_process:
            step_logs.append(f"      -> Running inside process: {self.active_process.name}")


def apply_patch():
    """Applies Monkey Patch to SimPy classes."""
    simpy.Resource = TrackedResource
    simpy.Container = TrackedContainer
    simpy.Store = TrackedStore
    simpy.Environment = TrackedEnvironment
