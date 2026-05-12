import json
import tkinter as tk
from tkinter import ttk
import weakref
from .search_controller import TextSearchController
from .widget_utils import create_scrolled_treeview


class DetailsWindowManager:
    """Manages resource detail popup windows."""

    def __init__(self, app):
        self.app = app
        self.detail_windows = {}

    def open_details(self, resource):
        """Open (or focus) a details window for the given resource."""
        if resource is None:
            return
        self._open_details_window(resource)

    def _safe_item_text(self, item):
        try:
            if isinstance(item, (dict, list, tuple)):
                return json.dumps(item, ensure_ascii=False, sort_keys=True)
            return str(item)
        except Exception:
            return repr(item)

    def _collect_metrics_rows(self, resource):
        metrics_obj = getattr(resource, "metrics", None)
        if metrics_obj is None:
            return []

        names = [name for name in dir(metrics_obj) if not name.startswith("_")]
        rows = []
        for name in sorted(set(names)):
            try:
                value = getattr(metrics_obj, name)
            except Exception:
                continue
            if callable(value):
                continue
            rows.append((str(name), str(value)))
        return rows

    def _collect_resource_details(self, resource):
        class_name = resource.__class__.__name__
        visual_type = getattr(resource, "visual_type", class_name)
        name = getattr(resource, "visual_name", class_name)
        capacity = getattr(resource, "capacity", "N/A")

        occupied = "N/A"
        put_queue_count = 0
        get_queue_count = 0
        internal_queue_count = None
        store_items = None

        if class_name.endswith("Container"):
            occupied = getattr(resource, "level", 0)
            put_queue_count = len(getattr(resource, "put_queue", []))
            get_queue_count = len(getattr(resource, "get_queue", []))
        elif class_name.endswith("Store"):
            items = list(getattr(resource, "items", []))
            occupied = len(items)
            put_queue_count = len(getattr(resource, "put_queue", []))
            get_queue_count = len(getattr(resource, "get_queue", []))
            store_items = [f"[{idx}] {self._safe_item_text(item)}" for idx, item in enumerate(items)]
        elif class_name.endswith("Resource"):
            occupied = int(getattr(resource, "count", 0))
            internal_queue_count = len(getattr(resource, "queue", []))
            get_queue_count = int(internal_queue_count)

        sim_time = float(self.app.get_sim_time())

        return {
            "name": str(name),
            "visual_type": str(visual_type),
            "class_name": str(class_name),
            "capacity": str(capacity),
            "occupied": str(occupied),
            "put_queue_count": str(put_queue_count),
            "get_queue_count": str(get_queue_count),
            "internal_queue_count": "N/A" if internal_queue_count is None else str(internal_queue_count),
            "store_items": store_items,
            "sim_time": f"{sim_time:.2f}",
            "metrics_rows": self._collect_metrics_rows(resource),
            "is_store": bool(class_name.endswith("Store")),
        }

    def _open_details_window(self, resource):
        window_id = id(resource)
        existing = self.detail_windows.get(window_id)
        if existing and existing["window"].winfo_exists():
            existing["window"].deiconify()
            existing["window"].lift()
            existing["window"].focus_force()
            return

        details_win = tk.Toplevel(self.app)
        details_win.title("Resource Details")
        is_store_resource = resource.__class__.__name__.endswith("Store")
        base_width = 620
        base_height = 713
        min_width = 520
        min_height = 558

        if not is_store_resource:
            base_height = int(round(base_height * 0.8))
            min_height = int(round(min_height * 0.8))

        details_win.geometry(f"{base_width}x{base_height}")
        details_win.minsize(min_width, min_height)

        root = ttk.Frame(details_win, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        fields_frame = ttk.Frame(root)
        fields_frame.pack(fill=tk.X)

        row_defs = [
            ("Resource Name", "name"),
            ("Visual Type", "visual_type"),
            ("Class", "class_name"),
            ("Simulation Time", "sim_time"),
            ("Capacity", "capacity"),
            ("Occupied", "occupied"),
            ("Put Queue (full)", "put_queue_count"),
            ("Get Queue (full)", "get_queue_count"),
            ("Internal Queue", "internal_queue_count"),
        ]

        value_labels = {}
        for row, (label_text, key) in enumerate(row_defs):
            ttk.Label(fields_frame, text=f"{label_text}:", width=18, anchor="w").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=1)
            value = ttk.Label(fields_frame, text="-", anchor="w")
            value.grid(row=row, column=1, sticky="w", pady=1)
            value_labels[key] = value

        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(10, 8))

        ttk.Label(root, text="Active Metrics:").pack(anchor="w")
        metrics_frame, metrics_tree, _metrics_scroll = create_scrolled_treeview(
            root,
            columns=("metric", "value"),
            show="headings",
            selectmode="none",
            height=6,
        )
        metrics_frame.pack(fill=tk.BOTH, expand=False, pady=(4, 8))
        metrics_tree.heading("metric", text="Metric")
        metrics_tree.heading("value", text="Value")
        metrics_tree.column("metric", width=220, anchor="w", stretch=True)
        metrics_tree.column("value", width=320, anchor="w", stretch=True)

        store_separator = ttk.Separator(root, orient=tk.HORIZONTAL)
        store_separator.pack(fill=tk.X, pady=(10, 8))
        store_section = ttk.Frame(root)
        store_section.pack(fill=tk.BOTH, expand=True)
        store_label = ttk.Label(store_section, text="Store Items (detailed view):")
        store_label.pack(anchor="w")

        find_frame = ttk.Frame(store_section)
        find_frame.pack(fill=tk.X, pady=(4, 4))
        ttk.Label(find_frame, text="Find:").pack(side=tk.LEFT, padx=(0, 4))
        details_find_var = tk.StringVar(value="")
        ent_details_find = ttk.Entry(find_frame, textvariable=details_find_var, width=22)
        ent_details_find.pack(side=tk.LEFT)
        ent_details_find.bind("<KeyRelease>", lambda _event: self._refresh_details_search(window_id, reset_index=True))
        ent_details_find.bind("<Return>", lambda _event: self._details_find_next(window_id))
        ttk.Button(find_frame, text="◀", width=3, command=lambda: self._details_find_prev(window_id)).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(find_frame, text="▶", width=3, command=lambda: self._details_find_next(window_id)).pack(side=tk.LEFT)
        find_counter = ttk.Label(find_frame, text="0/0", width=6, anchor="e")
        find_counter.pack(side=tk.RIGHT)

        items_frame = ttk.Frame(store_section)
        items_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        items_scroll = ttk.Scrollbar(items_frame, orient=tk.VERTICAL)
        items_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        items_text = tk.Text(
            items_frame,
            font=("Consolas", 9),
            wrap=tk.NONE,
            yscrollcommand=items_scroll.set,
            state="disabled",
            bg="#fbfbfb",
        )
        items_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        items_text.tag_configure("details_find_match", background="#FFF59D")
        items_text.tag_configure("details_find_current", background="#FBC02D")
        items_scroll.config(command=items_text.yview)

        def on_close():
            self.detail_windows.pop(window_id, None)
            details_win.destroy()

        details_win.protocol("WM_DELETE_WINDOW", on_close)

        self.detail_windows[window_id] = {
            "window": details_win,
            "resource_ref": weakref.ref(resource),
            "value_labels": value_labels,
            "metrics_tree": metrics_tree,
            "metrics_frame": metrics_frame,
            "last_metrics_rows": None,
            "store_separator": store_separator,
            "store_section": store_section,
            "items_text": items_text,
            "last_items_blob": None,
            "find_var": details_find_var,
            "find_counter_label": find_counter,
            "search_controller": TextSearchController(
                items_text,
                "details_find_match",
                "details_find_current",
                on_counter_change=lambda _controller, wid=window_id: self._details_update_find_counter(wid),
            ),
        }
        self._refresh_details_window(window_id)

    def _details_update_find_counter(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return

        query = entry["find_var"].get().strip()
        controller = entry["search_controller"]
        total = len(controller.matches)
        index = controller.index

        if not query or total == 0 or index < 0:
            entry["find_counter_label"].config(text="0/0")
            return

        entry["find_counter_label"].config(text=f"{index + 1}/{total}")

    def _refresh_details_search(self, window_id, reset_index=False):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return
        entry["search_controller"].refresh(entry["find_var"].get().strip(), reset_index=reset_index)

    def _details_find_next(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return
        entry["search_controller"].find_next(entry["find_var"].get().strip())

    def _details_find_prev(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return
        entry["search_controller"].find_prev(entry["find_var"].get().strip())

    def _refresh_details_window(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return

        details_win = entry["window"]
        if not details_win.winfo_exists():
            self.detail_windows.pop(window_id, None)
            return

        resource = entry["resource_ref"]()
        if resource is None:
            for label in entry["value_labels"].values():
                label.config(text="Unavailable")
            metrics_rows = []
            show_store_section = False
            items_blob = "Resource no longer available."
        else:
            details = self._collect_resource_details(resource)
            entry["value_labels"]["name"].config(text=details["name"])
            entry["value_labels"]["visual_type"].config(text=details["visual_type"])
            entry["value_labels"]["class_name"].config(text=details["class_name"])
            entry["value_labels"]["sim_time"].config(text=details["sim_time"])
            entry["value_labels"]["capacity"].config(text=details["capacity"])
            entry["value_labels"]["occupied"].config(text=details["occupied"])
            entry["value_labels"]["put_queue_count"].config(text=details["put_queue_count"])
            entry["value_labels"]["get_queue_count"].config(text=details["get_queue_count"])
            entry["value_labels"]["internal_queue_count"].config(text=details["internal_queue_count"])
            metrics_rows = list(details.get("metrics_rows", []))
            show_store_section = bool(details.get("is_store", False))

            if details["store_items"] is None:
                items_blob = "Detailed items are available for Store resources only."
            elif not details["store_items"]:
                items_blob = "(Store is empty)"
            else:
                items_blob = "\n".join(details["store_items"])

        if metrics_rows != entry["last_metrics_rows"]:
            metrics_tree = entry["metrics_tree"]
            metrics_tree.delete(*metrics_tree.get_children())
            if metrics_rows:
                for metric_name, metric_value in metrics_rows:
                    metrics_tree.insert("", tk.END, values=(metric_name, metric_value))
            else:
                metrics_tree.insert("", tk.END, values=("-", "No active metrics"))
            entry["last_metrics_rows"] = metrics_rows

        metrics_frame = entry.get("metrics_frame")
        store_separator = entry.get("store_separator")
        store_section = entry.get("store_section")
        if show_store_section:
            if metrics_frame is not None:
                metrics_frame.pack_configure(expand=False)
            if store_separator is not None and not store_separator.winfo_ismapped():
                store_separator.pack(fill=tk.X, pady=(10, 8), before=store_section)
            if store_section is not None and not store_section.winfo_ismapped():
                store_section.pack(fill=tk.BOTH, expand=True)
        else:
            if metrics_frame is not None:
                metrics_frame.pack_configure(expand=True)
            if store_separator is not None and store_separator.winfo_ismapped():
                store_separator.pack_forget()
            if store_section is not None and store_section.winfo_ismapped():
                store_section.pack_forget()
            entry["search_controller"].clear()
            entry["find_counter_label"].config(text="0/0")

        if show_store_section and items_blob != entry["last_items_blob"]:
            items_text = entry["items_text"]
            items_text.config(state="normal")
            items_text.delete("1.0", tk.END)
            items_text.insert(tk.END, items_blob)
            items_text.config(state="disabled")
            entry["last_items_blob"] = items_blob
            if entry["find_var"].get().strip():
                self._refresh_details_search(window_id, reset_index=True)
            else:
                self._details_update_find_counter(window_id)

        self.app.after(300, lambda: self._refresh_details_window(window_id))
