"""Optional Gradio import for desktop / API paths that must not require Gradio.

When Gradio is installed (classic UI), re-exports the real module.
Otherwise provides a minimal stub so FastAPI can import stage helpers.
"""

from __future__ import annotations

try:
    import gradio as gr
except ImportError:  # pragma: no cover — desktop core has no Gradio

    class Error(ValueError):
        """Stand-in for gradio.Error (subclass ValueError → API maps to HTTP 400)."""

    class _NullProgress:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __call__(self, *args, **kwargs) -> None:
            pass

        def tqdm(self, iterable, *args, **kwargs):
            return iterable

    class _GrStub:
        Error = Error

        @staticmethod
        def Progress(*args, **kwargs) -> _NullProgress:
            return _NullProgress()

        @staticmethod
        def update(**kwargs):
            return kwargs

    gr = _GrStub()  # type: ignore[assignment]

__all__ = ["gr"]
