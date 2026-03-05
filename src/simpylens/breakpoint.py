class Breakpoint:
    __slots__ = (
        "_id",
        "condition",
        "label",
        "enabled",
        "pause_on_hit",
        "edge",
        "hit_count",
        "last_error",
        "_last_matched",
        "_kind",
        "_expression",
        "_compiled",
        "_callable",
    )

    def __init__(self, condition, label=None, enabled=True, pause_on_hit=True, edge="none"):
        self._id = None
        self.hit_count = 0
        self.last_error = None
        self._last_matched = None

        self.enabled = bool(enabled)
        self.pause_on_hit = bool(pause_on_hit)

        edge_mode = str(edge).strip().lower()
        if edge_mode not in {"none", "rising", "falling"}:
            raise ValueError("edge must be one of: 'none', 'rising', 'falling'")
        self.edge = edge_mode

        if isinstance(condition, str):
            expr = condition.strip()
            if not expr:
                raise ValueError("Breakpoint condition cannot be empty")
            try:
                compiled = compile(expr, "<breakpoint>", "eval")
            except Exception as exc:
                raise ValueError(f"Invalid breakpoint expression: {exc}") from exc

            self._kind = "expression"
            self._expression = expr
            self._compiled = compiled
            self._callable = None
            self.condition = expr
        elif callable(condition):
            self._kind = "callable"
            self._expression = getattr(condition, "__name__", repr(condition))
            self._compiled = None
            self._callable = condition
            self.condition = condition
        else:
            raise TypeError("Breakpoint condition must be a string expression or a callable")

        label_text = str(label).strip() if label is not None else ""
        self.label = label_text if label_text else self._expression

    @property
    def id(self):
        return self._id

    @property
    def kind(self):
        return self._kind

    @property
    def expression(self):
        return self._expression

    def assign_id(self, breakpoint_id):
        if self._id is not None:
            raise ValueError("Breakpoint id is immutable and already assigned")
        self._id = int(breakpoint_id)

    def evaluate(self, context, eval_builtins):
        if self._kind == "expression":
            return bool(eval(self._compiled, {"__builtins__": eval_builtins}, context))
        return bool(self._callable(context))

    def compute_hit(self, matched):
        previous = self._last_matched

        if self.edge == "rising":
            hit = bool(matched) and previous is not True
        elif self.edge == "falling":
            hit = previous is True and not bool(matched)
        else:
            hit = bool(matched)

        self._last_matched = bool(matched)
        return hit

    def record_hit(self):
        self.hit_count += 1

    def clone_public(self):
        clone_condition = self._expression if self._kind == "expression" else self._callable
        cloned = Breakpoint(
            condition=clone_condition,
            label=self.label,
            enabled=self.enabled,
            pause_on_hit=self.pause_on_hit,
            edge=self.edge,
        )
        if self.id is not None:
            cloned.assign_id(self.id)
        cloned.hit_count = self.hit_count
        cloned.last_error = self.last_error
        return cloned
