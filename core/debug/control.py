"""Execution control: wait, continue, step-in/over/out, experimental pause.

Contract (ADR-031 / spike #135 §5a): the ping daemon is the only reader of
``pingDebugUIParams``. These functions never ping — they send a command and
read ``session.json`` (``lastStop``). ``debug wait`` is state based: if a stop is
already recorded it returns at once; if the 1C client exited it fails fast.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from adapters.debug_http import (
    ARM_PING_INTERVAL_SEC,
    DEFAULT_WAIT_TIMEOUT_SEC,
    DebugHttpError,
    DebugSession,
    StopEvent,
    TransportFn,
)
from adapters.platform_1cv8 import is_running
from core.debug.common import (
    SessionFactory,
    apply_stored_runtime,
    fail_result,
    frames_payload,
    handle_adapter_error,
    load_project,
    ok_result,
    restore_session,
)
from core.debug.constants import (
    CODE_CLIENT_EXITED,
    CODE_PROJECT,
    CODE_WAIT_TIMEOUT,
    SOURCE_DEBUG,
)
from core.debug.ping import soft_ensure_background_ping
from core.debug.result import DebugResult
from core.debug.state import (
    alive_ping,
    persist_session_runtime,
    read_session,
)
from core.diagnostics import error, warning
from core.runtime.state import read_pid

ClientAliveFn = Callable[[], bool | None]

PAUSE_EXPERIMENTAL_MESSAGE = (
    "pause — экспериментальный и может не работать (ADR-031: не проходил live acceptance); "
    "надёжный сценарий — breakpoint → debug wait → variables/eval → step/continue"
)


_ACTION_LABEL = {
    "Continue": "continue",
    "Step": "step-over",
    "StepIn": "step-in",
    "StepOut": "step-out",
}


def _client_alive_probe(root: Path) -> ClientAliveFn:
    """``True``/``False`` if ``runtime start`` recorded a client pid; ``None`` unknown."""

    def probe() -> bool | None:
        pid = read_pid(root)
        if pid is None:
            return None
        return is_running(pid)

    return probe


def _stored_stop(root: Path, session: DebugSession) -> StopEvent | None:
    stored = read_session(root)
    if stored is None or not isinstance(stored.get("lastStop"), dict):
        return None
    apply_stored_runtime(session, stored)
    # Prefer _last_stop (set by hydrate); MagicMock may shadow .last_stop.
    stop = getattr(session, "_last_stop", None) or getattr(session, "last_stop", None)
    if not isinstance(stop, StopEvent):
        return None
    if isinstance(session, DebugSession) and stop.frames:
        frames = session._enrich_frames(stop.frames)  # noqa: SLF001
        stop = StopEvent(
            target_id=stop.target_id,
            frames=tuple(frames),
            raw_xml=getattr(stop, "raw_xml", "") or "",
        )
        session._last_stop = stop  # noqa: SLF001
    return stop


def _await_persisted_stop(
    root: Path,
    session: DebugSession,
    *,
    timeout: float,
    poll_interval: float = ARM_PING_INTERVAL_SEC,
    client_alive: ClientAliveFn | None = None,
) -> StopEvent:
    """Return the stop recorded by the ping daemon in ``session.json``.

    Immediate if ``lastStop`` is already on disk. Raises ``1CD016`` when the
    client process is gone and no stop arrived, ``1CD005`` on timeout.
    """
    deadline = time.perf_counter() + max(0.0, timeout)
    while True:
        stop = _stored_stop(root, session)
        if stop is not None:
            return stop
        if client_alive is not None and client_alive() is False:
            # One last look: the stop may have been written just before exit.
            stop = _stored_stop(root, session)
            if stop is not None:
                return stop
            message = "клиент 1С завершился, остановки на breakpoint не было"
            raise DebugHttpError(
                message,
                code=CODE_CLIENT_EXITED,
                diagnostics=[
                    error(
                        message,
                        code=CODE_CLIENT_EXITED,
                        source=SOURCE_DEBUG,
                        suggestion=(
                            "проверьте --bp (строка/модуль) и повторите "
                            "runtime start --debug --bp …"
                        ),
                    )
                ],
            )
        if time.perf_counter() >= deadline:
            raise DebugHttpError(
                f"таймаут ожидания остановки ({timeout:g}s)",
                code=CODE_WAIT_TIMEOUT,
                diagnostics=[
                    error(
                        f"таймаут ожидания остановки ({timeout:g}s)",
                        code=CODE_WAIT_TIMEOUT,
                        source=SOURCE_DEBUG,
                    )
                ],
            )
        time.sleep(max(0.02, poll_interval))


def run_wait(
    start: Path | None = None,
    *,
    timeout: float = DEFAULT_WAIT_TIMEOUT_SEC,
    fresh: bool = False,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
    client_alive: ClientAliveFn | None = None,
) -> DebugResult:
    """Wait for a stop (``callStackFormed``) — state based.

    Returns immediately if ``session.json`` already holds ``lastStop``.
    ``fresh=True`` drops it first (use after resuming/restarting the client to
    wait for the *next* stop). Fails fast with ``1CD016`` when the client exited.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = restore_session(
        root,
        data,
        target,
        transport=transport,
        session_factory=session_factory,
        start_ping=False,
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err
    if fresh:
        session.clear_cached_stop()
        persist_session_runtime(root, session, url=base, alias=alias, clear_last_stop=True)
    ping_diags = soft_ensure_background_ping(root)
    probe = client_alive if client_alive is not None else _client_alive_probe(root)
    try:
        stop = _await_persisted_stop(root, session, timeout=timeout, client_alive=probe)
    except DebugHttpError as exc:
        return handle_adapter_error(exc, started=started, root=root, target=target)
    frames = frames_payload(stop.frames)
    leaf = stop.current_frame
    persist_session_runtime(root, session, url=base, alias=alias)
    ping_running, ping_pid, _ping_meta = alive_ping(root)
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=stop.target_id,
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=frames,
        ping_pid=ping_pid,
        ping_running=ping_running,
        diagnostics=ping_diags,
    )


def _run_step(
    action: str,
    start: Path | None = None,
    *,
    target_id: str | None = None,
    wait: bool = True,
    timeout: float = DEFAULT_WAIT_TIMEOUT_SEC,
    config_id: str | None = None,
    runtime_id: str | None = None,
    transport: TransportFn | None = None,
    session_factory: SessionFactory | None = None,
    client_alive: ClientAliveFn | None = None,
) -> DebugResult:
    """Send continue/step/pause; by default wait for the next stop.

    ``Continue``/``Step``/``StepIn``/``StepOut`` are supported (live acceptance
    passed). ``Pause`` is experimental: a warning diagnostic is attached.
    If the program runs to the end while waiting (client exits, e.g. ``StepOut``
    from the outermost frame) the result is ``ok`` with a ``1CD016`` warning.
    ``wait=False`` is fire-and-forget (``--no-wait``).
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    root, data, target, err = load_project(
        start_path, started=started, config_id=config_id, runtime_id=runtime_id
    )
    if err is not None:
        return err
    assert target is not None
    session, base, alias, restore_err = restore_session(
        root, data, target, transport=transport, session_factory=session_factory
    )
    if restore_err is not None:
        restore_err.duration = time.perf_counter() - started
        return restore_err

    leaves_stopped = action in ("Continue", "Step", "StepIn", "StepOut")
    extra_diags: list[Any] = soft_ensure_background_ping(root)
    if action == "Pause":
        extra_diags.append(
            warning(
                PAUSE_EXPERIMENTAL_MESSAGE,
                code=CODE_WAIT_TIMEOUT,
                source=SOURCE_DEBUG,
            )
        )
    # Pin the stopped target before clearing state.
    step_tid = target_id
    cached_stop = getattr(session, "_last_stop", None)
    if step_tid is None and isinstance(cached_stop, StopEvent) and cached_stop.target_id:
        step_tid = cached_stop.target_id
    if wait:
        session.clear_cached_stop()
        persist_session_runtime(root, session, url=base, alias=alias, clear_last_stop=True)

    try:
        if action == "Continue":
            session.continue_(step_tid)
        elif action == "Step":
            session.step_over(step_tid)
        elif action == "StepIn":
            session.step_in(step_tid)
        elif action == "StepOut":
            session.step_out(step_tid)
        elif action == "Pause":
            session.pause()
        else:
            return fail_result(
                started=started,
                root=root,
                diagnostics=[
                    error(f"неизвестное действие {action}", code=CODE_PROJECT, source=SOURCE_DEBUG)
                ],
            )
    except DebugHttpError as exc:
        return handle_adapter_error(exc, started=started, root=root, target=target)

    if not wait:
        if leaves_stopped:
            session.clear_cached_stop()
        persist_session_runtime(
            root, session, url=base, alias=alias, clear_last_stop=leaves_stopped
        )
        return ok_result(
            started=started,
            root=root,
            config_id=target.config_id,
            runtime_id=target.runtime_id,
            url=base,
            alias=alias,
            session_id=session.session_id,
            attached=True,
            target_id=target_id,
            diagnostics=extra_diags,
        )

    probe = client_alive if client_alive is not None else _client_alive_probe(root)
    try:
        stop = _await_persisted_stop(root, session, timeout=timeout, client_alive=probe)
    except DebugHttpError as exc:
        if leaves_stopped and exc.code == CODE_CLIENT_EXITED:
            # Program ran to the end after continue/step — normal completion.
            session.clear_cached_stop()
            persist_session_runtime(
                root, session, url=base, alias=alias, clear_last_stop=True
            )
            return ok_result(
                started=started,
                root=root,
                config_id=target.config_id,
                runtime_id=target.runtime_id,
                url=base,
                alias=alias,
                session_id=session.session_id,
                attached=True,
                diagnostics=list(extra_diags)
                + [
                    warning(
                        (
                            f"после {_ACTION_LABEL.get(action, action)} клиент 1С "
                            "завершился (программа выполнена)"
                        ),
                        code=CODE_CLIENT_EXITED,
                        source=SOURCE_DEBUG,
                        suggestion="runtime stop — очистить debug-состояние",
                    )
                ],
            )
        err_result = handle_adapter_error(exc, started=started, root=root, target=target)
        if extra_diags:
            err_result.diagnostics = list(err_result.diagnostics) + list(extra_diags)
        return err_result

    frames = frames_payload(stop.frames)
    leaf = stop.current_frame
    persist_session_runtime(root, session, url=base, alias=alias)
    ping_running, ping_pid, _ping_meta = alive_ping(root)
    return ok_result(
        started=started,
        root=root,
        config_id=target.config_id,
        runtime_id=target.runtime_id,
        url=base,
        alias=alias,
        session_id=session.session_id,
        attached=True,
        target_id=stop.target_id,
        module_name=leaf.module_name if leaf else None,
        line_no=leaf.line_no if leaf else None,
        call_stack=frames,
        ping_pid=ping_pid,
        ping_running=ping_running,
        diagnostics=extra_diags,
    )


def run_continue(start: Path | None = None, **kwargs: Any) -> DebugResult:
    """Resume the stopped target; waits for the next stop (``--no-wait`` to skip).

    If the program runs to the end (client exits) the wait fails with ``1CD016``
    — for a one-shot scenario use ``--no-wait`` and then ``runtime stop``.
    """
    return _run_step("Continue", start, **kwargs)


def run_step_in(start: Path | None = None, **kwargs: Any) -> DebugResult:
    """StepIn — заход в вызываемый метод."""
    return _run_step("StepIn", start, **kwargs)


def run_step_over(start: Path | None = None, **kwargs: Any) -> DebugResult:
    """Step over (platform ``Step``)."""
    return _run_step("Step", start, **kwargs)


def run_step_out(start: Path | None = None, **kwargs: Any) -> DebugResult:
    """StepOut — выход из текущего кадра."""
    return _run_step("StepOut", start, **kwargs)


def run_pause(start: Path | None = None, **kwargs: Any) -> DebugResult:
    """EXPERIMENTAL. Pause via ``breakOnNextLine``."""
    return _run_step("Pause", start, **kwargs)
