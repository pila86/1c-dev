"""Publish lifecycle: up / down / status / url (ADR-025)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from adapters.ibsrv import (
    build_url,
    clear_lock_pid,
    parse_server_config,
    read_lock_pid,
    start_daemon,
)
from adapters.ibsrv.client import IbsrvRunResult
from adapters.ibsrv.client import RunFn as IbsrvRunFn
from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_1cv8 import IsRunningFn, TerminateFn, is_running, terminate
from adapters.platform_ibcmd import IbcmdError, infobase_exists, server_config_init
from adapters.platform_ibcmd.client import RunFn as IbcmdRunFn
from core.diagnostics import Diagnostic, error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.publish.constants import (
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_IBSRV_FAILED,
    CODE_IBSRV_MISSING,
    CODE_PROJECT,
)
from core.publish.paths import (
    DEFAULT_HTTP_ADDRESS,
    DEFAULT_HTTP_BASE,
    data_dir,
    resolve_config_path,
)
from core.publish.resolve import ResolvedPublishProfile, resolve_publish_profile
from core.publish.result import PublishResult


def _failed(
    *,
    started: float,
    diagnostics: list[Diagnostic],
    root: Path | None = None,
    profile: ResolvedPublishProfile | None = None,
    runtime_path: Path | None = None,
    config_path: Path | None = None,
    data_path: Path | None = None,
) -> PublishResult:
    return PublishResult(
        status="failed",
        duration=time.perf_counter() - started,
        root=root,
        profile_id=profile.profile_id if profile else None,
        backend=profile.backend if profile else None,
        runtime_path=runtime_path,
        config_path=config_path,
        data_path=data_path,
        diagnostics=list(diagnostics),
    )


def _resolve_context(
    start: Path,
    *,
    started: float,
    profile_id: str | None,
) -> tuple[
    Path | None,
    ResolvedPublishProfile | None,
    Path | None,
    Path | None,
    Path | None,
    PublishResult | None,
]:
    """Return root, profile, db_path, config_path, data_path, or error result."""
    manifest_path = detect_manifest(start)
    if manifest_path is None:
        return (
            None,
            None,
            None,
            None,
            None,
            _failed(
                started=started,
                diagnostics=[
                    error(
                        "Файл проекта не найден",
                        code=CODE_PROJECT,
                        source="publish",
                        suggestion="Выполните 1c-dev init --type configuration",
                    )
                ],
            ),
        )

    data, load_diags = load_manifest(manifest_path)
    root = scope_root_from_manifest(manifest_path)
    if data is None:
        return (
            root,
            None,
            None,
            None,
            None,
            _failed(
                started=started,
                root=root,
                diagnostics=list(load_diags)
                or [
                    error(
                        "Не удалось прочитать манифест",
                        code=CODE_PROJECT,
                        source="publish",
                    )
                ],
            ),
        )

    profile, profile_diags = resolve_publish_profile(data, profile_id=profile_id)
    if profile is None:
        return (
            root,
            None,
            None,
            None,
            None,
            _failed(started=started, root=root, diagnostics=profile_diags),
        )

    target, resolve_diags = resolve_config_runtime(
        data,
        runtime_id=profile.runtime_id,
        require_runtime=True,
    )
    if target is None or target.runtime_rel is None:
        return (
            root,
            profile,
            None,
            None,
            None,
            _failed(
                started=started,
                root=root,
                profile=profile,
                diagnostics=list(resolve_diags)
                or [
                    error(
                        f"Не удалось разрешить runtime={profile.runtime_id!r}",
                        code=CODE_PROJECT,
                        source="publish",
                    )
                ],
            ),
        )

    db_path = (root / target.runtime_rel).resolve()
    cfg_path = resolve_config_path(root, profile.profile_id, profile.config_rel)
    data_path = data_dir(root, profile.profile_id).resolve()
    return root, profile, db_path, cfg_path, data_path, None


def _alive_pid(data_path: Path, *, is_alive: IsRunningFn) -> int | None:
    pid = read_lock_pid(data_path)
    if pid is None:
        return None
    if is_alive(pid):
        return pid
    clear_lock_pid(data_path)
    return None


def _url_from_config(config_path: Path) -> str | None:
    return build_url(parse_server_config(config_path))


def _yaml_needs_init(config_path: Path, *, db_path: Path, port: int) -> bool:
    if not config_path.is_file():
        return True
    cfg = parse_server_config(config_path)
    database = cfg.get("database")
    path_val: str | None = None
    if isinstance(database, dict):
        raw = database.get("path")
        if isinstance(raw, str):
            path_val = raw
    server = cfg.get("server")
    port_val: int | None = None
    if isinstance(server, dict):
        raw_port = server.get("port")
        if isinstance(raw_port, int):
            port_val = raw_port
        else:
            try:
                port_val = int(raw_port)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                port_val = None
    if path_val is None or Path(path_val).resolve() != db_path.resolve():
        return True
    if port_val != port:
        return True
    return False


def _ok_snapshot(
    *,
    started: float,
    root: Path,
    profile: ResolvedPublishProfile,
    db_path: Path,
    config_path: Path,
    data_path: Path,
    running: bool,
    pid: int | None,
) -> PublishResult:
    return PublishResult(
        status="ok",
        duration=time.perf_counter() - started,
        root=root,
        profile_id=profile.profile_id,
        backend=profile.backend,
        runtime_path=db_path,
        config_path=config_path,
        data_path=data_path,
        running=running,
        pid=pid,
        url=_url_from_config(config_path),
    )


def run_status(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> PublishResult:
    """Report whether ibsrv for the publish profile is running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, profile, db_path, cfg_path, data_path, err = _resolve_context(
        start_path, started=started, profile_id=profile_id
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and data_path is not None

    pid = _alive_pid(data_path, is_alive=alive)
    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=cfg_path,
        data_path=data_path,
        running=pid is not None,
        pid=pid,
    )


def run_url(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> PublishResult:
    """Return publish URL from ibsrv YAML (running flag from lock.pid)."""
    return run_status(start, profile_id=profile_id, is_alive=is_alive)


def run_down(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
) -> PublishResult:
    """Stop ibsrv for the profile (TERM → KILL) and clear stale lock."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    # ibsrv often ignores quick SIGTERM (spike #84); give TERM→KILL more time.
    stopper = terminate_fn or (lambda p: terminate(p, timeout=15.0))

    root, profile, db_path, cfg_path, data_path, err = _resolve_context(
        start_path, started=started, profile_id=profile_id
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and data_path is not None

    pid = _alive_pid(data_path, is_alive=alive)
    if pid is None:
        clear_lock_pid(data_path)
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            running=False,
            pid=None,
        )

    ok = stopper(pid)
    clear_lock_pid(data_path)
    if not ok and alive(pid):
        return PublishResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            profile_id=profile.profile_id,
            backend=profile.backend,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            running=True,
            pid=pid,
            url=_url_from_config(cfg_path),
            diagnostics=[
                error(
                    f"Не удалось остановить ibsrv (pid={pid})",
                    code=CODE_IBSRV_FAILED,
                    source="publish",
                )
            ],
        )

    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=cfg_path,
        data_path=data_path,
        running=False,
        pid=None,
    )


def run_up(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    ibcmd_run: IbcmdRunFn | None = None,
    ibsrv_run: IbsrvRunFn | None = None,
    is_alive: IsRunningFn | None = None,
    settle_seconds: float = 0.2,
    wait_lock_seconds: float = 2.0,
) -> PublishResult:
    """Ensure ibsrv YAML exists and start daemon idempotently."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    discover_fn = discover or discover_environment

    root, profile, db_path, cfg_path, data_path, err = _resolve_context(
        start_path, started=started, profile_id=profile_id
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and data_path is not None

    if not infobase_exists(db_path):
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            diagnostics=[
                error(
                    f"File IB не найдена: {db_path}",
                    code=CODE_IB_MISSING,
                    source="publish",
                    suggestion="Сначала выполните 1c-dev build",
                )
            ],
        )

    pid = _alive_pid(data_path, is_alive=alive)
    if pid is not None:
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            running=True,
            pid=pid,
        )

    discovery = discover_fn()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            diagnostics=[
                error(
                    "ibcmd не найден (нужен для server config init)",
                    code=CODE_IBCMD_MISSING,
                    source="publish",
                    suggestion="Установите платформу 1С и добавьте ibcmd в PATH.",
                )
            ],
        )
    if not discovery.ibsrv.found or discovery.ibsrv.path is None:
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            diagnostics=[
                error(
                    "ibsrv не найден",
                    code=CODE_IBSRV_MISSING,
                    source="publish",
                    suggestion=(
                        "Установите платформу 1С с автономным сервером "
                        "и добавьте ibsrv в PATH (см. 1c-dev doctor)."
                    ),
                )
            ],
        )

    if _yaml_needs_init(cfg_path, db_path=db_path, port=profile.port):
        try:
            server_config_init(
                discovery.ibcmd.path,
                out=cfg_path,
                db_path=db_path,
                http_port=profile.port,
                name=profile.name,
                http_address=DEFAULT_HTTP_ADDRESS,
                http_base=DEFAULT_HTTP_BASE,
                run=ibcmd_run,
            )
        except IbcmdError as exc:
            return _failed(
                started=started,
                root=root,
                profile=profile,
                runtime_path=db_path,
                config_path=cfg_path,
                data_path=data_path,
                diagnostics=list(exc.diagnostics)
                or [
                    error(
                        exc.message,
                        code=exc.code,
                        source="publish",
                    )
                ],
            )

    data_path.mkdir(parents=True, exist_ok=True)
    clear_lock_pid(data_path)
    result: IbsrvRunResult = start_daemon(
        discovery.ibsrv.path,
        config=cfg_path,
        data=data_path,
        run=ibsrv_run,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        msg = "ibsrv --daemon завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=data_path,
            diagnostics=[
                error(
                    msg,
                    code=CODE_IBSRV_FAILED,
                    source="publish",
                )
            ],
        )

    if settle_seconds > 0:
        time.sleep(settle_seconds)

    deadline = time.monotonic() + wait_lock_seconds
    new_pid: int | None = None
    while time.monotonic() < deadline:
        new_pid = _alive_pid(data_path, is_alive=alive)
        if new_pid is not None:
            break
        time.sleep(0.05)

    if new_pid is None:
        # Daemon may have written pid of a process we cannot see yet;
        # still accept lock.pid if present even when is_alive is mocked oddly.
        locked = read_lock_pid(data_path)
        if locked is not None and alive(locked):
            new_pid = locked
        else:
            return _failed(
                started=started,
                root=root,
                profile=profile,
                runtime_path=db_path,
                config_path=cfg_path,
                data_path=data_path,
                diagnostics=[
                    error(
                        "ibsrv не оставил живой lock.pid после старта",
                        code=CODE_IBSRV_FAILED,
                        source="publish",
                    )
                ],
            )

    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=cfg_path,
        data_path=data_path,
        running=True,
        pid=new_pid,
    )
