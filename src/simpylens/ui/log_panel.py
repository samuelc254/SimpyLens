import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from .search_controller import TextSearchController


class LogPanel(ttk.Frame):
    """Bottom log panel with search, resize, and source-location links."""

    def __init__(self, parent, app):
        super().__init__(parent, relief="raised", borderwidth=1)
        self.pack(side=tk.BOTTOM, fill=tk.X)
        self.app = app

        self.log_enabled = tk.BooleanVar(value=True)
        self.log_collapsed = False
        self.max_log_lines = 2000
        self.log_search_var = tk.StringVar(value="")
        self.log_resize_start_y = None
        self.log_resize_start_height = 0
        self.log_content_min_height = 100
        self.log_content_max_height = 600
        self.log_link_targets = {}
        self._next_log_link_id = 1

        self._build_widgets()

    def _build_widgets(self):
        """Sets up the log panel at the bottom."""
        self.log_resize_handle = tk.Frame(self, height=5, bg="#d0d0d0", cursor="sb_v_double_arrow")
        self.log_resize_handle.pack(side=tk.TOP, fill=tk.X)
        self.log_resize_handle.bind("<ButtonPress-1>", self._start_log_resize)
        self.log_resize_handle.bind("<B1-Motion>", self._do_log_resize)
        self.log_resize_handle.bind("<ButtonRelease-1>", self._stop_log_resize)

        header_frame = ttk.Frame(self)
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

        self.log_content_frame = ttk.Frame(self, height=180)
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
        self.txt_log.bind("<Configure>", self._update_log_tabs)
        self.txt_log.tag_configure("log_find_match", background="#FFF59D")
        self.txt_log.tag_configure("log_find_current", background="#FBC02D")
        self.txt_log.tag_configure("log_link_base", foreground="#0b57d0", underline=True)
        self.log_search = TextSearchController(
            self.txt_log,
            "log_find_match",
            "log_find_current",
            on_counter_change=lambda _controller: self._update_log_find_counter(),
        )

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

    def _update_log_tabs(self, event):
        widget_width = int(getattr(event, "width", 0)) - 25
        if widget_width <= 0:
            return

        # Tk expects tabs as a Tcl list (distance, alignment, ...).
        # Passing a single string like "956 right" is parsed as one token and fails.
        try:
            self.txt_log.config(tabs=(widget_width, "right"))
        except tk.TclError:
            # Ignore transient configure errors during rapid resize/destroy.
            pass

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
        for tag_name in list(self.log_link_targets.keys()):
            self.txt_log.tag_delete(tag_name)
        self.log_link_targets = {}
        self.txt_log.config(state="disabled")
        self.log_search.clear()
        self._update_log_find_counter()

    def _create_log_location_link(self, insert_at, rendered_line, location_token, file_path, line_number):
        if not location_token or not file_path:
            return

        stop_index = f"{insert_at}+{len(rendered_line)}c"
        tabbed_token = f"\t{location_token}"
        start = self.txt_log.search(tabbed_token, insert_at, stopindex=stop_index, exact=True)
        token_len = len(tabbed_token)
        if not start:
            start = self.txt_log.search(location_token, insert_at, stopindex=stop_index, exact=True)
            token_len = len(location_token)
        if not start:
            return

        end = f"{start}+{token_len}c"
        tag_name = f"log_link_{self._next_log_link_id}"
        self._next_log_link_id += 1

        self.log_link_targets[tag_name] = (str(file_path), int(line_number))
        self.txt_log.tag_add(tag_name, start, end)
        self.txt_log.tag_add("log_link_base", start, end)
        self.txt_log.tag_bind(tag_name, "<Enter>", lambda _event: self.txt_log.config(cursor="hand2"))
        self.txt_log.tag_bind(tag_name, "<Leave>", lambda _event: self.txt_log.config(cursor="xterm"))
        self.txt_log.tag_bind(tag_name, "<Button-1>", lambda _event, bound_tag=tag_name: self._open_log_link(bound_tag))

    def _open_log_link(self, tag_name):
        location = self.log_link_targets.get(tag_name)
        if not location:
            return
        file_path, line_number = location
        self.app.editor_manager.open_location(file_path, line_number)

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
        self.update_idletasks()

    def _stop_log_resize(self, _event=None):
        self.log_resize_start_y = None
        self.log_resize_start_height = 0

    def _update_log_find_counter(self):
        query = self.log_search_var.get().strip()
        if not query or self.log_collapsed:
            self.log_find_popup.place_forget()
            return

        total = len(self.log_search.matches)
        if total == 0 or self.log_search.index < 0:
            self.log_find_popup.config(text="0/0")
            self.log_find_popup.place(relx=1.0, x=-26, rely=1.0, y=-8, anchor="se")
            return
        self.log_find_popup.config(text=f"{self.log_search.index + 1}/{total}")
        self.log_find_popup.place(relx=1.0, x=-26, rely=1.0, y=-8, anchor="se")

    def _on_log_find_changed(self, _event=None):
        self._refresh_log_search_highlights(reset_index=True)

    def _refresh_log_search_highlights(self, reset_index=False):
        self.log_search.refresh(self.log_search_var.get().strip(), reset_index=reset_index)

    def find_next_log(self, _event=None):
        self.log_search.find_next(self.log_search_var.get().strip())

    def find_prev_log(self, _event=None):
        self.log_search.find_prev(self.log_search_var.get().strip())

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

        def _location_text():
            file_value = data.get("file")
            line_value = data.get("line")
            if file_value:
                try:
                    file_name = Path(str(file_value)).name
                except Exception:
                    file_name = str(file_value)
                if line_value is not None:
                    return f"{file_name}:{line_value}"
                return file_name
            if line_value is not None:
                return str(line_value)
            return ""

        def _append_location(base_text):
            location_text = _location_text()
            if not location_text:
                return base_text
            return f"{base_text} | {location_text}"

        # --- SIM ---
        if kind == "SIM":
            return f"[{timestamp:.2f}] [SIM] {message}"

        # --- STEP ---
        if kind == "STEP":
            if event == "START":
                step = data.get("step", "?")
                return _append_location(f"[{timestamp:.2f}] [STEP {step} \u25b6] {message}")

            if event == "ACTION":
                step = data.get("step", "?")
                extras = []
                if "amount" in data:
                    extras.append(f"amount={data['amount']}")
                if "item" in data:
                    extras.append(f"item={_trunc(data['item'], 40)}")
                if "filter" in data:
                    extras.append(f"filter={_trunc(data['filter'], 40)}")
                suffix = " | " + " | ".join(extras) if extras else ""
                return _append_location(f"[{timestamp:.2f}] [STEP {step} \u21b3] {message}{suffix}")

            if event == "END":
                step = data.get("step", "?")
                return _append_location(f"[{timestamp:.2f}] [STEP {step} \u2714] {message}")

            return f"[{timestamp:.2f}] [STEP] {message}"

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
            location_token = None
            location_file = None
            location_line = None
            if isinstance(msg, str):
                stripped = msg.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    try:
                        payload = json.loads(stripped)
                        line = self._format_json_log(payload)
                        if isinstance(payload, dict):
                            payload_data = payload.get("data") or {}
                            file_value = payload_data.get("file")
                            line_value = payload_data.get("line")
                            if file_value and line_value is not None:
                                try:
                                    location_line = int(line_value)
                                except (TypeError, ValueError):
                                    location_line = None
                                if location_line is not None:
                                    location_file = str(file_value)
                                    location_token = f"{Path(location_file).name}:{location_line}"
                    except json.JSONDecodeError:
                        line = msg

            rendered_line = str(line)
            insert_at = self.txt_log.index("end-1c")
            self.txt_log.insert(tk.END, rendered_line + "\n")

            if location_token and location_file and location_line is not None:
                self._create_log_location_link(insert_at, rendered_line, location_token, location_file, location_line)

        total_lines = int(self.txt_log.index("end-1c").split(".")[0])
        if total_lines > self.max_log_lines:
            lines_to_trim = total_lines - self.max_log_lines
            self.txt_log.delete("1.0", f"{lines_to_trim + 1}.0")

        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")
        if self.log_search_var.get().strip():
            self._refresh_log_search_highlights(reset_index=False)
