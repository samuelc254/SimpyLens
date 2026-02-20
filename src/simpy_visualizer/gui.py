from .monkey_patch import tracked_resources, pending_transfers, apply_patch
from .sim_manager import SimulationController
import time
import tkinter as tk
from tkinter import ttk, messagebox
import math


class SimPyVisualizer(tk.Tk):
    def __init__(self, setup_func=None, title="SimPy Visualizer"):
        """
        Initializes the SimPy Visualizer.

        :param setup_func: A function that takes a simpy.Environment as its only argument
                           and sets up the simulation (creates resources, processes, etc).
        :param title: Window title.
        """
        apply_patch()
        super().__init__()
        self.title(title)
        self.geometry("1000x800")

        self.env = None
        self.running = False
        self.target_time = float("inf")
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        self.current_setup_func = setup_func

        self.obj_coords_cache = {}
        self.active_animations = []
        self.active_list_widgets = {}

        self.last_tick_time = time.time()
        self.tick_count = 0
        self.last_fps_update = 0

        self.log_enabled = tk.BooleanVar(value=True)
        self.log_collapsed = False
        self.log_widget = None
        self.max_log_lines = 2000

        self._setup_top_bar()
        self._setup_log_panel()
        self._setup_canvas()

        self.sim_ctrl = SimulationController(
            draw_callback=lambda initial=False: (self.draw_scene(initial), self.update_idletasks()),
            start_animations_cb=self.start_animations,
            update_time_cb=self.update_time_display,
            schedule_cb=lambda ms, fn: self.after(ms, fn),
            speed_getter=lambda: self.scl_speed.get(),
            on_pause_cb=lambda: self.ent_target.config(state="normal"),
            log_callback=self.log_message,
        )

        if self.current_setup_func:
            try:
                self.sim_ctrl.reset(self.current_setup_func)
            except Exception as exc:
                messagebox.showerror("Simulation Error", f"Error in setup():\n{exc}")

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
            command=lambda: (
                self.sim_ctrl.set_setup_func(self.current_setup_func),
                self.sim_ctrl.run_single_step(),
            ),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            btn_frame,
            text="⏸ Pause",
            command=lambda: (
                self.sim_ctrl.pause(),
                self.ent_target.config(state="normal"),
            ),
        ).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            btn_frame,
            text="⏹ Reset",
            command=lambda: (
                self.sim_ctrl.reset(self.current_setup_func),
                self.ent_target.config(state="normal"),
                self.after(100, self.center_view),
            ),
        ).pack(side=tk.LEFT, padx=2)

        self.lbl_time = ttk.Label(bar, text="Time: 0.00", font=("Consolas", 14, "bold"))
        self.lbl_time.pack(side=tk.LEFT, padx=20)

        spd_frame = ttk.Frame(bar)
        spd_frame.pack(side=tk.LEFT, padx=20)
        ttk.Label(spd_frame, text="Speed:").pack(side=tk.LEFT)
        self.scl_speed = tk.Scale(spd_frame, from_=0, to=100, orient=tk.HORIZONTAL, showvalue=0, length=150)
        self.scl_speed.set(50)
        self.scl_speed.pack(side=tk.LEFT)

        self.lbl_speed_val = ttk.Label(spd_frame, text="0.0 tps", width=12)
        self.lbl_speed_val.pack(side=tk.LEFT, padx=(5, 0))

        right_frame = ttk.Frame(bar)
        right_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(right_frame, text="Break Point:").pack(side=tk.LEFT, padx=(5, 5))
        self.ent_target = ttk.Entry(right_frame, width=10)
        self.ent_target.insert(0, "")
        self.ent_target.pack(side=tk.LEFT)

    def on_play_click(self):
        try:
            value = self.ent_target.get().strip()
            self.sim_ctrl.target_time = float(value) if value else float("inf")
            self.ent_target.config(state="disabled")
            self.sim_ctrl.set_setup_func(self.current_setup_func)
            self.sim_ctrl.run()
        except ValueError:
            messagebox.showerror("Invalid Input", "Break Point must be a valid number.")
            self.ent_target.config(state="normal")

    def update_time_display(self, now):
        """Updates time label and calculates ticks/s in the interface."""
        self.lbl_time.config(text=f"Time: {now:.2f}")

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

        header_frame = ttk.Frame(self.bottom_panel)
        header_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)

        self.btn_toggle_log = ttk.Button(header_frame, text="▼ Logs", width=8, command=self.toggle_log_panel)
        self.btn_toggle_log.pack(side=tk.LEFT)

        ttk.Checkbutton(header_frame, text="Enable Logging", variable=self.log_enabled).pack(side=tk.LEFT, padx=10)
        ttk.Button(header_frame, text="Clear", command=self.clear_log).pack(side=tk.LEFT, padx=5)

        self.log_content_frame = ttk.Frame(self.bottom_panel)
        self.log_content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

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

        scrollbar.config(command=self.txt_log.yview)

    def toggle_log_panel(self):
        if self.log_collapsed:
            self.log_content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            self.btn_toggle_log.config(text="▼ Logs")
            self.log_collapsed = False
        else:
            self.log_content_frame.pack_forget()
            self.btn_toggle_log.config(text="▲ Logs")
            self.log_collapsed = True

    def clear_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", tk.END)
        self.txt_log.config(state="disabled")

    def log_message(self, messages):
        """Receives a list of log strings and displays them."""
        if not self.log_enabled.get():
            return

        self.txt_log.config(state="normal")
        for msg in messages:
            self.txt_log.insert(tk.END, msg + "\n")

        total_lines = int(self.txt_log.index("end-1c").split(".")[0])
        if total_lines > self.max_log_lines:
            lines_to_trim = total_lines - self.max_log_lines
            self.txt_log.delete("1.0", f"{lines_to_trim + 1}.0")

        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def _setup_canvas(self):
        self.canvas_frame = tk.Frame(self)
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

        self.canvas.bind("<ButtonPress-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.do_pan)
        self.canvas.bind("<ButtonRelease-1>", self.stop_pan)
        self.canvas.bind("<MouseWheel>", self.do_zoom)
        self.canvas.bind("<Button-4>", self.do_zoom)
        self.canvas.bind("<Button-5>", self.do_zoom)

    def on_canvas_click(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        clicked_items = self.canvas.find_overlapping(cx, cy, cx + 1, cy + 1)

        for item in clicked_items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("btn_expand_"):
                    try:
                        object_id = int(tag.split("_")[-1])
                        target_resource = None
                        for resource in tracked_resources:
                            if id(resource) == object_id:
                                target_resource = resource
                                break

                        if target_resource:
                            current_state = getattr(target_resource, "is_expanded", False)
                            target_resource.is_expanded = not current_state
                            self.draw_scene()
                    except (ValueError, IndexError):
                        pass
                    return

        self.start_pan(event)

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
        self.canvas.delete("all")
        self.scale = 1.0
        self.draw_scene(initial=True)
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

        self.scale = desired_scale
        self.offset_x = 0
        self.offset_y = 0
        self.canvas.delete("all")
        self.draw_scene(initial=True)

        self.update_idletasks()
        bbox_new = self.canvas.bbox("all")
        if bbox_new:
            new_w = bbox_new[2] - bbox_new[0]
            new_h = bbox_new[3] - bbox_new[1]

            center_x = self.canvas.winfo_width() / 2
            center_y = self.canvas.winfo_height() / 2

            content_center_x = bbox_new[0] + new_w / 2
            content_center_y = bbox_new[1] + new_h / 2

            dx = center_x - content_center_x
            dy = center_y - content_center_y
            self.canvas.move("all", dx, dy)
            self.offset_x = dx
            self.offset_y = dy

        if pending_transfers:
            pending_transfers.clear()

        self.active_animations = []
        self.obj_coords_cache = {}

    def start_animations(self, transfers, duration_ms):
        """Starts a smooth animation of moving balls between resources."""
        target_step_time = 33

        if duration_ms < target_step_time:
            step_time = max(1, duration_ms)
            frames = 1
        else:
            step_time = target_step_time
            frames = int(duration_ms / step_time)

        animated_objects = []
        for transfer in transfers:
            origin = transfer["from"]
            destination = transfer["to"]

            p1 = self.obj_coords_cache.get(origin, (0, 0))
            p2 = self.obj_coords_cache.get(destination, (0, 0))
            if p1 == (0, 0) or p2 == (0, 0):
                continue

            cx, cy = p1
            radius = 5 * self.scale
            ball = self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="#E74C3C", outline="black", width=1)
            animated_objects.append({"id": ball, "x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1]})

        if animated_objects:
            self.animate_frame(animated_objects, frames, 0, step_time)

    def animate_frame(self, animated_objects, total_frames, current_frame, step_time):
        if current_frame >= total_frames:
            for obj in animated_objects:
                self.canvas.delete(obj["id"])
            return

        progress = (current_frame + 1) / total_frames
        radius = 5 * self.scale

        for obj in animated_objects:
            current_x = obj["x1"] + (obj["x2"] - obj["x1"]) * progress
            current_y = obj["y1"] + (obj["y2"] - obj["y1"]) * progress
            self.canvas.coords(obj["id"], current_x - radius, current_y - radius, current_x + radius, current_y + radius)

        self.after(step_time, self.animate_frame, animated_objects, total_frames, current_frame + 1, step_time)

    def draw_scene(self, initial=False):
        if not initial:
            self.canvas.delete("all")

        previously_active_ids = set(self.active_list_widgets.keys())
        currently_active_ids = set()

        now = 0.0
        if hasattr(self, "sim_ctrl") and self.sim_ctrl.env is not None:
            now = self.sim_ctrl.env.now
        self.lbl_time.config(text=f"Time: {now:.2f}")

        start_x = (50 * self.scale) + self.offset_x
        start_y = (50 * self.scale) + self.offset_y

        margin = 20 * self.scale
        resource_list = list(tracked_resources)
        resource_list.sort(key=lambda resource: getattr(resource, "visual_name", str(id(resource))))

        total = len(resource_list)
        if total == 0:
            return

        col_y_offsets = {}
        if total <= 36:
            mode = "SQUARE"
            grid_dim = math.ceil(math.sqrt(total)) or 1
        else:
            mode = "RECT"
            fixed_rows = 6

        for i, resource in enumerate(resource_list):
            if mode == "SQUARE":
                col_logical = i % grid_dim
            else:
                col_logical = i // fixed_rows

            base_h_scaled = 100 * self.scale
            current_height = base_h_scaled
            if getattr(resource, "is_expanded", False):
                current_height = (base_h_scaled * 2) + margin

            col_width = (300 * self.scale) + margin
            x = start_x + (col_logical * col_width)

            if col_logical not in col_y_offsets:
                col_y_offsets[col_logical] = start_y

            y = col_y_offsets[col_logical]

            self._draw_block_for_resource(resource, x, y, i, resource_list, currently_active_ids)
            col_y_offsets[col_logical] += current_height + margin

        for resource_id in previously_active_ids:
            if resource_id not in currently_active_ids:
                widget = self.active_list_widgets.get(resource_id)
                if widget:
                    widget.destroy()
                del self.active_list_widgets[resource_id]

    def _draw_block_for_resource(self, resource, x, y, index, current_list, currently_active_ids):
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
        put_q = 0
        get_q = 0
        has_dual_queue = False
        items = []

        if isinstance(resource, tk.Variable):
            pass
        elif resource.__class__.__name__.endswith("Resource"):
            color = "#AED6F1"
            kind = "RESOURCE"
            occupied = resource.count
            get_q = len(resource.queue)
        elif resource.__class__.__name__.endswith("Container"):
            color = "#F9E79F"
            kind = "CONTAINER"
            occupied = resource.level
            put_q = len(resource.put_queue)
            get_q = len(resource.get_queue)
            has_dual_queue = True
        elif resource.__class__.__name__.endswith("Store"):
            color = "#D2B4DE"
            kind = "STORE"
            occupied = len(resource.items)
            put_q = len(resource.put_queue)
            get_q = len(resource.get_queue)
            has_dual_queue = True
            items = resource.items

        self.canvas.create_rectangle(x, y, x + w, y + h, fill=color, outline="black", width=2)

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
        self.canvas.create_text(x + 10 * self.scale, y + 40 * self.scale, text=f"{kind} (Cap: {capacity})", anchor="w", font=font_sub)

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

        radius = 15 * self.scale
        badge_font = ("Segoe UI", int(10 * self.scale), "bold")
        label_font = ("Segoe UI", int(7 * self.scale))

        if has_dual_queue:
            if put_q > 0:
                cx, cy = x + w - 30 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="#E67E22", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(put_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + radius + 7 * self.scale, text="PUT", font=label_font)
            if get_q > 0:
                cx, cy = x + w - 70 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="#C0392B", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + radius + 7 * self.scale, text="GET", font=label_font)
        else:
            if get_q > 0:
                cx, cy = x + w - 30 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, fill="#E67E22", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + radius + 7 * self.scale, text="Q", font=label_font)
