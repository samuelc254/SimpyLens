import math
import tkinter as tk
import weakref
import gc


class CanvasView(tk.Frame):
    """Canvas area with block drawing, zoom/pan, drag, and animations."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.pack(fill=tk.BOTH, expand=True)
        self.app = app

        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.active_list_widgets = {}
        self.manual_block_positions = weakref.WeakKeyDictionary()
        self._reset_scene_caches()
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
        self.right_press_moved = False

        self._build_widgets()

    def _reset_scene_caches(self):
        self.obj_coords_cache = weakref.WeakKeyDictionary()
        self.resource_world_positions = weakref.WeakKeyDictionary()
        self.resource_block_bounds = weakref.WeakKeyDictionary()
        self.resource_draw_order = []

    def _build_widgets(self):
        self.canvas = tk.Canvas(self, bg="#f0f0f0")
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

    def _toggle_expand_at_point(self, cx, cy):
        clicked_items = self.canvas.find_overlapping(cx, cy, cx + 1, cy + 1)

        for item in clicked_items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("btn_expand_"):
                    try:
                        object_id = int(tag.split("_")[-1])
                        target_resource = None
                        for resource in self.app.get_tracked_resources():
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

        resource_list = list(self.app.get_tracked_resources())
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
            self.app.save_manual_layout_cache()
        self.dragged_resource = None

    def on_right_press(self, event):
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        resource = self._resource_at_canvas_point(cx, cy)
        self.right_press_resource = resource
        self.right_press_canvas_x = cx
        self.right_press_canvas_y = cy
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
            self.block_context_menu.add_command(label="Details", command=self._open_details_for_context_resource)
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
        if name and name in self.app.manual_layout_by_name:
            del self.app.manual_layout_by_name[name]
        self.app.save_manual_layout_cache()
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
        pending_transfers = self.app.get_pending_transfers()
        if pending_transfers:
            pending_transfers.clear()
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

        self._reset_scene_caches()

        previously_active_ids = set(self.active_list_widgets.keys())
        currently_active_ids = set()

        now = self.app.get_sim_time()
        self.app.update_time_display(now)

        gc.collect()
        resource_list = list(self.app.get_tracked_resources())
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
            cached_pos = self.app.manual_layout_by_name.get(name)
            if cached_pos is None:
                continue
            self.manual_block_positions[resource] = (float(cached_pos[0]), float(cached_pos[1]))

        auto_resources = [resource for resource in resource_list if resource not in self.manual_block_positions]
        manual_resources = [resource for resource in resource_list if resource in self.manual_block_positions]

        auto_positions = self._compute_auto_layout_world_positions(auto_resources)

        for i, resource in enumerate(auto_resources):
            x_world, y_world = auto_positions.get(resource, (50.0, 50.0))

            x = (x_world * self.scale) + self.offset_x
            y = (y_world * self.scale) + self.offset_y

            self.resource_world_positions[resource] = (x_world, y_world)
            self._draw_block_for_resource(resource, x, y, i, currently_active_ids, is_manual=False)

        for i, resource in enumerate(manual_resources):
            x_world, y_world = self.manual_block_positions.get(resource, (50.0, 50.0))
            x = (x_world * self.scale) + self.offset_x
            y = (y_world * self.scale) + self.offset_y
            self.resource_world_positions[resource] = (x_world, y_world)
            self._draw_block_for_resource(resource, x, y, i, currently_active_ids, is_manual=True)

        for resource_id in previously_active_ids:
            if resource_id not in currently_active_ids:
                widget = self.active_list_widgets.get(resource_id)
                if widget:
                    widget.destroy()
                del self.active_list_widgets[resource_id]

    def _draw_block_for_resource(self, resource, x, y, index, currently_active_ids, is_manual=False):
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

    def _open_details_for_context_resource(self):
        """Open details window for the resource under the context menu."""
        resource = self.context_menu_resource
        self.context_menu_resource = None
        if resource is not None:
            self.app.open_resource_details(resource)
