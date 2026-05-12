from simpylens.ui.search_controller import TextSearchController


class FakeTextWidget:
    def __init__(self, text=""):
        self.text = text
        self.state = "normal"
        self.tags = {}
        self.last_seen = None

    def cget(self, key):
        if key == "state":
            return self.state
        raise KeyError(key)

    def config(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]

    def _to_offset(self, index):
        if index == "end":
            return len(self.text)
        if index == "1.0":
            return 0
        if "+" in index:
            base, delta = index.split("+", 1)
            if not delta.endswith("c"):
                raise ValueError(index)
            return self._to_offset(base) + int(delta[:-1])

        line_str, col_str = index.split(".", 1)
        line = int(line_str)
        col = int(col_str)

        lines = self.text.splitlines(keepends=True)
        if not lines:
            lines = [""]

        prefix = sum(len(lines[i]) for i in range(max(0, line - 1)))
        return min(len(self.text), prefix + col)

    def _from_offset(self, offset):
        offset = max(0, min(len(self.text), offset))
        lines = self.text.splitlines(keepends=True)
        if not lines:
            return "1.0"

        walked = 0
        for idx, line in enumerate(lines, start=1):
            next_walked = walked + len(line)
            if offset <= next_walked:
                return f"{idx}.{offset - walked}"
            walked = next_walked
        return f"{len(lines)}.{len(lines[-1])}"

    def search(self, query, start, stopindex=None, nocase=False):
        start_offset = self._to_offset(start)
        haystack = self.text
        needle = query
        if nocase:
            haystack = haystack.lower()
            needle = needle.lower()
        pos = haystack.find(needle, start_offset)
        if pos < 0:
            return ""
        return self._from_offset(pos)

    def tag_remove(self, tag_name, _start, _end):
        self.tags[tag_name] = []

    def tag_add(self, tag_name, start, end):
        self.tags.setdefault(tag_name, []).append((start, end))

    def see(self, index):
        self.last_seen = index


def test_refresh_and_counter_callback_case_insensitive():
    widget = FakeTextWidget("Alpha beta alpha BETA")
    counters = []
    controller = TextSearchController(widget, "match", "current", on_counter_change=lambda c: counters.append((c.index, len(c.matches))))

    controller.refresh("alpha", reset_index=True)

    assert len(controller.matches) == 2
    assert controller.index == 0
    assert widget.tags["match"]
    assert widget.tags["current"]
    assert counters[-1] == (0, 2)


def test_find_next_and_prev_cycle():
    widget = FakeTextWidget("foo bar foo")
    controller = TextSearchController(widget, "match", "current")

    controller.refresh("foo", reset_index=True)
    assert controller.index == 0

    controller.find_next("foo")
    assert controller.index == 1

    controller.find_next("foo")
    assert controller.index == 0

    controller.find_prev("foo")
    assert controller.index == 1


def test_clear_resets_state_and_tags():
    widget = FakeTextWidget("foo bar foo")
    controller = TextSearchController(widget, "match", "current")
    controller.refresh("foo", reset_index=True)

    controller.clear()

    assert controller.matches == []
    assert controller.index == -1
    assert controller.current_query == ""
    assert widget.tags.get("match", []) == []
    assert widget.tags.get("current", []) == []


def test_preserves_disabled_state_after_search_operations():
    widget = FakeTextWidget("foo bar foo")
    widget.config(state="disabled")
    controller = TextSearchController(widget, "match", "current")

    controller.refresh("foo", reset_index=True)
    controller.find_next("foo")

    assert widget.cget("state") == "disabled"
