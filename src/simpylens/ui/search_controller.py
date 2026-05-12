import tkinter as tk


class TextSearchController:
    """Reusable search/highlight controller for tk.Text widgets."""

    def __init__(self, text_widget, match_tag, current_tag, on_counter_change=None):
        self.text_widget = text_widget
        self.match_tag = match_tag
        self.current_tag = current_tag
        self.on_counter_change = on_counter_change
        self.matches = []
        self.index = -1
        self.current_query = ""

    def _set_editable(self):
        was_disabled = str(self.text_widget.cget("state")) == "disabled"
        if was_disabled:
            self.text_widget.config(state="normal")
        return was_disabled

    def _restore_state(self, was_disabled):
        if was_disabled:
            self.text_widget.config(state="disabled")

    def _notify(self):
        if self.on_counter_change is not None:
            self.on_counter_change(self)

    def clear(self):
        was_disabled = self._set_editable()
        self.text_widget.tag_remove(self.match_tag, "1.0", tk.END)
        self.text_widget.tag_remove(self.current_tag, "1.0", tk.END)
        self._restore_state(was_disabled)
        self.matches = []
        self.index = -1
        self.current_query = ""
        self._notify()

    def refresh(self, query, reset_index=False):
        query = str(query or "").strip()
        self.current_query = query

        was_disabled = self._set_editable()
        self.text_widget.tag_remove(self.match_tag, "1.0", tk.END)
        self.text_widget.tag_remove(self.current_tag, "1.0", tk.END)
        self.matches = []

        if not query:
            self.index = -1
            self._restore_state(was_disabled)
            self._notify()
            return

        start = "1.0"
        query_len = len(query)
        while True:
            pos = self.text_widget.search(query, start, tk.END, nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{query_len}c"
            self.text_widget.tag_add(self.match_tag, pos, end_pos)
            self.matches.append((pos, end_pos))
            start = end_pos

        if not self.matches:
            self.index = -1
            self._restore_state(was_disabled)
            self._notify()
            return

        if reset_index or self.index < 0 or self.index >= len(self.matches):
            self.index = 0

        self._highlight_current_inner()
        self._restore_state(was_disabled)

    def _highlight_current_inner(self):
        self.text_widget.tag_remove(self.current_tag, "1.0", tk.END)
        if not self.matches or self.index < 0:
            self._notify()
            return

        start, end = self.matches[self.index]
        self.text_widget.tag_add(self.current_tag, start, end)
        self.text_widget.see(start)
        self._notify()

    def find_next(self, query):
        self.refresh(query, reset_index=False)
        if not self.matches:
            return

        was_disabled = self._set_editable()
        self.index = (self.index + 1) % len(self.matches)
        self._highlight_current_inner()
        self._restore_state(was_disabled)

    def find_prev(self, query):
        self.refresh(query, reset_index=False)
        if not self.matches:
            return

        was_disabled = self._set_editable()
        self.index = (self.index - 1) % len(self.matches)
        self._highlight_current_inner()
        self._restore_state(was_disabled)
