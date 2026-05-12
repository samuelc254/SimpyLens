from ..sim_manager import SimulationController
from .editor_manager import EditorManager
from .log_panel import LogPanel
from .inspector_panel import InspectorPanel
from .canvas_view import CanvasView
from .details_window import DetailsWindowManager
import json
import time
import traceback
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path


class MainWindow(tk.Tk):
    def __init__(self, model=None, title="SimPyLens", seed=None, lens_json_path=None):
        """
        Initializes SimPyLens.

        :param model: A function that takes a simpy.Environment as its only argument
                      and sets up the simulation (creates resources, processes, etc).
        :param title: Window title.
        :param seed: Optional random seed for reproducible simulations.
        :param lens_json_path: Optional explicit path to the layout JSON file.
            When provided, this path is used instead of the auto-inferred default
            (``.<model_file>.lens.json`` next to the model's source file).
            Useful for versioning multiple layouts for the same model.
        """
        super().__init__()
        self._app_icon_image = None
        self._set_app_icon()
        self.title(title)
        self.geometry("1000x800")

        self.env = None
        self.running = False
        self.current_model = model

        self.manual_layout_by_name = {}
        self.last_breakpoint_hit = None
        self.layout_config_path = self._resolve_layout_config_path(lens_json_path)
        self._load_manual_layout_cache()
        self.editor_manager = EditorManager(self)

        # TPS must reflect real simulation progress (step delta / wall-clock delta),
        # not UI redraw frequency.
        self.last_fps_update = time.time()
        self.last_step_for_tps = 0
        self.tps_update_interval = 0.5

        self._setup_top_bar()
        self.main_area = ttk.Frame(self)
        self.main_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.main_content = ttk.Frame(self.main_area)
        self.main_content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_panel = LogPanel(self, self)
        self.canvas_view = CanvasView(self.main_content, self)

        self.sim_ctrl = SimulationController(
            draw_callback=lambda initial=False: (self.canvas_view.draw_scene(initial), self.update_idletasks()),
            start_animations_cb=self.canvas_view.start_animations,
            update_time_cb=self.update_time_display,
            schedule_cb=lambda ms, fn: self.after(ms, fn),
            speed_getter=lambda: self.scl_speed.get(),
            log_callback=self.log_panel.log_message,
            on_breakpoint_cb=self._on_breakpoint_hit,
            seed=seed,
        )

        self.details_manager = DetailsWindowManager(self)
        self.inspector_panel = InspectorPanel(self.main_area, self)

        if self.current_model:
            try:
                self.sim_ctrl.reset(self.current_model)
                self.after(100, self.canvas_view.center_view)
            except Exception as exc:
                traceback.print_exc()
                messagebox.showerror("Simulation Error", f"Error in setup():\n{exc}")

    def _tracked_resources(self):
        return self.get_tracked_resources()

    def get_tracked_resources(self):
        env = self.sim_ctrl.env if hasattr(self, "sim_ctrl") and self.sim_ctrl else None
        if env is None:
            return ()
        return getattr(env, "tracked_resources", ())

    def _pending_transfers(self):
        return self.get_pending_transfers()

    def get_pending_transfers(self):
        env = self.sim_ctrl.env if hasattr(self, "sim_ctrl") and self.sim_ctrl else None
        if env is None:
            return []
        return getattr(env, "pending_transfers", [])

    def get_environment(self):
        return self.sim_ctrl.env if hasattr(self, "sim_ctrl") and self.sim_ctrl else None

    def get_sim_time(self):
        env = self.get_environment()
        return float(getattr(env, "now", 0.0)) if env is not None else 0.0

    def _set_app_icon(self):
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
        if not icon_path.exists():
            return
        try:
            self._app_icon_image = tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, self._app_icon_image)
        except Exception:
            self._app_icon_image = None

    def _resolve_layout_config_path(self, lens_json_path=None):
        if lens_json_path is not None:
            return Path(lens_json_path).resolve()

        setup_path = None
        if self.current_model and hasattr(self.current_model, "__code__"):
            setup_path = Path(self.current_model.__code__.co_filename).resolve()

        if setup_path is not None:
            return setup_path.parent / f".{setup_path.stem}.lens.json"

        return Path.cwd() / ".lens.json"

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
        self.save_manual_layout_cache()

    def save_manual_layout_cache(self):
        positions = {name: [float(coords[0]), float(coords[1])] for name, coords in self.manual_layout_by_name.items() if coords and len(coords) == 2}
        for resource in list(self.get_tracked_resources()):
            if resource not in self.canvas_view.manual_block_positions:
                continue
            coords = self.canvas_view.manual_block_positions.get(resource)
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

    def open_resource_details(self, resource):
        if resource is None:
            return
        self.details_manager.open_details(resource)

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
        self.inspector_panel.clear_hit_state()
        self.sim_ctrl.set_model(self.current_model)
        self.sim_ctrl.run()

    def on_step_click(self):
        self.inspector_panel.clear_hit_state()
        self.sim_ctrl.set_model(self.current_model)
        self.sim_ctrl.run_single_step()

    def on_reset_click(self):
        self.inspector_panel.clear_hit_state()
        self.sim_ctrl.reset(self.current_model)
        self.after(100, self.canvas_view.center_view)

    def _on_breakpoint_hit(self, event):
        self.last_breakpoint_hit = dict(event)
        self.inspector_panel.on_breakpoint_hit(event)

    def add_breakpoint(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        breakpoint_id = self.sim_ctrl.add_breakpoint(
            condition=condition,
            label=label,
            enabled=enabled,
            pause_on_hit=pause_on_hit,
            edge=edge,
        )
        self.inspector_panel.on_breakpoint_added()
        return breakpoint_id

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

        # If the simulation was reset (or step counter restarted), realign baseline.
        if step < self.last_step_for_tps:
            self.last_step_for_tps = step
            self.last_fps_update = current_time
            self.lbl_speed_val.config(text="0.0 tps")
            return

        elapsed = current_time - self.last_fps_update
        if elapsed >= self.tps_update_interval and elapsed > 0:
            step_delta = max(0, step - self.last_step_for_tps)
            tps = step_delta / elapsed
            self.lbl_speed_val.config(text=f"{tps:.1f} tps")
            self.last_step_for_tps = step
            self.last_fps_update = current_time
