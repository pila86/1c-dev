"""Stopped-state inspection: stack, variables, evaluate."""

from __future__ import annotations

import time
from pathlib import Path

from adapters.debug_http import (
    DebugHttpError,
    TransportFn,
)
from core.debug.common import (
    SessionFactory,
    _eval_result_text,
    _frames_payload,
    _handle_adapter_error,
    _load_project,
    _ok,
    _restore_session,
    _vars_payload,
)
from core.debug.result import DebugResult


def run_stack(
    start: Path | None = None,
    *,
    target_id: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = _restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        frames = session.stack(target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    payload = _frames_payload(frames)
    leaf = frames[-1] if frames else None
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=payload,
    )


def run_variables(
    start: Path | None = None,
    *,
    target_id: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = _restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        result = session.variables(target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        eval_state=result.state,
        variables=_vars_payload(result),
    )


def run_evaluate(
    start: Path | None = None,
    *,
    expression: str,
    target_id: str | None = None,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
) -> DebugResult:
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = _load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = _restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    try:
        result = session.evaluate(expression, target_id)
    except DebugHttpError as exc:
        return _handle_adapter_error(exc, started=started, root=root, target=target)
    return _ok(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        expression=expression,
        eval_state=result.state,
        result=_eval_result_text(result),
        variables=_vars_payload(result),
    )
