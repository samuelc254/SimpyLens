from .sim_manager import SimulationController
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox
import math
import weakref
import gc
from pathlib import Path


class Viewer(tk.Tk):
    def __init__(self, model=None, title="SimPyLens", seed=None):
        """
        Initializes SimPyLens.

        :param model: A function that takes a simpy.Environment as its only argument
                      and sets up the simulation (creates resources, processes, etc).
        :param title: Window title.
        """
        super().__init__()
        self._app_icon_image = None
        self._set_app_icon()
        self.title(title)
        self.geometry("1000x800")

        self.env = None
        self.running = False
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        self.current_model = model

        self.obj_coords_cache = weakref.WeakKeyDictionary()
        self.active_animations = []
        self.active_list_widgets = {}
        self.manual_block_positions = weakref.WeakKeyDictionary()
        self.resource_world_positions = weakref.WeakKeyDictionary()
        self.resource_block_bounds = weakref.WeakKeyDictionary()
        self.resource_draw_order = []
        self.dragged_resource = None
        self.drag_start_canvas_x = 0
        self.drag_start_canvas_y = 0
        self.drag_start_world_x = 0.0
        self.drag_start_world_y = 0.0
        self.pan_active = False
        self.context_menu_resource = None
        self.right_press_resource = None
        self.right_press_canvas_x = 0.0
        self.right_press_canvas_y = 0.0
        self.right_press_root_x = 0
        self.right_press_root_y = 0
        self.right_press_moved = False
        self.manual_layout_by_name = {}
        self.detail_windows = {}
        self.last_breakpoint_hit = None
        self.layout_config_path = self._resolve_layout_config_path()
        self._load_manual_layout_cache()

        self.last_tick_time = time.time()
        self.tick_count = 0
        self.last_fps_update = 0

        self.log_enabled = tk.BooleanVar(value=True)
        self.log_collapsed = False
        self.log_widget = None
        self.max_log_lines = 2000
        self.log_search_var = tk.StringVar(value="")
        self.log_search_matches = []
        self.log_search_index = -1
        self.log_resize_start_y = None
        self.log_resize_start_height = 0
        self.log_content_min_height = 100
        self.log_content_max_height = 600

        self.breakpoint_panel_collapsed = False
        self.breakpoint_panel_width = 320
        self.breakpoint_panel_min_width = 220
        self.breakpoint_panel_max_width = 1100
        self.breakpoint_resize_start_x = None
        self.breakpoint_resize_start_width = 0
        self.breakpoint_row_cache = []
        self._breakpoint_refresh_job = None
        self.paused_breakpoint_id = None

        self._setup_top_bar()
        self.main_area = ttk.Frame(self)
        self.main_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.main_content = ttk.Frame(self.main_area)
        self.main_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._setup_log_panel()
        self._setup_canvas()

        self.sim_ctrl = SimulationController(
            draw_callback=lambda initial=False: (self.draw_scene(initial), self.update_idletasks()),
            start_animations_cb=self.start_animations,
            update_time_cb=self.update_time_display,
            schedule_cb=lambda ms, fn: self.after(ms, fn),
            speed_getter=lambda: self.scl_speed.get(),
            log_callback=self.log_message,
            on_breakpoint_cb=self._on_breakpoint_hit,
            seed=42 if seed is None else seed,
        )

        self._setup_breakpoint_panel()
        self._refresh_breakpoint_panel()

        if self.current_model:
            try:
                self.sim_ctrl.reset(self.current_model)
                self.after(100, self.center_view)
            except Exception as exc:
                messagebox.showerror("Simulation Error", f"Error in setup():\n{exc}")

    def _tracked_resources(self):
        env = self.sim_ctrl.env if hasattr(self, "sim_ctrl") and self.sim_ctrl else None
        if env is None:
            return ()
        return getattr(env, "tracked_resources", ())

    def _pending_transfers(self):
        env = self.sim_ctrl.env if hasattr(self, "sim_ctrl") and self.sim_ctrl else None
        if env is None:
            return []
        return getattr(env, "pending_transfers", [])

    def _set_app_icon(self):
        icon_path = Path(__file__).resolve().parents[0] / "assets" / "icon.png"
        if not icon_path.exists():
            return
        try:
            self._app_icon_image = tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, self._app_icon_image)
        except Exception:
            self._app_icon_image = None

    def _resolve_layout_config_path(self):
        setup_path = None
        if self.current_model and hasattr(self.current_model, "__code__"):
            setup_path = Path(self.current_model.__code__.co_filename).resolve()

        if setup_path is not None:
            return setup_path.parent / f".{setup_path.stem}.simpy_layout.json"

        return Path.cwd() / ".simpy_layout.json"

    def _load_manual_layout_cache(self):
        self.manual_layout_by_name = {}
        cfg = self.layout_config_path
        if not cfg.exists():
            return

        try:
            payload = json.loads(cfg.read_text(encoding="utf-8"))
            items = payload.get("manual_positions", {})
            if isinstance(items, dict):
                for name, coords in items.items():
                    if isinstance(coords, (list, tuple)) and len(coords) == 2:
                        self.manual_layout_by_name[str(name)] = (float(coords[0]), float(coords[1]))
        except Exception:
            self.manual_layout_by_name = {}

    def _save_manual_layout_cache(self):
        positions = {name: [float(coords[0]), float(coords[1])] for name, coords in self.manual_layout_by_name.items() if coords and len(coords) == 2}
        for resource in list(self._tracked_resources()):
            if resource not in self.manual_block_positions:
                continue
            coords = self.manual_block_positions.get(resource)
            if not coords or len(coords) != 2:
                continue
            name = getattr(resource, "visual_name", None)
            if not name:
                continue
            positions[str(name)] = [float(coords[0]), float(coords[1])]

        self.manual_layout_by_name = {name: (coords[0], coords[1]) for name, coords in positions.items()}
        payload = {"manual_positions": positions}
        try:
            self.layout_config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

    def _setup_top_bar(self):
        top_container = ttk.Frame(self)
        top_container.pack(side=tk.TOP, fill=tk.X)

        bar = ttk.Frame(top_container, padding=5)
        bar.pack(side=tk.TOP, fill=tk.X)

        btn_frame = ttk.Frame(bar)
        btn_frame.pack(side=tk.LEFT, padx=5)

        ttk.Button(
            btn_frame,
            text="▶ Play",
            command=self.on_play_click,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            btn_frame,
            text="⏯ Step",
            command=self.on_step_click,
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            btn_frame,
            text="⏸ Pause",
            command=lambda: self.sim_ctrl.pause(),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            btn_frame,
            text="⏹ Reset",
            command=self.on_reset_click,
        ).pack(side=tk.LEFT, padx=2)

        # --- Time + Step display panel ---
        info_frame = ttk.Frame(bar, relief="groove", padding=(8, 4))
        info_frame.pack(side=tk.LEFT, padx=16)

        # Time
        time_block = ttk.Frame(info_frame)
        time_block.pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(time_block, text="TIME", font=("Segoe UI", 7), foreground="#888").pack(side=tk.LEFT, padx=(0, 5))
        self.lbl_time = ttk.Label(time_block, text="—", font=("Consolas", 12, "bold"))
        self.lbl_time.pack(side=tk.LEFT)

        # Separator
        ttk.Separator(info_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16), pady=2)

        # Step
        step_block = ttk.Frame(info_frame)
        step_block.pack(side=tk.LEFT)
        ttk.Label(step_block, text="STEP", font=("Segoe UI", 7), foreground="#888").pack(side=tk.LEFT, padx=(0, 5))
        self.lbl_step = ttk.Label(step_block, text="—", font=("Consolas", 12, "bold"))
        self.lbl_step.pack(side=tk.LEFT)

        spd_frame = ttk.Frame(bar)
        spd_frame.pack(side=tk.LEFT, padx=20)
        ttk.Label(spd_frame, text="Speed:").pack(side=tk.LEFT)
        self.scl_speed = tk.Scale(spd_frame, from_=0, to=100, orient=tk.HORIZONTAL, showvalue=0, length=150)
        self.scl_speed.set(50)
        self.scl_speed.pack(side=tk.LEFT)

        self.lbl_speed_val = ttk.Label(spd_frame, text="0.0 tps", width=12)
        self.lbl_speed_val.pack(side=tk.LEFT, padx=(5, 0))

    def on_play_click(self):
        self.paused_breakpoint_id = None
        self._refresh_breakpoint_panel(force=True, reschedule=False)
        self.sim_ctrl.set_model(self.current_model)
        self.sim_ctrl.run()

    def on_step_click(self):
        self.paused_breakpoint_id = None
        self._refresh_breakpoint_panel(force=True, reschedule=False)
        self.sim_ctrl.set_model(self.current_model)
        self.sim_ctrl.run_single_step()

    def on_reset_click(self):
        self.paused_breakpoint_id = None
        self._refresh_breakpoint_panel(force=True, reschedule=False)
        self.sim_ctrl.reset(self.current_model)
        self.after(100, self.center_view)

    def _on_breakpoint_hit(self, event):
        self.last_breakpoint_hit = dict(event)
        if event.get("pause_on_hit", True):
            self.paused_breakpoint_id = event.get("breakpoint_id")
            self._refresh_breakpoint_panel(force=True, reschedule=False)

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

    def update_time_display(self, now):
        """Updates time label, step label and calculates ticks/s in the interface."""
        env = getattr(self.sim_ctrl, "env", None)
        step = getattr(env, "_step_count", 0) if env is not None else 0

        if step:
            self.lbl_time.config(text=f"{now:.4f}")
            self.lbl_step.config(text=str(step))
        else:
            self.lbl_time.config(text="—")
            self.lbl_step.config(text="—")

        current_time = time.time()
        self.tick_count += 1
        elapsed = current_time - self.last_fps_update

        if elapsed >= 0.5:
            if elapsed > 0:
                tps = self.tick_count / elapsed
                self.lbl_speed_val.config(text=f"{tps:.1f} tps")

            self.last_fps_update = current_time
            self.tick_count = 0

    def _setup_log_panel(self):
        """Sets up the log panel at the bottom."""
        self.bottom_panel = ttk.Frame(self, relief="raised", borderwidth=1)
        self.bottom_panel.pack(side=tk.BOTTOM, fill=tk.X)

        self.log_resize_handle = tk.Frame(self.bottom_panel, height=5, bg="#d0d0d0", cursor="sb_v_double_arrow")
        self.log_resize_handle.pack(side=tk.TOP, fill=tk.X)
        self.log_resize_handle.bind("<ButtonPress-1>", self._start_log_resize)
        self.log_resize_handle.bind("<B1-Motion>", self._do_log_resize)
        self.log_resize_handle.bind("<ButtonRelease-1>", self._stop_log_resize)

        header_frame = ttk.Frame(self.bottom_panel)
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)

        self.btn_toggle_log = ttk.Button(header_frame, text="▼ Logs", width=8, command=self.toggle_log_panel)
        self.btn_toggle_log.pack(side=tk.LEFT)

        ttk.Checkbutton(header_frame, text="Enable Logging", variable=self.log_enabled).pack(side=tk.LEFT, padx=10)
        self.btn_clear_log = ttk.Button(header_frame, text="Clear", command=self.clear_log)
        self.btn_clear_log.pack(side=tk.LEFT, padx=5)

        self.log_find_frame = ttk.Frame(header_frame)
        self.log_find_frame.pack(side=tk.RIGHT)
        ttk.Label(self.log_find_frame, text="Find:").pack(side=tk.LEFT, padx=(0, 4))
        self.ent_log_find = ttk.Entry(self.log_find_frame, textvariable=self.log_search_var, width=22)
        self.ent_log_find.pack(side=tk.LEFT)
        self.ent_log_find.bind("<KeyRelease>", self._on_log_find_changed)
        self.ent_log_find.bind("<Return>", self.find_next_log)
        ttk.Button(self.log_find_frame, text="◀", width=3, command=self.find_prev_log).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(self.log_find_frame, text="▶", width=3, command=self.find_next_log).pack(side=tk.LEFT)

        self.log_content_frame = ttk.Frame(self.bottom_panel, height=180)
        self.log_content_frame.pack(side=tk.TOP, fill=tk.X)
        self.log_content_frame.pack_propagate(False)

        scrollbar = ttk.Scrollbar(self.log_content_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.txt_log = tk.Text(
            self.log_content_frame,
            height=8,
            state="disabled",
            bg="#ffffff",
            fg="#333333",
            font=("Consolas", 9),
            yscrollcommand=scrollbar.set,
        )
        self.txt_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.txt_log.tag_configure("log_find_match", background="#FFF59D")
        self.txt_log.tag_configure("log_find_current", background="#FBC02D")

        self.log_find_popup = tk.Label(
            self.log_content_frame,
            text="0/0",
            bg="#1f2937",
            fg="white",
            padx=8,
            pady=3,
            relief="solid",
            borderwidth=1,
        )
        self.log_find_popup.place_forget()

        scrollbar.config(command=self.txt_log.yview)

    def _setup_breakpoint_panel(self):
        self.breakpoint_panel = ttk.Frame(self.main_area, relief="raised", borderwidth=1)
        self.breakpoint_panel.pack(side=tk.RIGHT, fill=tk.Y)

        self.breakpoint_tab = tk.Canvas(
            self.breakpoint_panel,
            width=26,
            bg="#d0d0d0",
            highlightthickness=0,
            cursor="hand2",
        )
        self.breakpoint_tab.bind("<Button-1>", lambda _event: self.toggle_breakpoint_panel())
        self.breakpoint_tab.bind("<Configure>", self._redraw_breakpoint_tab)

        self.breakpoint_resize_handle = tk.Frame(self.breakpoint_panel, width=5, bg="#d0d0d0", cursor="sb_h_double_arrow")
        self.breakpoint_resize_handle.pack(side=tk.LEFT, fill=tk.Y)
        self.breakpoint_resize_handle.bind("<ButtonPress-1>", self._start_breakpoint_resize)
        self.breakpoint_resize_handle.bind("<B1-Motion>", self._do_breakpoint_resize)
        self.breakpoint_resize_handle.bind("<ButtonRelease-1>", self._stop_breakpoint_resize)

        self.breakpoint_inner = ttk.Frame(self.breakpoint_panel, width=self.breakpoint_panel_width)
        self.breakpoint_inner.pack(side=tk.LEFT, fill=tk.Y)
        self.breakpoint_inner.pack_propagate(False)

        header = ttk.Frame(self.breakpoint_inner)
        header.pack(side=tk.TOP, fill=tk.X, padx=5, pady=4)

        self.btn_toggle_breakpoint_panel = ttk.Button(
            header,
            text="▶",
            width=3,
            command=self.toggle_breakpoint_panel,
        )
        self.btn_toggle_breakpoint_panel.pack(side=tk.LEFT)

        self.breakpoint_content = ttk.Frame(self.breakpoint_inner)
        self.breakpoint_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 6))

        tree_frame = ttk.Frame(self.breakpoint_content)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        bp_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        bp_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.breakpoint_tree = ttk.Treeview(
            tree_frame,
            columns=("id", "label", "pause", "hits", "edge", "condition"),
            show="headings",
            selectmode="browse",
            yscrollcommand=bp_scroll.set,
            height=10,
        )
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
        self.breakpoint_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.breakpoint_tree.bind("<Button-1>", self._on_breakpoint_tree_click)
        bp_scroll.config(command=self.breakpoint_tree.yview)

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
            text="Breakpoint",
            angle=90,
            fill="#111",
            font=("Segoe UI", 9, "bold"),
        )

    def toggle_breakpoint_panel(self):
        if self.breakpoint_panel_collapsed:
            self.breakpoint_tab.pack_forget()
            self.breakpoint_resize_handle.pack(side=tk.LEFT, fill=tk.Y)
            self.breakpoint_inner.pack(side=tk.LEFT, fill=tk.Y)
            self.breakpoint_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=5, pady=(0, 6))
            self.btn_toggle_breakpoint_panel.config(text="▶")
            self.breakpoint_panel_collapsed = False
        else:
            self.breakpoint_content.pack_forget()
            self.breakpoint_inner.pack_forget()
            self.breakpoint_resize_handle.pack_forget()
            self.breakpoint_tab.pack(side=tk.RIGHT, fill=tk.Y)
            self._redraw_breakpoint_tab()
            self.breakpoint_panel_collapsed = True

    def _start_breakpoint_resize(self, event):
        self.breakpoint_resize_start_x = event.x_root
        self.breakpoint_resize_start_width = max(self.breakpoint_panel_min_width, self.breakpoint_inner.winfo_width())

    def _do_breakpoint_resize(self, event):
        if self.breakpoint_resize_start_x is None:
            return

        delta_x = self.breakpoint_resize_start_x - event.x_root
        new_width = self.breakpoint_resize_start_width + delta_x
        new_width = max(self.breakpoint_panel_min_width, min(self.breakpoint_panel_max_width, new_width))

        self.breakpoint_panel_width = int(new_width)
        self.breakpoint_inner.configure(width=self.breakpoint_panel_width)
        self.update_idletasks()

    def _stop_breakpoint_resize(self, _event=None):
        self.breakpoint_resize_start_x = None
        self.breakpoint_resize_start_width = 0

    def _on_breakpoint_tree_click(self, event):
        region = self.breakpoint_tree.identify("region", event.x, event.y)
        row_id = self.breakpoint_tree.identify_row(event.y)

        if not row_id:
            current_selection = self.breakpoint_tree.selection()
            if current_selection:
                self.breakpoint_tree.selection_remove(current_selection)
            self.breakpoint_tree.focus("")
            return

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

        try:
            breakpoint_id = int(row_id)
        except ValueError:
            return

        bp_map = {getattr(bp, "id", None): bp for bp in self.sim_ctrl.list_breakpoints()}
        bp = bp_map.get(breakpoint_id)
        if bp is None:
            return "break"

        new_value = not bool(getattr(bp, "pause_on_hit", True))
        self.sim_ctrl.set_breakpoint_pause_on_hit(breakpoint_id, new_value)
        self._refresh_breakpoint_panel(force=True, reschedule=False)
        self.breakpoint_tree.selection_set(row_id)
        self.breakpoint_tree.focus(row_id)
        return "break"

    def _refresh_breakpoint_panel(self, force=False, reschedule=True):
        if not hasattr(self, "breakpoint_tree"):
            return

        self._breakpoint_refresh_job = None

        breakpoints = self.sim_ctrl.list_breakpoints() if hasattr(self, "sim_ctrl") and self.sim_ctrl else []
        row_models = []
        for bp in breakpoints:
            row_models.append(
                {
                    "id": getattr(bp, "id", 0),
                    "label": str(getattr(bp, "label", "")),
                    "pause": "☑" if getattr(bp, "pause_on_hit", True) else "☐",
                    "hits": str(getattr(bp, "hit_count", 0)),
                    "edge": str(getattr(bp, "edge", "none")),
                    "condition": str(getattr(bp, "expression", "")),
                    "has_error": bool(getattr(bp, "last_error", None)),
                }
            )

        rows = [(model["id"], model["label"], model["pause"], model["hits"], model["edge"], model["condition"], model["has_error"]) for model in row_models]

        if force or rows != self.breakpoint_row_cache:
            selected = self.breakpoint_tree.selection()
            selected_id = selected[0] if selected else None

            self.breakpoint_tree.delete(*self.breakpoint_tree.get_children())
            for model in row_models:
                row_id = model["id"]
                iid = str(row_id)
                tags = ()
                if model["has_error"]:
                    tags = ("bp_error",)
                elif self.paused_breakpoint_id == row_id:
                    tags = ("bp_paused",)
                values = (model["id"], model["label"], model["pause"], model["hits"], model["edge"], model["condition"])
                self.breakpoint_tree.insert("", tk.END, iid=iid, values=values, tags=tags)

            if selected_id and self.breakpoint_tree.exists(selected_id):
                self.breakpoint_tree.selection_set(selected_id)
                self.breakpoint_tree.focus(selected_id)

            self.breakpoint_row_cache = rows

        if reschedule and self._breakpoint_refresh_job is None:
            self._breakpoint_refresh_job = self.after(350, self._refresh_breakpoint_panel)

    def toggle_log_panel(self):
        if self.log_collapsed:
            self.log_content_frame.pack(side=tk.TOP, fill=tk.X)
            self.btn_clear_log.pack(side=tk.LEFT, padx=5)
            self.log_find_frame.pack(side=tk.RIGHT)
            self.btn_toggle_log.config(text="▼ Logs")
            self.log_collapsed = False
            self._update_log_find_counter()
        else:
            self.log_content_frame.pack_forget()
            self.btn_clear_log.pack_forget()
            self.log_find_frame.pack_forget()
            self.log_find_popup.place_forget()
            self.btn_toggle_log.config(text="▲ Logs")
            self.log_collapsed = True

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")
        self.log_search_matches = []
        self.log_search_index = -1
        self._update_log_find_counter()

    def _start_log_resize(self, event):
        self.log_resize_start_y = event.y_root
        self.log_resize_start_height = max(self.log_content_min_height, self.log_content_frame.winfo_height())

    def _do_log_resize(self, event):
        if self.log_resize_start_y is None:
            return

        delta_y = self.log_resize_start_y - event.y_root
        new_height_px = self.log_resize_start_height + delta_y
        new_height_px = max(self.log_content_min_height, min(self.log_content_max_height, new_height_px))

        self.log_content_frame.configure(height=int(new_height_px))
        self.bottom_panel.update_idletasks()

    def _stop_log_resize(self, _event=None):
        self.log_resize_start_y = None
        self.log_resize_start_height = 0

    def _update_log_find_counter(self):
        query = self.log_search_var.get().strip()
        if not query or self.log_collapsed:
            self.log_find_popup.place_forget()
            return

        total = len(self.log_search_matches)
        if total == 0 or self.log_search_index < 0:
            self.log_find_popup.config(text="0/0")
            self.log_find_popup.place(relx=1.0, x=-26, rely=1.0, y=-8, anchor="se")
            return
        self.log_find_popup.config(text=f"{self.log_search_index + 1}/{total}")
        self.log_find_popup.place(relx=1.0, x=-26, rely=1.0, y=-8, anchor="se")

    def _on_log_find_changed(self, _event=None):
        self._refresh_log_search_highlights(reset_index=True)

    def _refresh_log_search_highlights(self, reset_index=False):
        query = self.log_search_var.get().strip()

        self.txt_log.config(state="normal")
        self.txt_log.tag_remove("log_find_match", "1.0", tk.END)
        self.txt_log.tag_remove("log_find_current", "1.0", tk.END)

        self.log_search_matches = []

        if not query:
            self.log_search_index = -1
            self._update_log_find_counter()
            self.txt_log.config(state="disabled")
            return

        start = "1.0"
        query_len = len(query)
        while True:
            pos = self.txt_log.search(query, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{query_len}c"
            self.txt_log.tag_add("log_find_match", pos, end_pos)
            self.log_search_matches.append((pos, end_pos))
            start = end_pos

        if not self.log_search_matches:
            self.log_search_index = -1
            self._update_log_find_counter()
            self.txt_log.config(state="disabled")
            return

        if reset_index or self.log_search_index < 0 or self.log_search_index >= len(self.log_search_matches):
            self.log_search_index = 0

        self._highlight_current_log_match()
        self.txt_log.config(state="disabled")

    def _highlight_current_log_match(self):
        self.txt_log.tag_remove("log_find_current", "1.0", tk.END)

        if not self.log_search_matches or self.log_search_index < 0:
            self._update_log_find_counter()
            return

        start, end = self.log_search_matches[self.log_search_index]
        self.txt_log.tag_add("log_find_current", start, end)
        self.txt_log.see(start)
        self._update_log_find_counter()

    def find_next_log(self, _event=None):
        self._refresh_log_search_highlights(reset_index=False)
        if not self.log_search_matches:
            return

        self.log_search_index = (self.log_search_index + 1) % len(self.log_search_matches)
        self.txt_log.config(state="normal")
        self._highlight_current_log_match()
        self.txt_log.config(state="disabled")

    def find_prev_log(self, _event=None):
        self._refresh_log_search_highlights(reset_index=False)
        if not self.log_search_matches:
            return

        self.log_search_index = (self.log_search_index - 1) % len(self.log_search_matches)
        self.txt_log.config(state="normal")
        self._highlight_current_log_match()
        self.txt_log.config(state="disabled")

    def _format_json_log(self, payload):
        if not isinstance(payload, dict):
            return str(payload)

        kind = payload.get("kind", "")
        event = payload.get("event", "")
        timestamp = float(payload.get("time", 0.0))
        message = payload.get("message", "")
        data = payload.get("data") or {}

        def _trunc(text, limit=100):
            text = str(text)
            return text if len(text) <= limit else text[:limit] + "..."

        # --- SIM ---
        if kind == "SIM":
            return f"[{timestamp:.2f}] [SIM] {message}"

        # --- STEP ---
        if kind == "STEP":
            if event == "STEP_BEFORE":
                step = data.get("step", "?")
                sim_ev = data.get("sim_event", "?")
                extras = []
                if "triggering" in data:
                    extras.append(f"triggering={','.join(data['triggering'])}")
                if "delay" in data:
                    extras.append(f"delay={data['delay']}")
                if "resource" in data:
                    extras.append(f"resource={data['resource']}")
                if "process" in data and "triggering" not in data:
                    extras.append(f"process={data['process']}")
                suffix = " | " + " | ".join(extras) if extras else ""
                return f"[{timestamp:.2f}] [STEP \u25b6 {step}] {sim_ev}{suffix}"

            if event == "STEP_AFTER":
                step = data.get("step", "?")
                active = data.get("active_process", "-")
                return f"[{timestamp:.2f}] [STEP \u25c4 {step}] active={active}"

            return f"[{timestamp:.2f}] [STEP] {message}"

        # --- RESOURCE ---
        if kind == "RESOURCE":
            process_name = data.get("process", "?")
            resource_name = data.get("resource", "?")
            from_name = data.get("from", "?")
            to_name = data.get("to", "?")
            extras = []
            if "amount" in data:
                extras.append(f"amount={data['amount']}")
            if "item" in data:
                extras.append(f"item={_trunc(data['item'], 40)}")
            if "filter" in data:
                extras.append(f"filter={_trunc(data['filter'], 40)}")
            suffix = " | " + " | ".join(extras) if extras else ""
            move = f"({from_name} \u2192 {to_name})"
            if message:
                return f"[{timestamp:.2f}] [RESOURCE] {message}  {move}{suffix}"
            return f"[{timestamp:.2f}] [RESOURCE] {process_name} {event.lower()} {resource_name}  {move}{suffix}"

        # --- BREAKPOINT ---
        if kind == "BREAKPOINT":
            label = data.get("label") or data.get("condition", "-")
            condition = data.get("condition", "-")
            if event == "BREAKPOINT_HIT":
                hit_count = data.get("hit_count", "?")
                cond_str = _trunc(condition, 80)
                if str(label) == str(condition):
                    return f"[{timestamp:.2f}] [BREAKPOINT \u25cf] {cond_str} | hits={hit_count}"
                return f"[{timestamp:.2f}] [BREAKPOINT \u25cf] {label} | condition={cond_str} | hits={hit_count}"

            if event == "BREAKPOINT_ERROR":
                error_text = _trunc(data.get("error", "-"), 80)
                cond_str = _trunc(condition, 60)
                if str(label) == str(condition):
                    return f"[{timestamp:.2f}] [BREAKPOINT \u2717] {cond_str} | error={error_text}"
                return f"[{timestamp:.2f}] [BREAKPOINT \u2717] {label} | condition={cond_str} | error={error_text}"

            return f"[{timestamp:.2f}] [BREAKPOINT] {message}"

        # --- STATUS / fallback ---
        if message:
            return f"[{timestamp:.2f}] [STATUS] {message}"

        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def log_message(self, messages):
        """Receives a list of log strings and displays them."""
        if not self.log_enabled.get():
            return

        self.txt_log.config(state="normal")
        for msg in messages:
            line = msg
            if isinstance(msg, str):
                stripped = msg.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        payload = json.loads(stripped)
                        line = self._format_json_log(payload)
                    except json.JSONDecodeError:
                        line = msg
            self.txt_log.insert(tk.END, str(line) + "\n")

        total_lines = int(self.txt_log.index("end-1c").split(".")[0])
        if total_lines > self.max_log_lines:
            lines_to_trim = total_lines - self.max_log_lines
            self.txt_log.delete("1.0", f"{lines_to_trim + 1}.0")

        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")
        if self.log_search_var.get().strip():
            self._refresh_log_search_highlights(reset_index=False)

    def _format_queue_badge_count(self, value):
        try:
            count = int(value)
        except (TypeError, ValueError):
            return str(value)

        if count <= 0:
            return "0"

        if count > 99999:
            return "99k+"

        if count >= 10000:
            rounded_k = int(round(count / 1000.0))
            rounded_k = max(10, min(99, rounded_k))
            return f"{rounded_k}k"

        return str(count)

    def _open_details_for_selected(self):
        resource = self.context_menu_resource
        self.context_menu_resource = None
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

        sim_time = 0.0
        if hasattr(self, "sim_ctrl") and self.sim_ctrl and self.sim_ctrl.env is not None:
            sim_time = float(self.sim_ctrl.env.now)

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

        details_win = tk.Toplevel(self)
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
        metrics_frame = ttk.Frame(root)
        metrics_frame.pack(fill=tk.BOTH, expand=False, pady=(4, 8))
        metrics_scroll = ttk.Scrollbar(metrics_frame, orient=tk.VERTICAL)
        metrics_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        metrics_tree = ttk.Treeview(
            metrics_frame,
            columns=("metric", "value"),
            show="headings",
            selectmode="none",
            yscrollcommand=metrics_scroll.set,
            height=6,
        )
        metrics_tree.heading("metric", text="Metric")
        metrics_tree.heading("value", text="Value")
        metrics_tree.column("metric", width=220, anchor="w", stretch=True)
        metrics_tree.column("value", width=320, anchor="w", stretch=True)
        metrics_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        metrics_scroll.config(command=metrics_tree.yview)

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
            "find_matches": [],
            "find_index": -1,
            "find_counter_label": find_counter,
        }
        self._refresh_details_window(window_id)

    def _details_update_find_counter(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return

        query = entry["find_var"].get().strip()
        total = len(entry["find_matches"])
        index = entry["find_index"]

        if not query or total == 0 or index < 0:
            entry["find_counter_label"].config(text="0/0")
            return

        entry["find_counter_label"].config(text=f"{index + 1}/{total}")

    def _highlight_current_details_match(self, window_id):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return

        items_text = entry["items_text"]
        items_text.tag_remove("details_find_current", "1.0", tk.END)

        if not entry["find_matches"] or entry["find_index"] < 0:
            self._details_update_find_counter(window_id)
            return

        start, end = entry["find_matches"][entry["find_index"]]
        items_text.tag_add("details_find_current", start, end)
        items_text.see(start)
        self._details_update_find_counter(window_id)

    def _refresh_details_search(self, window_id, reset_index=False):
        entry = self.detail_windows.get(window_id)
        if not entry:
            return

        items_text = entry["items_text"]
        query = entry["find_var"].get().strip()

        items_text.config(state="normal")
        items_text.tag_remove("details_find_match", "1.0", tk.END)
        items_text.tag_remove("details_find_current", "1.0", tk.END)
        entry["find_matches"] = []

        if not query:
            entry["find_index"] = -1
            self._details_update_find_counter(window_id)
            items_text.config(state="disabled")
            return

        start = "1.0"
        query_len = len(query)
        while True:
            pos = items_text.search(query, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{query_len}c"
            items_text.tag_add("details_find_match", pos, end_pos)
            entry["find_matches"].append((pos, end_pos))
            start = end_pos

        if not entry["find_matches"]:
            entry["find_index"] = -1
            self._details_update_find_counter(window_id)
            items_text.config(state="disabled")
            return

        if reset_index or entry["find_index"] < 0 or entry["find_index"] >= len(entry["find_matches"]):
            entry["find_index"] = 0

        self._highlight_current_details_match(window_id)
        items_text.config(state="disabled")

    def _details_find_next(self, window_id):
        self._refresh_details_search(window_id, reset_index=False)
        entry = self.detail_windows.get(window_id)
        if not entry or not entry["find_matches"]:
            return

        entry["find_index"] = (entry["find_index"] + 1) % len(entry["find_matches"])
        entry["items_text"].config(state="normal")
        self._highlight_current_details_match(window_id)
        entry["items_text"].config(state="disabled")

    def _details_find_prev(self, window_id):
        self._refresh_details_search(window_id, reset_index=False)
        entry = self.detail_windows.get(window_id)
        if not entry or not entry["find_matches"]:
            return

        entry["find_index"] = (entry["find_index"] - 1) % len(entry["find_matches"])
        entry["items_text"].config(state="normal")
        self._highlight_current_details_match(window_id)
        entry["items_text"].config(state="disabled")

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
            entry["find_matches"] = []
            entry["find_index"] = -1
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

        self.after(300, lambda: self._refresh_details_window(window_id))

    def _setup_canvas(self):
        self.canvas_frame = tk.Frame(self.main_content)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#f0f0f0")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.btn_center = tk.Button(
            self.canvas,
            text="🎯 Center View",
            command=self.center_view,
            bg="white",
            relief="raised",
        )
        self.btn_center.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-20)

        self.block_context_menu = tk.Menu(self, tearoff=0)
        self.block_context_menu.add_command(label="Return to Auto Layout", command=self.restore_auto_layout_for_selected)

        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<ButtonPress-3>", self.on_right_press)
        self.canvas.bind("<B3-Motion>", self.on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_release)
        self.canvas.bind("<MouseWheel>", self.do_zoom)
        self.canvas.bind("<Button-4>", self.do_zoom)
        self.canvas.bind("<Button-5>", self.do_zoom)

    def _toggle_expand_at_point(self, cx, cy):
        clicked_items = self.canvas.find_overlapping(cx, cy, cx + 1, cy + 1)

        for item in clicked_items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("btn_expand_"):
                    try:
                        object_id = int(tag.split("_")[-1])
                        target_resource = None
                        for resource in self._tracked_resources():
                            if id(resource) == object_id:
                                target_resource = resource
                                break

                        if target_resource:
                            current_state = getattr(target_resource, "is_expanded", False)
                            target_resource.is_expanded = not current_state
                            self.draw_scene()
                    except (ValueError, IndexError):
                        pass
                    return True
        return False

    def _resource_at_canvas_point(self, cx, cy):
        for resource in reversed(self.resource_draw_order):
            bounds = self.resource_block_bounds.get(resource)
            if not bounds:
                continue
            x1, y1, x2, y2 = bounds
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                return resource
        return None

    def _compute_auto_layout_world_positions(self, auto_resources):
        positions = {}
        if not auto_resources:
            return positions

        col_y_offsets = {}
        if len(auto_resources) <= 36:
            mode = "SQUARE"
            grid_dim = math.ceil(math.sqrt(max(1, len(auto_resources))))
        else:
            mode = "RECT"
            fixed_rows = 6

        for i, resource in enumerate(auto_resources):
            if mode == "SQUARE":
                col_logical = i % grid_dim
            else:
                col_logical = i // fixed_rows

            base_h_world = 100
            expanded_h_world = (base_h_world * 2) + 20
            current_height_world = expanded_h_world if getattr(resource, "is_expanded", False) else base_h_world

            col_width_world = 320
            x_world = 50 + (col_logical * col_width_world)

            if col_logical not in col_y_offsets:
                col_y_offsets[col_logical] = 50

            y_world = col_y_offsets[col_logical]
            positions[resource] = (float(x_world), float(y_world))
            col_y_offsets[col_logical] += current_height_world + 20

        return positions

    def _is_resource_aligned_to_auto_layout(self, resource, tolerance=0.5):
        if resource is None:
            return True

        resource_list = list(self._tracked_resources())
        resource_list.sort(key=lambda item: getattr(item, "visual_name", str(id(item))))
        if resource not in resource_list:
            return True

        if resource not in self.manual_block_positions:
            return True

        auto_resources = [item for item in resource_list if item not in self.manual_block_positions or item is resource]
        auto_positions = self._compute_auto_layout_world_positions(auto_resources)
        expected = auto_positions.get(resource)
        current = self.manual_block_positions.get(resource)
        if not expected or not current:
            return True

        return abs(current[0] - expected[0]) <= tolerance and abs(current[1] - expected[1]) <= tolerance

    def on_left_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if self._toggle_expand_at_point(cx, cy):
            return

        resource = self._resource_at_canvas_point(cx, cy)
        if resource is None:
            self.dragged_resource = None
            return

        current_world = self.resource_world_positions.get(resource)
        if current_world is None:
            return

        self.dragged_resource = resource
        self.drag_start_canvas_x = event.x
        self.drag_start_canvas_y = event.y
        self.drag_start_world_x, self.drag_start_world_y = current_world

    def on_left_drag(self, event):
        if self.dragged_resource is None:
            return

        dx = event.x - self.drag_start_canvas_x
        dy = event.y - self.drag_start_canvas_y

        if abs(dx) < 1 and abs(dy) < 1:
            return

        scale = self.scale if self.scale != 0 else 1.0
        new_world_x = self.drag_start_world_x + (dx / scale)
        new_world_y = self.drag_start_world_y + (dy / scale)
        self.manual_block_positions[self.dragged_resource] = (new_world_x, new_world_y)
        self.draw_scene()

    def on_left_release(self, _event):
        if self.dragged_resource is not None:
            self._save_manual_layout_cache()
        self.dragged_resource = None

    def on_right_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        resource = self._resource_at_canvas_point(cx, cy)
        self.right_press_resource = resource
        self.right_press_canvas_x = cx
        self.right_press_canvas_y = cy
        self.right_press_root_x = event.x_root
        self.right_press_root_y = event.y_root
        self.right_press_moved = False
        self.start_pan(event)
        self.pan_active = True

    def on_right_drag(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        if abs(cx - self.right_press_canvas_x) > 3 or abs(cy - self.right_press_canvas_y) > 3:
            self.right_press_moved = True

        if not self.pan_active:
            return
        self.do_pan(event)

    def on_right_release(self, event):
        released_resource = self._resource_at_canvas_point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        if self.right_press_resource is not None and not self.right_press_moved and released_resource is self.right_press_resource:
            self.context_menu_resource = released_resource
            self.block_context_menu.delete(0, tk.END)
            self.block_context_menu.add_command(label="Details", command=self._open_details_for_selected)
            if not self._is_resource_aligned_to_auto_layout(released_resource):
                self.block_context_menu.add_separator()
                self.block_context_menu.add_command(label="Return to Auto Layout", command=self.restore_auto_layout_for_selected)
            try:
                if self.block_context_menu.index("end") is not None:
                    self.block_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.block_context_menu.grab_release()

        self.right_press_resource = None
        self.right_press_moved = False

        if self.pan_active:
            self.stop_pan(event)
        self.pan_active = False

    def restore_auto_layout_for_selected(self):
        resource = self.context_menu_resource
        self.context_menu_resource = None
        if resource is None:
            return
        try:
            del self.manual_block_positions[resource]
        except KeyError:
            return
        name = getattr(resource, "visual_name", None)
        if name and name in self.manual_layout_by_name:
            del self.manual_layout_by_name[name]
        self._save_manual_layout_cache()
        self.draw_scene()

    def start_pan(self, event):
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def stop_pan(self, event):
        pass

    def do_pan(self, event):
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y

        if abs(dx) < 2 and abs(dy) < 2:
            return

        self.canvas.move("all", dx, dy)
        self.offset_x += dx
        self.offset_y += dy
        for resource, bounds in list(self.resource_block_bounds.items()):
            x1, y1, x2, y2 = bounds
            self.resource_block_bounds[resource] = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def do_zoom(self, event):
        world_x = (event.x - self.offset_x) / self.scale
        world_y = (event.y - self.offset_y) / self.scale

        if event.delta > 0 or event.num == 4:
            factor = 1.1
        else:
            factor = 0.9

        new_scale = self.scale * factor
        if new_scale < 0.1 or new_scale > 5.0:
            return

        self.scale = new_scale
        self.offset_x = event.x - (world_x * self.scale)
        self.offset_y = event.y - (world_y * self.scale)
        self.draw_scene()

    def center_view(self):
        pending_transfers = self._pending_transfers()
        if pending_transfers:
            pending_transfers.clear()
        self.active_animations = []
        gc.collect()

        # First pass at scale=1.0 to measure content bounding box
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.draw_scene()
        self.update_idletasks()

        bbox = self.canvas.bbox("all")
        if not bbox:
            return

        content_w = bbox[2] - bbox[0]
        content_h = bbox[3] - bbox[1]
        canvas_w = self.canvas.winfo_width() - 100
        canvas_h = self.canvas.winfo_height() - 100

        if canvas_w <= 0 or canvas_h <= 0:
            return

        desired_scale = 1.0
        if content_w > 0 and content_h > 0:
            desired_scale = min(canvas_w / content_w, canvas_h / content_h)
            desired_scale = min(desired_scale, 1.0)
            desired_scale = max(desired_scale, 0.1)

        # Second pass at desired_scale to measure scaled bounding box
        self.scale = desired_scale
        self.offset_x = 0
        self.offset_y = 0
        self.draw_scene()
        self.update_idletasks()

        bbox_new = self.canvas.bbox("all")
        if bbox_new:
            new_w = bbox_new[2] - bbox_new[0]
            new_h = bbox_new[3] - bbox_new[1]

            center_x = self.canvas.winfo_width() / 2
            center_y = self.canvas.winfo_height() / 2

            content_center_x = bbox_new[0] + new_w / 2
            content_center_y = bbox_new[1] + new_h / 2

            # Update offset and redraw so resource_block_bounds reflects
            # the final canvas positions (canvas.move would leave them stale)
            self.offset_x = center_x - content_center_x
            self.offset_y = center_y - content_center_y
            self.draw_scene()
            self.obj_coords_cache = weakref.WeakKeyDictionary()

    def start_animations(self, transfers, duration_ms, on_complete=None):
        """Starts a smooth animation of moving balls between resources."""
        target_step_time = 33

        if not transfers:
            if on_complete:
                on_complete()
            return

        # Ensure resources created in the current tick already have cached coordinates
        resources_to_check = set()
        for transfer in transfers:
            resources_to_check.add(transfer["from"])
            resources_to_check.add(transfer["to"])

        missing_coords = [resource for resource in resources_to_check if self.obj_coords_cache.get(resource, (0, 0)) == (0, 0)]
        if missing_coords:
            self.draw_scene()
            self.update_idletasks()

        effective_duration_ms = max(1, int(duration_ms))

        if effective_duration_ms < target_step_time:
            step_time = max(1, effective_duration_ms)
            frames = 1
        else:
            step_time = target_step_time
            frames = max(2, int(effective_duration_ms / step_time))

        grouped_transfers = {}
        for transfer in transfers:
            origin = transfer["from"]
            destination = transfer["to"]
            key = (origin, destination)
            grouped_transfers[key] = grouped_transfers.get(key, 0) + 1

        animated_objects = []
        for (origin, destination), count in grouped_transfers.items():

            p1 = self.obj_coords_cache.get(origin, (0, 0))
            p2 = self.obj_coords_cache.get(destination, (0, 0))
            if p1 == (0, 0) or p2 == (0, 0):
                continue

            cx, cy = p1
            size_factor = min(2.5, 1.0 + (0.35 * (count - 1)))
            radius = 5 * self.scale * size_factor
            ball = self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="#27AE60", outline="black", width=1)

            text_id = None
            if count > 1:
                text_id = self.canvas.create_text(
                    cx,
                    cy,
                    text=str(count),
                    fill="white",
                    font=("Segoe UI", max(8, int(9 * self.scale)), "bold"),
                )

            animated_objects.append(
                {
                    "id": ball,
                    "text_id": text_id,
                    "count": count,
                    "radius": radius,
                    "x1": p1[0],
                    "y1": p1[1],
                    "x2": p2[0],
                    "y2": p2[1],
                }
            )

        if animated_objects:
            self.animate_frame(animated_objects, frames, 0, step_time, on_complete=on_complete)
        elif on_complete:
            on_complete()

    def animate_frame(self, animated_objects, total_frames, current_frame, step_time, on_complete=None):
        if current_frame >= total_frames:
            for obj in animated_objects:
                self.canvas.delete(obj["id"])
                if obj.get("text_id") is not None:
                    self.canvas.delete(obj["text_id"])
            self.update_idletasks()
            if on_complete:
                on_complete()
            return

        progress = (current_frame + 1) / total_frames

        for obj in animated_objects:
            current_x = obj["x1"] + (obj["x2"] - obj["x1"]) * progress
            current_y = obj["y1"] + (obj["y2"] - obj["y1"]) * progress
            radius = obj["radius"]
            self.canvas.coords(obj["id"], current_x - radius, current_y - radius, current_x + radius, current_y + radius)
            if obj.get("text_id") is not None:
                self.canvas.coords(obj["text_id"], current_x, current_y)

        self.after(step_time, self.animate_frame, animated_objects, total_frames, current_frame + 1, step_time, on_complete)

    def draw_scene(self, initial=False):
        if not initial:
            self.canvas.delete("all")

        self.obj_coords_cache = weakref.WeakKeyDictionary()
        self.resource_draw_order = []
        self.resource_block_bounds = weakref.WeakKeyDictionary()
        self.resource_world_positions = weakref.WeakKeyDictionary()

        previously_active_ids = set(self.active_list_widgets.keys())
        currently_active_ids = set()

        now = 0.0
        if hasattr(self, "sim_ctrl") and self.sim_ctrl.env is not None:
            now = self.sim_ctrl.env.now
        self.update_time_display(now)

        start_x = (50 * self.scale) + self.offset_x
        start_y = (50 * self.scale) + self.offset_y

        margin = 20 * self.scale
        margin_world = 20
        gc.collect()
        resource_list = list(self._tracked_resources())
        resource_list.sort(key=lambda resource: getattr(resource, "visual_name", str(id(resource))))

        total = len(resource_list)
        if total == 0:
            return

        auto_resources = [resource for resource in resource_list if resource not in self.manual_block_positions]
        manual_resources = [resource for resource in resource_list if resource in self.manual_block_positions]

        for resource in auto_resources:
            name = getattr(resource, "visual_name", None)
            if not name:
                continue
            cached_pos = self.manual_layout_by_name.get(name)
            if cached_pos is None:
                continue
            self.manual_block_positions[resource] = (float(cached_pos[0]), float(cached_pos[1]))

        auto_resources = [resource for resource in resource_list if resource not in self.manual_block_positions]
        manual_resources = [resource for resource in resource_list if resource in self.manual_block_positions]

        col_y_offsets = {}
        if len(auto_resources) <= 36:
            mode = "SQUARE"
            grid_dim = math.ceil(math.sqrt(max(1, len(auto_resources))))
        else:
            mode = "RECT"
            fixed_rows = 6

        for i, resource in enumerate(auto_resources):
            if mode == "SQUARE":
                col_logical = i % grid_dim
            else:
                col_logical = i // fixed_rows

            base_h_world = 100
            expanded_h_world = (base_h_world * 2) + 20
            current_height_world = expanded_h_world if getattr(resource, "is_expanded", False) else base_h_world

            col_width_world = 320
            x_world = 50 + (col_logical * col_width_world)

            if col_logical not in col_y_offsets:
                col_y_offsets[col_logical] = 50

            y_world = col_y_offsets[col_logical]

            x = (x_world * self.scale) + self.offset_x
            y = (y_world * self.scale) + self.offset_y

            self.resource_world_positions[resource] = (x_world, y_world)
            self._draw_block_for_resource(resource, x, y, i, resource_list, currently_active_ids, is_manual=False)
            col_y_offsets[col_logical] += current_height_world + margin_world

        for i, resource in enumerate(manual_resources):
            x_world, y_world = self.manual_block_positions.get(resource, (50.0, 50.0))
            x = (x_world * self.scale) + self.offset_x
            y = (y_world * self.scale) + self.offset_y
            self.resource_world_positions[resource] = (x_world, y_world)
            self._draw_block_for_resource(resource, x, y, i, resource_list, currently_active_ids, is_manual=True)

        for resource_id in previously_active_ids:
            if resource_id not in currently_active_ids:
                widget = self.active_list_widgets.get(resource_id)
                if widget:
                    widget.destroy()
                del self.active_list_widgets[resource_id]

    def _draw_block_for_resource(self, resource, x, y, index, current_list, currently_active_ids, is_manual=False):
        base_h = 100 * self.scale
        current_h = base_h
        expanded = getattr(resource, "is_expanded", False)

        if expanded:
            current_h = (base_h * 2) + (20 * self.scale)

        w = 300 * self.scale
        h = current_h

        center_x = x + w / 2
        center_y = y + h / 2
        self.obj_coords_cache[resource] = (center_x, center_y)

        occupied = 0
        capacity = resource.capacity
        color = "#ddd"
        kind = "GENERIC"
        visual_type = getattr(resource, "visual_type", None)
        put_q = 0
        get_q = 0
        has_dual_queue = False
        items = []

        if isinstance(resource, tk.Variable):
            pass
        elif visual_type == "PREEMPTIVE_RESOURCE":
            color = "#85C1E9"
            kind = "PREEMPTIVE_RESOURCE"
            occupied = resource.count
            get_q = len(resource.queue)
        elif visual_type == "PRIORITY_RESOURCE":
            color = "#A9CCE3"
            kind = "PRIORITY_RESOURCE"
            occupied = resource.count
            get_q = len(resource.queue)
        elif resource.__class__.__name__.endswith("Resource"):
            color = "#AED6F1"
            kind = visual_type or "RESOURCE"
            occupied = resource.count
            get_q = len(resource.queue)
        elif resource.__class__.__name__.endswith("Container"):
            color = "#F9E79F"
            kind = visual_type or "CONTAINER"
            occupied = resource.level
            put_q = len(resource.put_queue)
            get_q = len(resource.get_queue)
            has_dual_queue = True
        elif resource.__class__.__name__.endswith("Store"):
            color = "#D2B4DE"
            kind = visual_type or "STORE"
            occupied = len(resource.items)
            put_q = len(resource.put_queue)
            get_q = len(resource.get_queue)
            has_dual_queue = True
            items = resource.items

        outline_color = "black"
        outline_width = 2
        dash_pattern = None if is_manual else (6, 3)
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=color, outline=outline_color, width=outline_width, dash=dash_pattern)
        self.resource_block_bounds[resource] = (x, y, x + w, y + h)
        self.resource_draw_order.append(resource)

        if resource.__class__.__name__.endswith("Store"):
            btn_size = 20 * self.scale
            bx = x + w - btn_size - 5 * self.scale
            by = y + 5 * self.scale
            symbol = "▲" if expanded else "▼"

            btn_tag = f"btn_expand_{id(resource)}"
            self.canvas.create_rectangle(bx, by, bx + btn_size, by + btn_size, fill="white", outline="black", tags=(btn_tag,))
            self.canvas.create_text(bx + btn_size / 2, by + btn_size / 2, text=symbol, font=("Segoe UI", int(10 * self.scale)), tags=(btn_tag,))

        font_title = ("Segoe UI", int(12 * self.scale), "bold")
        font_sub = ("Segoe UI", int(9 * self.scale), "italic")

        name = getattr(resource, "visual_name", "Resource")
        self.canvas.create_text(x + 10 * self.scale, y + 20 * self.scale, text=name, anchor="w", font=font_title)
        self.canvas.create_text(x + 10 * self.scale, y + 40 * self.scale, text=f"{kind}", anchor="w", font=font_sub)

        bar_x = x + 10 * self.scale
        bar_y = y + 60 * self.scale
        bar_w = w - 20 * self.scale
        bar_h = 25 * self.scale

        self.canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, fill="white", outline="black")

        if capacity > 0:
            pct = min(1.0, occupied / capacity)
            fill_w = bar_w * pct
            fill_color = "#27AE60" if pct < 1.0 else "#E67E22"
            self.canvas.create_rectangle(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h, fill=fill_color, outline="")

        font_bar = ("Segoe UI", int(10 * self.scale), "bold")
        self.canvas.create_text(bar_x + bar_w / 2, bar_y + bar_h / 2, text=f"{occupied}/{capacity}", font=font_bar)

        if expanded:
            resource_id = id(resource)
            list_y = y + 100 * self.scale
            list_w = w - 20 * self.scale
            list_h = h - (110 * self.scale)

            if resource_id in self.active_list_widgets:
                frame_container = self.active_list_widgets[resource_id]
                try:
                    listbox = frame_container.winfo_children()[2]
                except IndexError:
                    listbox = None
            else:
                listbox = None
                frame_container = None

            listbox_font = ("Consolas", int(9 * self.scale)) if self.scale > 0.5 else ("Consolas", 8)

            if frame_container is None or listbox is None:
                frame_container = tk.Frame(self.canvas, bg="white", bd=1, relief="solid")
                scrollbar_v = tk.Scrollbar(frame_container, orient=tk.VERTICAL)
                scrollbar_h = tk.Scrollbar(frame_container, orient=tk.HORIZONTAL)

                listbox = tk.Listbox(
                    frame_container,
                    yscrollcommand=scrollbar_v.set,
                    xscrollcommand=scrollbar_h.set,
                    font=listbox_font,
                    bg="#f9f9f9",
                    bd=0,
                    highlightthickness=0,
                )
                scrollbar_v.config(command=listbox.yview)
                scrollbar_h.config(command=listbox.xview)
                scrollbar_v.pack(side=tk.RIGHT, fill=tk.Y)
                scrollbar_h.pack(side=tk.BOTTOM, fill=tk.X)
                listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                self.active_list_widgets[resource_id] = frame_container
            else:
                listbox.config(font=listbox_font)

            current_items_str = [str(item) for item in items] if items else ["(Empty)"]
            displayed_items = listbox.get(0, tk.END)

            if displayed_items != tuple(current_items_str):
                y_scroll_pos = listbox.yview()
                x_scroll_pos = listbox.xview()

                listbox.delete(0, tk.END)
                for item in current_items_str:
                    listbox.insert(tk.END, item)

                if not items:
                    listbox.config(fg="#888")
                else:
                    listbox.config(fg="black")

                try:
                    listbox.yview_moveto(y_scroll_pos[0])
                    listbox.xview_moveto(x_scroll_pos[0])
                except Exception:
                    pass

            self.canvas.create_window(
                x + 10 * self.scale,
                list_y,
                width=list_w,
                height=list_h,
                anchor="nw",
                window=frame_container,
                tags=("window_widget",),
            )

            currently_active_ids.add(resource_id)

        badge_half_height = 12 * self.scale
        badge_min_half_width = 20 * self.scale
        badge_char_half_width = 3.6 * self.scale
        badge_font = ("Segoe UI", int(9 * self.scale), "bold")
        label_font = ("Segoe UI", int(7 * self.scale))
        is_store_resource = resource.__class__.__name__.endswith("Store")
        right_badge_offset = 55 * self.scale if is_store_resource else 30 * self.scale
        left_badge_offset = 95 * self.scale if is_store_resource else 70 * self.scale

        def draw_queue_badge(cx, cy, count_value, fill_color, label_text):
            count_text = self._format_queue_badge_count(count_value)
            badge_half_width = max(badge_min_half_width, (len(count_text) * badge_char_half_width) + (7 * self.scale))
            outline_width = 1 if self.scale < 0.95 else 2
            self.canvas.create_rectangle(
                cx - badge_half_width,
                cy - badge_half_height,
                cx + badge_half_width,
                cy + badge_half_height,
                fill=fill_color,
                outline="white",
                width=outline_width,
            )
            self.canvas.create_text(cx, cy, text=count_text, fill="white", font=badge_font)
            self.canvas.create_text(cx, cy + badge_half_height + 7 * self.scale, text=label_text, font=label_font)

        if has_dual_queue:
            if put_q > 0:
                cx, cy = x + w - right_badge_offset, y + 20 * self.scale
                draw_queue_badge(cx, cy, put_q, "#E67E22", "PUT")
            if get_q > 0:
                cx, cy = x + w - left_badge_offset, y + 20 * self.scale
                draw_queue_badge(cx, cy, get_q, "#C0392B", "GET")
        else:
            if get_q > 0:
                cx, cy = x + w - right_badge_offset, y + 20 * self.scale
                draw_queue_badge(cx, cy, get_q, "#E67E22", "Q")
