import re
import tkinter as tk
from tkinter import ttk
from .widget_utils import create_scrolled_treeview


class InspectorPanel(ttk.Frame):
    """Right-side inspector panel with Breakpoints and Task Viewer tabs."""

    def __init__(self, parent, app):
        super().__init__(parent, relief="raised", borderwidth=1)
        self.pack(side=tk.RIGHT, fill=tk.Y)
        self.app = app

        self.collapsed = False
        self.panel_width = 320
        self.panel_min_width = 220
        self.panel_max_width = 1100
        self.resize_start_x = None
        self.resize_start_width = 0
        self.row_cache = []
        self.task_viewer_row_cache = []
        self.task_viewer_sort_column = None
        self.task_viewer_sort_state = 0
        self._refresh_job = None
        self.paused_breakpoint_ids = set()
        self.last_breakpoint_hit_step = None

        self._build_widgets()
        self.reset_initial_state()
        self._apply_panel_state()
        self.refresh()

    def _build_widgets(self):
        self.breakpoint_tab = tk.Canvas(
            self,
            width=26,
            bg="#d0d0d0",
            highlightthickness=0,
            cursor="hand2",
        )
        self.breakpoint_tab.bind("<Button-1>", lambda _event: self.toggle())
        self.breakpoint_tab.bind("<Configure>", self._redraw_breakpoint_tab)

        self.breakpoint_resize_handle = tk.Frame(self, width=5, bg="#d0d0d0", cursor="sb_h_double_arrow")
        self.breakpoint_resize_handle.pack(side=tk.LEFT, fill=tk.Y)
        self.breakpoint_resize_handle.bind("<ButtonPress-1>", self._start_breakpoint_resize)
        self.breakpoint_resize_handle.bind("<B1-Motion>", self._do_breakpoint_resize)
        self.breakpoint_resize_handle.bind("<ButtonRelease-1>", self._stop_breakpoint_resize)

        self.inner_frame = ttk.Frame(self, width=self.panel_width)
        self.inner_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.inner_frame.pack_propagate(False)

        header = ttk.Frame(self.inner_frame)
        header.pack(side=tk.TOP, fill=tk.X, padx=5, pady=4)

        self.btn_toggle = ttk.Button(
            header,
            text="▶",
            width=3,
            command=self.toggle,
        )
        self.btn_toggle.pack(side=tk.LEFT)

        self.breakpoint_notebook = ttk.Notebook(self.inner_frame)
        self.breakpoint_notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 6))

        self.breakpoint_tab_frame = ttk.Frame(self.breakpoint_notebook)
        self.task_viewer_tab_frame = ttk.Frame(self.breakpoint_notebook)
        self.breakpoint_notebook.add(self.breakpoint_tab_frame, text="Breakpoints")
        self.breakpoint_notebook.add(self.task_viewer_tab_frame, text="Task Viewer")

        tree_frame, self.breakpoint_tree, _bp_scroll = create_scrolled_treeview(
            self.breakpoint_tab_frame,
            columns=("id", "label", "pause", "hits", "edge", "condition"),
            show="headings",
            selectmode="browse",
            height=10,
        )
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.breakpoint_tree.heading("id", text="ID")
        self.breakpoint_tree.heading("label", text="Label")
        self.breakpoint_tree.heading("pause", text="Pause")
        self.breakpoint_tree.heading("hits", text="Hits")
        self.breakpoint_tree.heading("edge", text="Edge")
        self.breakpoint_tree.heading("condition", text="Condition")
        self.breakpoint_tree.column("id", width=40, anchor="center", stretch=False)
        self.breakpoint_tree.column("label", width=140, anchor="w", stretch=False)
        self.breakpoint_tree.column("pause", width=58, anchor="center", stretch=False)
        self.breakpoint_tree.column("hits", width=52, anchor="center", stretch=False)
        self.breakpoint_tree.column("edge", width=62, anchor="center", stretch=False)
        self.breakpoint_tree.column("condition", width=280, anchor="w", stretch=True)
        self.breakpoint_tree.tag_configure("bp_paused", background="#d9f7d9")
        self.breakpoint_tree.tag_configure("bp_error", background="#ffd9d9")
        self.breakpoint_tree.tag_configure("bp_disabled", foreground="#8e8e8e")
        self.breakpoint_tree.bind("<Button-1>", self._on_breakpoint_tree_click)

        task_tree_frame, self.task_tree, _task_scroll = create_scrolled_treeview(
            self.task_viewer_tab_frame,
            columns=("queue_order", "process", "yielding_on", "holding", "waiting"),
            show="headings",
            selectmode="browse",
            height=10,
        )
        task_tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.task_tree.heading("queue_order", text="#", command=lambda: self._on_task_viewer_heading_click("queue_order"))
        self.task_tree.heading("process", text="Process", command=lambda: self._on_task_viewer_heading_click("process"))
        self.task_tree.heading("yielding_on", text="Yielding On", command=lambda: self._on_task_viewer_heading_click("yielding_on"))
        self.task_tree.heading("holding", text="Holding", command=lambda: self._on_task_viewer_heading_click("holding"))
        self.task_tree.heading("waiting", text="Waiting On", command=lambda: self._on_task_viewer_heading_click("waiting"))
        self.task_tree.column("queue_order", width=30, anchor="center", stretch=False)
        self.task_tree.column("process", width=130, anchor="w", stretch=False)
        self.task_tree.column("yielding_on", width=95, anchor="w", stretch=False)
        self.task_tree.column("holding", width=80, anchor="w", stretch=True)
        self.task_tree.column("waiting", width=110, anchor="w", stretch=True)
        self.task_tree.bind("<Button-1>", self._on_task_viewer_click)

    def has_defined_breakpoints(self):
        return bool(self.app.list_breakpoints())

    def reset_initial_state(self):
        # Keep initial state stable and predictable before first render.
        self.paused_breakpoint_ids.clear()
        self.last_breakpoint_hit_step = None
        self.row_cache = []
        self.task_viewer_row_cache = []
        self.task_viewer_sort_column = None
        self.task_viewer_sort_state = 0
        self.collapsed = not self.has_defined_breakpoints()

    def _apply_panel_state(self):
        if not hasattr(self, "breakpoint_notebook"):
            return

        self.breakpoint_notebook.pack_forget()
        self.inner_frame.pack_forget()
        self.breakpoint_resize_handle.pack_forget()
        self.breakpoint_tab.pack_forget()

        if self.collapsed:
            self.breakpoint_tab.pack(side=tk.RIGHT, fill=tk.Y)
            self._redraw_breakpoint_tab()
            self.btn_toggle.config(text="◀")
            return

        self.breakpoint_resize_handle.pack(side=tk.LEFT, fill=tk.Y)
        self.inner_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.breakpoint_notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 6))
        self.btn_toggle.config(text="▶")

    def _describe_process_target(self, target):
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

    def _describe_process_resource(self, target):
        """Return only the resource/store/container name the process is waiting on."""
        if target is None:
            return None
        resource = getattr(target, "resource", None)
        if resource is None:
            return None
        return getattr(resource, "visual_name", None)

    def _task_viewer_queue_order_map(self, env):
        if env is None:
            return {}

        event_queue = getattr(env, "_queue", [])
        if not event_queue:
            return {}

        order_map = {}
        for idx, queue_item in enumerate(sorted(event_queue, key=lambda item: (item[0], item[1], item[2])), start=0):
            try:
                event = queue_item[3]
            except Exception:
                continue
            order_map.setdefault(id(event), idx)
        return order_map

    def _sort_task_viewer_rows(self, row_models):
        column = self.task_viewer_sort_column
        state = self.task_viewer_sort_state
        if not column or state == 0:
            return sorted(row_models, key=lambda item: item["original_order"])

        if column == "queue_order":
            with_queue = [item for item in row_models if item["queue_order_value"] is not None]
            without_queue = [item for item in row_models if item["queue_order_value"] is None]
            with_queue.sort(
                key=lambda item: (item["queue_order_value"], item["original_order"]),
                reverse=(state < 0),
            )
            return with_queue + without_queue

        def _string_key(item):
            value = item.get(column, "-")
            return (str(value).casefold(), item["original_order"])

        return sorted(row_models, key=_string_key, reverse=(state < 0))

    _TASK_VIEWER_HEADING_LABELS = {
        "queue_order": "#",
        "process": "Process",
        "yielding_on": "Yielding On",
        "holding": "Holding",
        "waiting": "Waiting On",
    }

    def _update_task_viewer_heading_arrows(self):
        arrow = {1: " ↑", -1: " ↓", 0: ""}
        for col, base in self._TASK_VIEWER_HEADING_LABELS.items():
            suffix = arrow[self.task_viewer_sort_state] if col == self.task_viewer_sort_column else ""
            self.task_tree.heading(col, text=base + suffix)

    def _on_task_viewer_heading_click(self, column_name):
        if self.task_viewer_sort_column != column_name:
            self.task_viewer_sort_column = column_name
            self.task_viewer_sort_state = 1
        elif self.task_viewer_sort_state == 1:
            self.task_viewer_sort_state = -1
        elif self.task_viewer_sort_state == -1:
            self.task_viewer_sort_column = None
            self.task_viewer_sort_state = 0
        else:
            self.task_viewer_sort_column = column_name
            self.task_viewer_sort_state = 1

        self._update_task_viewer_heading_arrows()
        self._refresh_task_viewer_panel(force=True)

    def _on_task_viewer_click(self, event):
        region = self.task_tree.identify("region", event.x, event.y)
        row_id = self.task_tree.identify_row(event.y)
        if not row_id and region != "heading":
            selected = self.task_tree.selection()
            if selected:
                self.task_tree.selection_remove(selected)
            self.task_tree.focus("")

    def _refresh_task_viewer_panel(self, force=False):
        if not hasattr(self, "task_tree"):
            return

        env = self.app.get_environment()
        process_states = getattr(env, "process_states", None) if env is not None else None
        queue_order_map = self._task_viewer_queue_order_map(env)

        row_models = []
        if process_states:
            for process, state in list(process_states.items()):
                if process is None:
                    continue
                if not bool(getattr(process, "is_alive", False)):
                    continue

                label = str(state.get("label") or getattr(process, "name", "process"))
                process_id = int(state.get("process_id", id(process)))
                target = getattr(process, "target", None)
                yielding_on = self._describe_process_target(target)
                queue_order_value = queue_order_map.get(id(target)) if target is not None else None

                holding_values = sorted(str(item) for item in state.get("holding", set()))
                queuing_values = sorted(str(item) for item in state.get("queuing", set()))
                if queuing_values:
                    stripped = [re.sub(r"\s*\(.*?\)\s*$", "", v).strip() or v for v in queuing_values]
                    waiting_display = ", ".join(stripped)
                else:
                    resource_name = self._describe_process_resource(target)
                    waiting_display = resource_name if resource_name else "-"

                row_models.append(
                    {
                        "original_order": int(state.get("creation_order", process_id)),
                        "process_id": process_id,
                        "process": f"{label} [{process_id}]",
                        "yielding_on": yielding_on,
                        "holding": ", ".join(holding_values) if holding_values else "-",
                        "waiting": waiting_display,
                        "queue_order": "-" if queue_order_value is None else str(queue_order_value),
                        "queue_order_value": queue_order_value,
                    }
                )

        row_models = self._sort_task_viewer_rows(row_models)
        rows = [(item["queue_order"], item["process"], item["yielding_on"], item["holding"], item["waiting"]) for item in row_models]

        if force or rows != self.task_viewer_row_cache:
            selected = self.task_tree.selection()
            selected_id = selected[0] if selected else None

            self.task_tree.delete(*self.task_tree.get_children())
            for item in row_models:
                iid = f"task_{item['process_id']}"
                values = (item["queue_order"], item["process"], item["yielding_on"], item["holding"], item["waiting"])
                self.task_tree.insert("", tk.END, iid=iid, values=values)

            if selected_id and self.task_tree.exists(selected_id):
                self.task_tree.selection_set(selected_id)
                self.task_tree.focus(selected_id)

            self.task_viewer_row_cache = rows

    def _redraw_breakpoint_tab(self, _event=None):
        if not hasattr(self, "breakpoint_tab"):
            return

        self.breakpoint_tab.delete("all")
        width = max(1, int(self.breakpoint_tab.winfo_width()))
        height = max(1, int(self.breakpoint_tab.winfo_height()))

        self.breakpoint_tab.create_text(width / 2, 14, text="◀", fill="#111", font=("Segoe UI", 9, "bold"))
        self.breakpoint_tab.create_text(
            width / 2,
            height / 2,
            text="Inspector",
            angle=90,
            fill="#111",
            font=("Segoe UI", 9, "bold"),
        )

    def toggle(self):
        self.collapsed = not self.collapsed
        self._apply_panel_state()

    def _start_breakpoint_resize(self, event):
        self.resize_start_x = event.x_root
        self.resize_start_width = max(self.panel_min_width, self.inner_frame.winfo_width())

    def _do_breakpoint_resize(self, event):
        if self.resize_start_x is None:
            return

        delta_x = self.resize_start_x - event.x_root
        new_width = self.resize_start_width + delta_x
        new_width = max(self.panel_min_width, min(self.panel_max_width, new_width))

        self.panel_width = int(new_width)
        self.inner_frame.configure(width=self.panel_width)
        self.update_idletasks()

    def _stop_breakpoint_resize(self, _event=None):
        self.resize_start_x = None
        self.resize_start_width = 0

    def _on_breakpoint_tree_click(self, event):
        region = self.breakpoint_tree.identify("region", event.x, event.y)
        row_id = self.breakpoint_tree.identify_row(event.y)

        if not row_id:
            current_selection = self.breakpoint_tree.selection()
            if current_selection:
                self.breakpoint_tree.selection_remove(current_selection)
            self.breakpoint_tree.focus("")
            return

        try:
            breakpoint_id = int(row_id)
        except ValueError:
            return

        bp_map = {getattr(bp, "id", None): bp for bp in self.app.list_breakpoints()}
        bp = bp_map.get(breakpoint_id)
        if bp is not None and not bool(getattr(bp, "enabled", True)):
            # Disabled breakpoints are intentionally non-interactive.
            current_selection = self.breakpoint_tree.selection()
            if current_selection:
                self.breakpoint_tree.selection_remove(current_selection)
            self.breakpoint_tree.focus("")
            return "break"

        if region != "cell":
            return

        column = self.breakpoint_tree.identify_column(event.x)
        try:
            col_index = int(column.lstrip("#")) - 1
        except ValueError:
            return

        columns = self.breakpoint_tree["columns"]
        if col_index < 0 or col_index >= len(columns):
            return

        if columns[col_index] != "pause":
            return

        if bp is None:
            return "break"

        new_value = not bool(getattr(bp, "pause_on_hit", True))
        self.app.set_breakpoint_pause_on_hit(breakpoint_id, new_value)
        self.refresh(force=True, reschedule=False)
        self.breakpoint_tree.selection_set(row_id)
        self.breakpoint_tree.focus(row_id)
        return "break"

    def refresh(self, force=False, reschedule=True):
        if not hasattr(self, "breakpoint_tree"):
            return

        self._refresh_job = None

        env = self.app.get_environment()
        current_step = getattr(env, "_step_count", None) if env is not None else None
        if self.last_breakpoint_hit_step is not None and current_step is not None and current_step != self.last_breakpoint_hit_step:
            self.paused_breakpoint_ids.clear()
            self.last_breakpoint_hit_step = None

        breakpoints = self.app.list_breakpoints()
        row_models = []
        for bp in breakpoints:
            row_models.append(
                {
                    "id": getattr(bp, "id", 0),
                    "label": str(getattr(bp, "label", "")),
                    "enabled": bool(getattr(bp, "enabled", True)),
                    "is_paused": int(getattr(bp, "id", 0)) in self.paused_breakpoint_ids,
                    "pause": "☑" if getattr(bp, "pause_on_hit", True) else "☐",
                    "hits": str(getattr(bp, "hit_count", 0)),
                    "edge": str(getattr(bp, "edge", "none")),
                    "condition": str(getattr(bp, "expression", "")),
                    "has_error": bool(getattr(bp, "last_error", None)),
                }
            )

        rows = [
            (
                model["id"],
                model["label"],
                model["enabled"],
                model["is_paused"],
                model["pause"],
                model["hits"],
                model["edge"],
                model["condition"],
                model["has_error"],
            )
            for model in row_models
        ]

        if force or rows != self.row_cache:
            selected = self.breakpoint_tree.selection()
            selected_id = selected[0] if selected else None

            self.breakpoint_tree.delete(*self.breakpoint_tree.get_children())
            for model in row_models:
                row_id = model["id"]
                iid = str(row_id)
                tags = ()
                if not model["enabled"]:
                    tags = ("bp_disabled",)
                elif model["has_error"]:
                    tags = ("bp_error",)
                elif model["is_paused"]:
                    tags = ("bp_paused",)
                values = (model["id"], model["label"], model["pause"], model["hits"], model["edge"], model["condition"])
                self.breakpoint_tree.insert("", tk.END, iid=iid, values=values, tags=tags)

            if selected_id and self.breakpoint_tree.exists(selected_id):
                self.breakpoint_tree.selection_set(selected_id)
                self.breakpoint_tree.focus(selected_id)

            self.row_cache = rows

        self._refresh_task_viewer_panel(force=force)

        if reschedule and self._refresh_job is None:
            self._refresh_job = self.after(350, self.refresh)

    def on_breakpoint_hit(self, event):
        """Called by MainWindow when a breakpoint fires."""
        step = event.get("step")
        if step is not None and step != self.last_breakpoint_hit_step:
            self.paused_breakpoint_ids.clear()
            self.last_breakpoint_hit_step = step

        breakpoint_id = event.get("breakpoint_id")
        if breakpoint_id is not None:
            self.paused_breakpoint_ids.add(int(breakpoint_id))

        self.refresh(force=True, reschedule=False)

    def on_breakpoint_added(self):
        """Called by MainWindow after adding a breakpoint."""
        if self.collapsed and self.has_defined_breakpoints():
            self.collapsed = False
            self._apply_panel_state()
        self.refresh(force=True, reschedule=False)

    def clear_hit_state(self):
        """Reset hit-tracking state (called on play/step/reset)."""
        self.paused_breakpoint_ids.clear()
        self.last_breakpoint_hit_step = None
        self.refresh(force=True, reschedule=False)
