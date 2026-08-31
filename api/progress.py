"""Progress callback shim (replaces Gradio Progress in API)."""

from __future__ import annotations

from typing import Callable

ProgressFn = Callable[[float, str | None], None]


class ProgressShim:
    def __init__(self, on_tick: ProgressFn | None = None):
        self._on_tick = on_tick
        self.last_pct: float = 0.0
        self.last_msg: str = ""

    def __call__(self, p: float, desc: str | None = None) -> None:
        from workflow.task_control import check_cancelled

        check_cancelled()
        self.last_pct = p
        self.last_msg = desc or ""
        if self._on_tick:
            self._on_tick(p, desc or "")
