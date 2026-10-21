"""Stopped-state inspection: stack, variables, evaluate."""

from __future__ import annotations

from pathlib import Path

from adapters.debug_http import DebugHttpError, TransportFn
from core.debug.common import (
    SessionFactory,
    eval_result_text,
    frames_payload,
    vars_payload,
)
from core.debug.context import DebugContext
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
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    restored = ctx.restore()
    if isinstance(restored, DebugResult):
        return restored
    session = restored.session
    try:
        frames = session.stack(target_id)
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)
    leaf = frames[-1] if frames else None
    return ctx.ok_attached(
        restored,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=frames_payload(frames),
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
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    restored = ctx.restore()
    if isinstance(restored, DebugResult):
        return restored
    session = restored.session
    try:
        result = session.variables(target_id)
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)
    return ctx.ok_attached(
        restored,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        eval_state=result.state,
        variables=vars_payload(result),
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
    ctx = DebugContext.open(
        start,
        config_id=config_id,
        runtime_id=runtime_id,
        transport=transport,
        session_factory=session_factory,
    )
    if isinstance(ctx, DebugResult):
        return ctx
    restored = ctx.restore()
    if isinstance(restored, DebugResult):
        return restored
    session = restored.session
    try:
        result = session.evaluate(expression, target_id)
    except DebugHttpError as exc:
        return ctx.adapter_error(exc)
    return ctx.ok_attached(
        restored,
        target_id=target_id or (session.last_stop.target_id if session.last_stop else None),
        expression=expression,
        eval_state=result.state,
        result=eval_result_text(result),
        variables=vars_payload(result),
    )
