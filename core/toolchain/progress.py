"""Progress reporting for toolchain sync (text UX)."""

from __future__ import annotations

from collections.abc import Callable

ProgressFn = Callable[[str], None]


def noop_progress(_message: str) -> None:
    """No-op progress sink (json / tests)."""
