"""Publish lifecycle: up / down / status / url (ADR-025)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from adapters.apache import (
    clear_pid as clear_httpd_pid,
)
from adapters.apache import (
    find_ws_module,
    scaffold_httpd_conf,
    start_httpd,
)
from adapters.apache import (
    read_pid as read_httpd_pid,
)
from adapters.apache.client import ApacheRunResult
from adapters.apache.client import RunFn as ApacheRunFn
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
from adapters.webinst import (
    build_url as webinst_build_url,
)
from adapters.webinst import (
    materialize_publication,
    remove_httpd_publication,
    vrd_matches_ib,
)
from adapters.webinst.client import RunFn as WebinstRunFn
from core.configuration.register import write_manifest_yaml
from core.diagnostics import Diagnostic, error
from core.project.detect import detect_manifest
from core.project.load import load_manifest
from core.project.paths import scope_root_from_manifest
from core.project.resolve import resolve_config_runtime
from core.publish.constants import (
    CODE_APACHE_FAILED,
    CODE_IB_MISSING,
    CODE_IBCMD_MISSING,
    CODE_IBSRV_FAILED,
    CODE_IBSRV_MISSING,
    CODE_PROJECT,
    CODE_WEBINST_MISSING,
)
from core.publish.paths import (
    DEFAULT_HTTP_ADDRESS,
    DEFAULT_HTTP_BASE,
    DEFAULT_WEBINST_ADDRESS,
    data_dir,
    profile_dir,
    resolve_config_path,
    resolve_httpd_conf_path,
    resolve_www_dir,
)
from core.publish.resolve import ResolvedPublishProfile, resolve_or_ensure_publish_profile
from core.publish.result import PublishResult
from core.toolchain.resolve import ApacheResolve, resolve_apache_home


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
    backend: str | None = None,
    ensure: bool = False,
) -> tuple[
    Path | None,
    ResolvedPublishProfile | None,
    Path | None,
    Path | None,
    Path | None,
    PublishResult | None,
]:
    """Return root, profile, db_path, config_path, data_or_www_path, or error result."""
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

    profile, profile_diags, mutated = resolve_or_ensure_publish_profile(
        data,
        profile_id=profile_id,
        backend=backend,
        ensure=ensure,
    )
    if mutated:
        write_manifest_yaml(manifest_path, data)
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
    if profile.backend == "webinst":
        cfg_path = resolve_httpd_conf_path(root, profile.profile_id, profile.confpath_rel)
        extra_path = resolve_www_dir(root, profile.profile_id, profile.dir_rel)
    else:
        cfg_path = resolve_config_path(root, profile.profile_id, profile.config_rel)
        extra_path = data_dir(root, profile.profile_id).resolve()
    return root, profile, db_path, cfg_path, extra_path, None


def _alive_pid(data_path: Path, *, is_alive: IsRunningFn) -> int | None:
    pid = read_lock_pid(data_path)
    if pid is None:
        return None
    if is_alive(pid):
        return pid
    clear_lock_pid(data_path)
    return None


def _alive_httpd_pid(profile_root: Path, *, is_alive: IsRunningFn) -> int | None:
    pid = read_httpd_pid(profile_root)
    if pid is None:
        return None
    if is_alive(pid):
        return pid
    clear_httpd_pid(profile_root)
    return None


def _url_from_config(config_path: Path) -> str | None:
    return build_url(parse_server_config(config_path))


def _webinst_url(profile: ResolvedPublishProfile) -> str:
    wsdir = profile.wsdir or profile.profile_id
    return webinst_build_url(
        address=DEFAULT_WEBINST_ADDRESS,
        port=profile.port,
        wsdir=wsdir,
    )


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
    url: str | None = None,
) -> PublishResult:
    if url is None:
        if profile.backend == "webinst":
            url = _webinst_url(profile)
        else:
            url = _url_from_config(config_path)
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
        url=url,
    )


def run_status(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    backend: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> PublishResult:
    """Report whether publish backend for the profile is running."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running

    root, profile, db_path, cfg_path, extra_path, err = _resolve_context(
        start_path, started=started, profile_id=profile_id, backend=backend, ensure=False
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and extra_path is not None

    if profile.backend == "webinst":
        profile_root = profile_dir(root, profile.profile_id)
        pid = _alive_httpd_pid(profile_root, is_alive=alive)
        running = pid is not None and vrd_matches_ib(extra_path, db_path)
        if pid is not None and not running:
            # httpd up but vrd stale — still report pid
            running = True
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=cfg_path,
            data_path=extra_path,
            running=running,
            pid=pid,
        )

    pid = _alive_pid(extra_path, is_alive=alive)
    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=cfg_path,
        data_path=extra_path,
        running=pid is not None,
        pid=pid,
    )


def run_url(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    backend: str | None = None,
    is_alive: IsRunningFn | None = None,
) -> PublishResult:
    """Return publish URL (running flag from backend pid)."""
    return run_status(start, profile_id=profile_id, backend=backend, is_alive=is_alive)


def run_down(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    backend: str | None = None,
    is_alive: IsRunningFn | None = None,
    terminate_fn: TerminateFn | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    webinst_run: WebinstRunFn | None = None,
) -> PublishResult:
    """Stop publish backend for the profile."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    stopper = terminate_fn or (lambda p: terminate(p, timeout=15.0))

    root, profile, db_path, cfg_path, extra_path, err = _resolve_context(
        start_path, started=started, profile_id=profile_id, backend=backend, ensure=False
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and extra_path is not None

    if profile.backend == "webinst":
        return _run_down_webinst(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            conf_path=cfg_path,
            www_dir=extra_path,
            alive=alive,
            stopper=stopper,
            discover=discover,
            webinst_run=webinst_run,
        )

    pid = _alive_pid(extra_path, is_alive=alive)
    if pid is None:
        clear_lock_pid(extra_path)
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=cfg_path,
            data_path=extra_path,
            running=False,
            pid=None,
        )

    ok = stopper(pid)
    clear_lock_pid(extra_path)
    if not ok and alive(pid):
        return PublishResult(
            status="failed",
            duration=time.perf_counter() - started,
            root=root,
            profile_id=profile.profile_id,
            backend=profile.backend,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=extra_path,
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
        data_path=extra_path,
        running=False,
        pid=None,
    )


def _platform_bin_dir(discovery: DiscoveryResult) -> Path | None:
    """Directory with wsap24 next to webinst / ibcmd / platform root."""
    for tool in (discovery.webinst, discovery.ibcmd):
        if tool.found and tool.path is not None:
            return tool.path.parent
    if discovery.platform.found and discovery.platform.path is not None:
        return discovery.platform.path
    return None


def _run_down_webinst(
    *,
    started: float,
    root: Path,
    profile: ResolvedPublishProfile,
    db_path: Path,
    conf_path: Path,
    www_dir: Path,
    alive: IsRunningFn,
    stopper: TerminateFn,
    discover: Callable[[], DiscoveryResult] | None,
    webinst_run: WebinstRunFn | None,
) -> PublishResult:
    del discover, webinst_run  # binary webinst not used (root-only on Linux)
    profile_root = profile_dir(root, profile.profile_id)
    pid = _alive_httpd_pid(profile_root, is_alive=alive)
    if pid is not None:
        ok = stopper(pid)
        clear_httpd_pid(profile_root)
        if not ok and alive(pid):
            return PublishResult(
                status="failed",
                duration=time.perf_counter() - started,
                root=root,
                profile_id=profile.profile_id,
                backend=profile.backend,
                runtime_path=db_path,
                config_path=conf_path,
                data_path=www_dir,
                running=True,
                pid=pid,
                url=_webinst_url(profile),
                diagnostics=[
                    error(
                        f"Не удалось остановить httpd (pid={pid})",
                        code=CODE_APACHE_FAILED,
                        source="publish",
                    )
                ],
            )
    else:
        clear_httpd_pid(profile_root)

    wsdir = profile.wsdir or profile.profile_id
    if conf_path.is_file() or www_dir.is_dir():
        remove_httpd_publication(conf_path, wsdir=wsdir, www_dir=www_dir)

    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=conf_path,
        data_path=www_dir,
        running=False,
        pid=None,
    )


def run_up(
    start: Path | None = None,
    *,
    profile_id: str | None = None,
    backend: str | None = None,
    discover: Callable[[], DiscoveryResult] | None = None,
    ibcmd_run: IbcmdRunFn | None = None,
    ibsrv_run: IbsrvRunFn | None = None,
    webinst_run: WebinstRunFn | None = None,
    apache_run: ApacheRunFn | None = None,
    apache_home: ApacheResolve | None = None,
    is_alive: IsRunningFn | None = None,
    settle_seconds: float = 0.2,
    wait_lock_seconds: float = 2.0,
) -> PublishResult:
    """Ensure publish backend is up idempotently."""
    started = time.perf_counter()
    start_path = (start or Path.cwd()).resolve()
    alive = is_alive or is_running
    discover_fn = discover or discover_environment

    root, profile, db_path, cfg_path, extra_path, err = _resolve_context(
        start_path,
        started=started,
        profile_id=profile_id,
        backend=backend,
        ensure=True,
    )
    if err is not None or root is None or profile is None:
        return err or _failed(
            started=started,
            diagnostics=[error("Внутренняя ошибка resolve", code=CODE_PROJECT, source="publish")],
        )
    assert db_path is not None and cfg_path is not None and extra_path is not None

    if not infobase_exists(db_path):
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=cfg_path,
            data_path=extra_path,
            diagnostics=[
                error(
                    f"File IB не найдена: {db_path}",
                    code=CODE_IB_MISSING,
                    source="publish",
                    suggestion="Сначала выполните 1c-dev build",
                )
            ],
        )

    if profile.backend == "webinst":
        return _run_up_webinst(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            conf_path=cfg_path,
            www_dir=extra_path,
            discover_fn=discover_fn,
            webinst_run=webinst_run,
            apache_run=apache_run,
            apache_home=apache_home,
            alive=alive,
            settle_seconds=settle_seconds,
            wait_lock_seconds=wait_lock_seconds,
        )

    return _run_up_ibsrv(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        cfg_path=cfg_path,
        data_path=extra_path,
        discover_fn=discover_fn,
        ibcmd_run=ibcmd_run,
        ibsrv_run=ibsrv_run,
        alive=alive,
        settle_seconds=settle_seconds,
        wait_lock_seconds=wait_lock_seconds,
    )


def _run_up_webinst(
    *,
    started: float,
    root: Path,
    profile: ResolvedPublishProfile,
    db_path: Path,
    conf_path: Path,
    www_dir: Path,
    discover_fn: Callable[[], DiscoveryResult],
    webinst_run: WebinstRunFn | None,
    apache_run: ApacheRunFn | None,
    apache_home: ApacheResolve | None,
    alive: IsRunningFn,
    settle_seconds: float,
    wait_lock_seconds: float,
) -> PublishResult:
    del webinst_run  # Linux webinst requires root; we materialize conf/vrd ourselves
    profile_root = profile_dir(root, profile.profile_id)
    pid = _alive_httpd_pid(profile_root, is_alive=alive)
    if pid is not None and vrd_matches_ib(www_dir, db_path):
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=conf_path,
            data_path=www_dir,
            running=True,
            pid=pid,
        )

    discovery = discover_fn()
    resolved = apache_home if apache_home is not None else resolve_apache_home()
    if (
        not resolved.found
        or resolved.httpd is None
        or resolved.home is None
        or resolved.modules_dir is None
    ):
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=conf_path,
            data_path=www_dir,
            diagnostics=[
                error(
                    "Apache httpd (user cache) не найден",
                    code=CODE_APACHE_FAILED,
                    source="publish",
                    suggestion=(
                        "Выполните 1c-dev tools sync или задайте ONEC_APACHE_HOME "
                        "на prefix с bin/httpd (без /etc и sudo)."
                    ),
                )
            ],
        )

    platform_bin = _platform_bin_dir(discovery)
    ws_module = find_ws_module(platform_bin)
    if ws_module is None:
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=conf_path,
            data_path=www_dir,
            diagnostics=[
                error(
                    "Модуль wsap24 (1C Apache handler) не найден",
                    code=CODE_WEBINST_MISSING,
                    source="publish",
                    suggestion=(
                        "Нужна установка платформы 1С с wsap24.so рядом с ibcmd "
                        "(бинарь webinst не вызываем — он требует root)."
                    ),
                )
            ],
        )

    profile_root.mkdir(parents=True, exist_ok=True)
    www_dir.mkdir(parents=True, exist_ok=True)
    wsdir = profile.wsdir or profile.profile_id
    # Always refresh conf/vrd before start (idempotent; picks up scaffold fixes).
    scaffold_httpd_conf(
        conf_path,
        server_root=profile_root,
        port=profile.port,
        modules_dir=resolved.modules_dir,
        ws_module=ws_module,
        address=DEFAULT_WEBINST_ADDRESS,
    )
    materialize_publication(
        conf_path=conf_path,
        www_dir=www_dir,
        wsdir=wsdir,
        db_path=db_path,
    )

    if pid is not None:
        return _ok_snapshot(
            started=started,
            root=root,
            profile=profile,
            db_path=db_path,
            config_path=conf_path,
            data_path=www_dir,
            running=True,
            pid=pid,
        )

    clear_httpd_pid(profile_root)
    result: ApacheRunResult = start_httpd(
        resolved.httpd,
        conf=conf_path,
        server_root=profile_root,
        run=apache_run,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        log_path = profile_root / "logs" / "error.log"
        log_tail = ""
        if log_path.is_file():
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                log_tail = "\n".join(lines[-8:]).strip()
            except OSError:
                log_tail = ""
        msg = "httpd завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:400]}"
        if log_tail:
            msg = f"{msg}\n{log_tail[:400]}"
        return _failed(
            started=started,
            root=root,
            profile=profile,
            runtime_path=db_path,
            config_path=conf_path,
            data_path=www_dir,
            diagnostics=[
                error(
                    msg,
                    code=CODE_APACHE_FAILED,
                    source="publish",
                    suggestion=f"См. {log_path}" if log_path.is_file() else None,
                )
            ],
        )

    if settle_seconds > 0:
        time.sleep(settle_seconds)

    deadline = time.monotonic() + wait_lock_seconds
    new_pid: int | None = None
    while time.monotonic() < deadline:
        new_pid = _alive_httpd_pid(profile_root, is_alive=alive)
        if new_pid is not None:
            break
        time.sleep(0.05)

    if new_pid is None:
        locked = read_httpd_pid(profile_root)
        if locked is not None and alive(locked):
            new_pid = locked
        else:
            return _failed(
                started=started,
                root=root,
                profile=profile,
                runtime_path=db_path,
                config_path=conf_path,
                data_path=www_dir,
                diagnostics=[
                    error(
                        "httpd не оставил живой httpd.pid после старта",
                        code=CODE_APACHE_FAILED,
                        source="publish",
                    )
                ],
            )

    return _ok_snapshot(
        started=started,
        root=root,
        profile=profile,
        db_path=db_path,
        config_path=conf_path,
        data_path=www_dir,
        running=True,
        pid=new_pid,
    )


def _run_up_ibsrv(
    *,
    started: float,
    root: Path,
    profile: ResolvedPublishProfile,
    db_path: Path,
    cfg_path: Path,
    data_path: Path,
    discover_fn: Callable[[], DiscoveryResult],
    ibcmd_run: IbcmdRunFn | None,
    ibsrv_run: IbsrvRunFn | None,
    alive: IsRunningFn,
    settle_seconds: float,
    wait_lock_seconds: float,
) -> PublishResult:
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
