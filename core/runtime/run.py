"""Runtime client lifecycle: start / stop / status (ADR-019)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import (
    IsRunningFn,
    SpawnFn,
    TerminateFn,
    is_running,
    start_enterprise_client,
    stop_client,
)
from adapters.platform_1cv8.constants import (
    CLIENT_THICK,
    CLIENT_THIN,
    MODE_ENTERPRISE,
)
from adapters.platform_ibcmd import infobase_exists
from core.diagnostics import Diagnostic, error, warning
from core.project.constants import HOME_MANIFEST_REL
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.runtime.constants import (
    CODE_CLIENT_FAILED,
    CODE_IB_MISSING,
    CODE_ONECV8_MISSING,
    CODE_ONECV8C_MISSING,
    CODE_PROJECT,
)
from core.runtime.result import RuntimeResult
from core.runtime.state import clear_state, read_meta, read_pid, write_state

ClientKind = Literal["thick", "thin"]


def _debugger_url_from_meta(meta: dict[str, Any]) -> str | None:
    debug_raw = meta.get("debug")
    if not isinstance(debug_raw, dict):
        return None
    url = debug_raw.get("debuggerUrl")
    return url.strip() if isinstance(url, str) and url.strip() else None


def _resolve_debugger_url_for_start(
    root: Path,
    data: dict[str, Any],
    *,
    explicit: str | None,
) -> str | None:
    from core.debug.state import resolve_debugger_url

    return resolve_debugger_url(root, data, explicit=explicit)


def _gui_suggestion() -> str:
    if sys.platform == "win32":
        return "Запускайте на машине с интерактивной GUI-сессией Windows."
    return (
        "Нужен графический дисплей (DISPLAY). "
        "На headless-хосте запустите клиент в сессии с GUI."
    )


def _normalize_client(client: str) -> ClientKind:
    value = client.strip().lower()
    if value == CLIENT_THIN:
        return "thin"
    return "thick"


def _resolve_project(
    start: Path,
    *,
    started: float,
    config_id: str | None = None,
    runtime_id: str | None = None,
) -> tuple[Path, Path, RuntimeResult | None]:
    """Return (root, db_path, error_result_or_None)."""
    manifest_path = detect_manifest(start)
    if manifest_path is None:
        return (
            start,
            start,
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                diagnostics=[
                    error(
                        f"Файл {HOME_MANIFEST_REL} не найден",
                        code=CODE_PROJECT,
                        source="runtime",
                        suggestion="Выполните 1c-dev init --type configuration",
                    )
                ],
            ),
        )

    data, load_diags = load_manifest(manifest_path)
    if data is None:
        return (
            scope_root_from_manifest(manifest_path),
            scope_root_from_manifest(manifest_path),
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=scope_root_from_manifest(manifest_path),
                diagnostics=list(load_diags)
                or [
                    error(
                        "Не удалось прочитать манифест",
                        code=CODE_PROJECT,
                        file=str(manifest_path.name),
                        source="runtime",
                    )
                ],
            ),
        )

    root = scope_root_from_manifest(manifest_path)
    target, resolve_diags = resolve_config_runtime(
        data,
        config_id=config_id,
        runtime_id=runtime_id,
        require_runtime=True,
    )
    if target is None or target.runtime_rel is None:
        return (
            root,
            root,
            RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                diagnostics=list(resolve_diags)
                or [
                    error(
                        "Не удалось разрешить --config/--runtime",
                        code=CODE_PROJECT,
                        source="runtime",
                    )
                ],
            ),
        )
    db_path = (root / target.runtime_rel).resolve()
    return root, db_path, None


def _alive_snapshot(
    root: Path,
    *,
    is_alive: IsRunningFn,
) -> tuple[bool, int | None, str, str, bool, str | None]:
    """Return (running, pid, mode, client, debug_enabled, debugger_url); clear stale."""
    pid = read_pid(root)
    meta = read_meta(root)
    mode = str(meta.get("mode") or MODE_ENTERPRISE)
    client = str(meta.get("client") or CLIENT_THICK)
    debug_raw = meta.get("debug")
    debug_enabled = bool(
        debug_raw.get("enabled") if isinstance(debug_raw, dict) else False
    )
    debugger_url = _debugger_url_from_meta(meta)
    if pid is None:
        return False, None, mode, client, debug_enabled, debugger_url
    if is_alive(pid):
        return True, pid, mode, client, debug_enabled, debugger_url
    clear_state(root)
    return False, None, MODE_ENTERPRISE, CLIENT_THICK, False, None


def run_status(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> RuntimeResult:
    """Report whether the detached ENTERPRISE client is running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    running, pid, mode, client, debug_enabled, debugger_url = _alive_snapshot(
        root, is_alive=alive
    )
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=running,
        pid=pid,
        mode=mode if running else None,
        client=client if running else None,
        debug_enabled=debug_enabled if running else False,
        debugger_url=debugger_url if running else None,
    )


def _teardown_debug_state(
    start_path: Path,
    root: Path,
    *,
    config_id: str | None,
    runtime_id: str | None,
    is_alive: IsRunningFn | None,
    terminate_fn: TerminateFn | None,
) -> list[Diagnostic]:
    """Stop ping daemon, debug session and our own dbgs; failures are warnings."""
    from core.debug.ops import has_debug_state, teardown_debug

    if not has_debug_state(root):
        return []
    try:
        result = teardown_debug(
            start_path,
            config_id=config_id,
            runtime_id=runtime_id,
            is_alive=is_alive,
            terminate_fn=terminate_fn,
        )
    except Exception as exc:  # noqa: BLE001 — runtime stop must still succeed
        return [
            warning(
                f"не удалось полностью остановить debug: {exc}",
                code=CODE_CLIENT_FAILED,
                source="runtime",
            )
        ]
    diags: list[Diagnostic] = []
    for diag in result.diagnostics:
        if diag.get("severity") == "error":
            diags.append(
                warning(
                    str(diag.get("message", "")),
                    code=diag.get("code"),
                    source="runtime",
                    suggestion=diag.get("suggestion"),
                )
            )
        else:
            diags.append(diag)
    return diags


def run_stop(
    start: Path | None = None,
    *,
    config_id: str | None = None,
    runtime_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> RuntimeResult:
    """Stop the client and everything debug-related.

    Order: client → ping daemon → debug UI session (detach) → ``dbgs`` (only when
    we started it) → ``.1c-dev/debug`` state. Idempotent.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    running, pid, mode, client, debug_enabled, debugger_url = _alive_snapshot(
        root, is_alive=alive
    )
    if not running or pid is None:
        clear_state(root)
        teardown_diags = _teardown_debug_state(
            start_path,
            root,
            config_id=config_id,
            runtime_id=runtime_id,
            is_alive=is_alive,
            terminate_fn=terminate_fn,
        )
        return RuntimeResult(
            status="ok",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=False,
            pid=None,
            mode=None,
            client=None,
            debug_enabled=False,
            diagnostics=teardown_diags,
        )

    ok = stop_client(pid, terminate_fn=terminate_fn)
    clear_state(root)
    if not ok and alive(pid):
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=True,
            pid=pid,
            mode=mode,
            client=client,
            debug_enabled=debug_enabled,
            debugger_url=debugger_url,
            diagnostics=[
                error(
                    f"Не удалось остановить процесс клиента 1С (pid={pid})",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                )
            ],
        )

    teardown_diags = _teardown_debug_state(
        start_path,
        root,
        config_id=config_id,
        runtime_id=runtime_id,
        is_alive=is_alive,
        terminate_fn=terminate_fn,
    )
    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=False,
        pid=None,
        mode=None,
        client=None,
        debug_enabled=False,
        diagnostics=teardown_diags,
    )


def run_start(
    start: Path | None = None,
    *,
    client: str = CLIENT_THICK,
    debug: bool = False,
    debugger_url: str | None = None,
    breakpoints: Sequence[str] | None = None,
    targets_timeout: float = 15.0,
    config_id: str | None = None,
    runtime_id: str | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    spawn: SpawnFn | None = None,
    is_alive: IsRunningFn | None = None,
    settle_seconds: float = 0.3,
) -> RuntimeResult:
    """Detach-start ENTERPRISE client (thick or thin) against the project file IB.

    With ``debug=True``, prefers HTTP attach argv when DebuggerURL is known
    (explicit / live ``debug.server`` / manifest ``debug.host``+``port``, ADR-031).
    Without ``breakpoints`` and without an existing ``session.json``, still
    ensures dbgs + attach before spawn (parity with ``test.run* --debug``, #147).

    With ``breakpoints`` (``--bp file:line``), ensures dbgs + attach + BP *before*
    spawning the client, then polls ``session.json`` until the ping daemon has
    attached a debug target (or timeout). It never waits for a stop — use
    ``debug wait`` for that.

    With ``debug=True`` and an existing ``session.json`` (MCP stepwise:
    ``debug.attach`` + ``debug.breakpoint`` then ``runtime.start``), resets
    stale stop/targets, ensures the ping daemon, and awaits target arm — same
    as the ``--bp`` path, without re-running ensure/attach.
    """
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    client_kind = _normalize_client(client)
    bp_raw = [str(x).strip() for x in (breakpoints or []) if str(x).strip()]

    root, db_path, err = _resolve_project(
        start_path,
        started=started,
        config_id=config_id,
        runtime_id=runtime_id,
    )
    if err is not None:
        return err

    if bp_raw and not debug:
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    "--bp требует --debug",
                    code=CODE_PROJECT,
                    source="runtime",
                    suggestion=(
                        "1c-dev runtime start --debug "
                        "--bp src/main/Ext/ManagedApplicationModule.bsl:4"
                    ),
                )
            ],
        )
    # Manifest needed for DebuggerURL resolution when debug=True
    manifest_path = detect_manifest(start_path)
    manifest_data: dict[str, Any] = {}
    if manifest_path is not None:
        loaded, _ = load_manifest(manifest_path)
        if isinstance(loaded, dict):
            manifest_data = loaded

    debug_bps: list[dict[str, Any]] = []
    debug_session_id: str | None = None
    extra_diags: list[Diagnostic] = []
    arm_debug_targets = False
    resolved_url = (
        _resolve_debugger_url_for_start(root, manifest_data, explicit=debugger_url)
        if debug
        else None
    )

    if debug and bp_raw:
        from core.debug.ops import ensure_debug_for_runtime

        boot = ensure_debug_for_runtime(
            start_path,
            breakpoints=bp_raw,
            debugger_url=debugger_url,
            config_id=config_id,
            runtime_id=runtime_id,
            discover=discover,
            is_alive=alive,
        )
        if boot.status != "ok":
            return RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                debug_enabled=True,
                debugger_url=boot.debugger_url or boot.url or resolved_url,
                breakpoints=list(boot.breakpoints),
                session_id=boot.session_id,
                diagnostics=list(boot.diagnostics),
            )
        resolved_url = boot.debugger_url or boot.url or resolved_url
        debug_bps = list(boot.breakpoints)
        debug_session_id = boot.session_id
        arm_debug_targets = True
    elif debug:
        from core.debug.state import read_session

        stored = read_session(root)
        if stored is not None:
            arm_debug_targets = True
            debug_session_id = str(stored.get("sessionId") or "") or None
            raw_bps = stored.get("breakpoints")
            if isinstance(raw_bps, list):
                debug_bps = [bp for bp in raw_bps if isinstance(bp, dict)]
            session_url = stored.get("url")
            if isinstance(session_url, str) and session_url.strip():
                resolved_url = session_url.strip()
        if not arm_debug_targets:
            # No prior session and no --bp: still ensure dbgs + attach before spawn.
            from core.debug.ops import ensure_debug_for_runtime

            boot = ensure_debug_for_runtime(
                start_path,
                breakpoints=[],
                debugger_url=debugger_url,
                config_id=config_id,
                runtime_id=runtime_id,
                discover=discover,
                is_alive=alive,
            )
            if boot.status != "ok":
                return RuntimeResult(
                    status="failed",
                    duration=time.perf_counter() - started,
                    root=root,
                    runtime_path=db_path,
                    debug_enabled=True,
                    debugger_url=boot.debugger_url or boot.url or resolved_url,
                    breakpoints=list(boot.breakpoints),
                    session_id=boot.session_id,
                    diagnostics=list(boot.diagnostics),
                )
            resolved_url = boot.debugger_url or boot.url or resolved_url
            debug_session_id = boot.session_id
            arm_debug_targets = True

    running, pid, mode, running_client, debug_enabled, running_url = _alive_snapshot(
        root, is_alive=alive
    )
    if running and pid is not None:
        if running_client == client_kind:
            return RuntimeResult(
                status="ok",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                running=True,
                pid=pid,
                mode=mode,
                client=running_client,
                debug_enabled=debug_enabled,
                debugger_url=running_url,
            )
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            running=True,
            pid=pid,
            mode=mode,
            client=running_client,
            debug_enabled=debug_enabled,
            debugger_url=running_url,
            diagnostics=[
                error(
                    (
                        f"Уже запущен клиент client={running_client} (pid={pid}); "
                        f"запрошен client={client_kind}"
                    ),
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion="Выполните 1c-dev runtime stop и повторите start",
                )
            ],
        )

    if not infobase_exists(db_path):
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"File IB не найдена: нет маркера 1Cv8.1CD в {db_path}",
                    code=CODE_IB_MISSING,
                    source="runtime",
                    suggestion="Сначала выполните 1c-dev build или 1c-dev runtime load",
                )
            ],
        )

    discovery = (discover or discover_environment)()
    if client_kind == CLIENT_THIN:
        tool = discovery.onecv8c
        missing_code = CODE_ONECV8C_MISSING
        missing_name = "1cv8c"
        missing_suggestion = (
            "Установите платформу 1С с тонким клиентом и добавьте 1cv8c в PATH "
            "(обычно рядом с 1cv8 в каталоге установки)."
        )
    else:
        tool = discovery.onecv8
        missing_code = CODE_ONECV8_MISSING
        missing_name = "1cv8"
        missing_suggestion = (
            "Установите платформу 1С и добавьте 1cv8 в PATH "
            "(или в стандартный каталог установки)."
        )

    if not tool.found or tool.path is None:
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"{missing_name} не найден",
                    code=missing_code,
                    source="platform",
                    suggestion=missing_suggestion,
                )
            ],
        )

    # Reset stale stop/targets and make sure the daemon runs *before* spawn:
    # the daemon is the only ping reader, so no event of the new client is lost.
    # Also for MCP stepwise (session already on disk, no --bp).
    if arm_debug_targets:
        from core.debug.ops import prepare_debug_for_spawn

        prepared = prepare_debug_for_spawn(
            start_path,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        if prepared.status != "ok":
            return RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                debug_enabled=True,
                debugger_url=resolved_url,
                breakpoints=debug_bps,
                session_id=debug_session_id or prepared.session_id,
                diagnostics=list(prepared.diagnostics),
            )
        extra_diags.extend(prepared.diagnostics)

    try:
        new_pid, _argv = start_enterprise_client(
            tool.path,
            ib_path=db_path,
            debug=debug,
            debugger_url=resolved_url,
            spawn=spawn,
            settle_seconds=settle_seconds,
            is_alive=alive,
        )
    except RuntimeError as exc:
        clear_state(root)
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    str(exc),
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=_gui_suggestion(),
                )
            ],
        )
    except OSError as exc:
        clear_state(root)
        return RuntimeResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            runtime_path=db_path,
            diagnostics=[
                error(
                    f"Не удалось запустить {missing_name}: {exc}",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=_gui_suggestion(),
                )
            ],
        )

    write_state(
        root,
        pid=new_pid,
        debug=debug,
        mode=MODE_ENTERPRISE,
        client=client_kind,
        debugger_url=resolved_url if debug else None,
    )

    targets_armed = False
    if arm_debug_targets:
        from core.debug.ops import await_debug_targets_armed

        armed = await_debug_targets_armed(
            start_path,
            timeout=targets_timeout,
            config_id=config_id,
            runtime_id=runtime_id,
        )
        if armed.status != "ok":
            return RuntimeResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                runtime_path=db_path,
                running=True,
                pid=new_pid,
                mode=MODE_ENTERPRISE,
                client=client_kind,
                debug_enabled=True,
                debugger_url=resolved_url,
                breakpoints=debug_bps,
                session_id=debug_session_id or armed.session_id,
                diagnostics=list(armed.diagnostics),
            )
        targets_armed = bool(armed.targets)
        if not targets_armed:
            extra_diags.append(
                warning(
                    f"debug target не появился за {targets_timeout:g}s — BP могут не сработать",
                    code=CODE_CLIENT_FAILED,
                    source="runtime",
                    suggestion=(
                        "проверьте GUI/DISPLAY и 1c-dev debug targets; "
                        "затем debug wait"
                    ),
                )
            )

    return RuntimeResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        runtime_path=db_path,
        running=True,
        pid=new_pid,
        mode=MODE_ENTERPRISE,
        client=client_kind,
        debug_enabled=debug,
        debugger_url=resolved_url if debug else None,
        breakpoints=debug_bps,
        session_id=debug_session_id,
        targets_armed=targets_armed,
        diagnostics=list(extra_diags),
    )
