"""Background ping daemon operations: start / stop / status."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.debug.common import (
    load_project,
)
from core.debug.ping import (
    ensure_background_ping,
    ping_status,
    stop_background_ping,
)
from core.debug.result import DebugResult


def run_ping_start(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    """Start background ``pingDebugUIParams`` keepalive (CLI between commands)."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = ensure_background_ping(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result


def run_ping_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = stop_background_ping(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result


def run_ping_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    **kwargs: Any,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, _data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    result = ping_status(root, **kwargs)
    result.duration = time.perf_counter() - started
    result.config_id = target.config_id
    result.runtime_id = target.runtime_id
    return result
