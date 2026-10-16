"""Debug server / session state under ``.1c-dev/debug/`` (ADR-031)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.debug_http.index import debug_state_dir
from adapters.debug_http.models import BreakpointSpec
from adapters.platform_1cv8 import is_running
from core.debug.constants import (
    DEFAULT_ALIAS,
    DEFAULT_HOST,
    NOTIFY_NAME,
    PING_META_NAME,
    PING_PID_NAME,
    SERVER_META_NAME,
    SERVER_PID_NAME,
    SESSION_LOCK_NAME,
    SESSION_NAME,
)

try:  # POSIX only; Windows falls back to atomic replace without a lock
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def state_dir(root: Path) -> Path:
    return debug_state_dir(root)


def server_pid_path(root: Path) -> Path:
    return state_dir(root) / SERVER_PID_NAME


def server_meta_path(root: Path) -> Path:
    return state_dir(root) / SERVER_META_NAME


def session_path(root: Path) -> Path:
    return state_dir(root) / SESSION_NAME


def notify_path(root: Path) -> Path:
    return state_dir(root) / NOTIFY_NAME


def read_server_pid(root: Path) -> int | None:
    path = server_pid_path(root)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_server_meta(root: Path) -> dict[str, Any]:
    path = server_meta_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_server_state(
    root: Path,
    *,
    pid: int,
    host: str,
    port: int,
    notify: str | None = None,
) -> None:
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    server_pid_path(root).write_text(f"{pid}\n", encoding="utf-8")
    meta: dict[str, Any] = {
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}",
        "startedAt": datetime.now(UTC).isoformat(),
    }
    if notify:
        meta["notify"] = notify
    server_meta_path(root).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_server_state(root: Path) -> None:
    for path in (server_pid_path(root), server_meta_path(root), notify_path(root)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def alive_server(
    root: Path,
    *,
    is_alive: Any | None = None,
) -> tuple[bool, int | None, dict[str, Any]]:
    """Return (running, pid, meta); clear stale pid."""
    check = is_alive or is_running
    pid = read_server_pid(root)
    meta = read_server_meta(root)
    if pid is None:
        return False, None, meta
    if check(pid):
        return True, pid, meta
    clear_server_state(root)
    return False, None, {}


def read_session(root: Path) -> dict[str, Any] | None:
    path = session_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def session_lock_path(root: Path) -> Path:
    return state_dir(root) / SESSION_LOCK_NAME


@contextmanager
def session_lock(root: Path) -> Iterator[None]:
    """Cross-process lock for ``session.json`` read-modify-write.

    CLI commands and the ping daemon update the same file; without a lock the
    last writer silently drops the other side's fields (lastStop, targets).
    """
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(session_lock_path(root), "a+")  # noqa: SIM115 — closed in finally
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def _write_session_file(root: Path, payload: dict[str, Any]) -> None:
    """Atomic replace so readers never see a half-written ``session.json``."""
    path = session_path(root)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def update_session(
    root: Path,
    mutate: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any] | None:
    """Locked read-modify-write of ``session.json``.

    ``mutate`` receives the current dict and returns the new one (or ``None`` to
    keep the file untouched). No-op (returns ``None``) when there is no session.
    """
    if read_session(root) is None:
        return None
    with session_lock(root):
        current = read_session(root)
        if current is None:
            return None
        updated = mutate(dict(current))
        if updated is None:
            return current
        _write_session_file(root, updated)
        return updated


def write_session(
    root: Path,
    *,
    url: str,
    alias: str,
    session_id: str,
    last_stop: dict[str, Any] | None = None,
    attached_targets: list[str] | None = None,
    breakpoints: list[dict[str, Any]] | None = None,
    last_target_id: str | None = None,
    clear_last_stop: bool = False,
    keep_existing_stop: bool = False,
) -> None:
    """Persist debug UI session; merge runtime fields for short-lived CLI.

    ``keep_existing_stop``: a ``lastStop`` already on disk wins over ``last_stop``
    (the ping daemon writes it; a CLI snapshot must not overwrite a newer stop).

    ``attached_targets`` is *unioned* with what is on disk (the ping daemon owns
    pruning). A different ``session_id`` starts a fresh record.
    """
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    with session_lock(root):
        existing = read_session(root) or {}
        if existing.get("sessionId") != session_id:
            existing = {}
        payload: dict[str, Any] = {
            "url": url,
            "alias": alias,
            "sessionId": session_id,
            "attachedAt": existing.get("attachedAt") or datetime.now(UTC).isoformat(),
        }
        if clear_last_stop:
            payload.pop("lastStop", None)
        elif last_stop is not None and not (
            keep_existing_stop and isinstance(existing.get("lastStop"), dict)
        ):
            payload["lastStop"] = last_stop
        elif isinstance(existing.get("lastStop"), dict):
            payload["lastStop"] = existing["lastStop"]

        old_targets = (
            [str(t) for t in existing["attachedTargets"]]
            if isinstance(existing.get("attachedTargets"), list)
            else []
        )
        if attached_targets is not None:
            merged = sorted({*old_targets, *attached_targets})
            if merged:
                payload["attachedTargets"] = merged
        elif old_targets:
            payload["attachedTargets"] = old_targets

        if breakpoints is not None:
            payload["breakpoints"] = list(breakpoints)
        elif isinstance(existing.get("breakpoints"), list):
            payload["breakpoints"] = list(existing["breakpoints"])

        if last_target_id is not None:
            if last_target_id:
                payload["lastTargetId"] = last_target_id
        elif isinstance(existing.get("lastTargetId"), str) and existing["lastTargetId"]:
            payload["lastTargetId"] = existing["lastTargetId"]

        _write_session_file(root, payload)


def reset_session_runtime(root: Path) -> None:
    """Drop stale stop / targets before spawning a fresh client (keeps BP + session)."""

    def _mutate(data: dict[str, Any]) -> dict[str, Any]:
        for key in ("lastStop", "attachedTargets", "lastTargetId"):
            data.pop(key, None)
        return data

    update_session(root, _mutate)
    directory = eval_dir(root)
    if directory.is_dir():
        for stale in directory.glob("*"):
            try:
                stale.unlink()
            except OSError:
                pass


def breakpoints_from_stored(stored: dict[str, Any]) -> list[BreakpointSpec]:
    """``session.json`` ``breakpoints`` → ``BreakpointSpec`` list."""
    raw_bps = stored.get("breakpoints")
    restored: list[BreakpointSpec] = []
    if not isinstance(raw_bps, list):
        return restored
    for item in raw_bps:
        if not isinstance(item, dict):
            continue
        oid = str(item.get("objectId") or "")
        pid = str(item.get("propertyId") or "")
        lines_raw = item.get("lines") or []
        if not oid or not pid or not isinstance(lines_raw, list):
            continue
        lines = tuple(int(x) for x in lines_raw if isinstance(x, int) or str(x).isdigit())
        if not lines:
            continue
        restored.append(
            BreakpointSpec(
                object_id=oid,
                property_id=pid,
                lines=lines,
                extension_name=str(item.get("extensionName") or ""),
            )
        )
    return restored


def serialize_last_stop(stop: Any) -> dict[str, Any] | None:
    """``StopEvent`` → JSON-friendly dict for ``session.json``."""
    if stop is None:
        return None
    frames = []
    for frame in getattr(stop, "frames", ()) or ():
        frames.append(
            {
                "objectId": getattr(frame, "object_id", "") or "",
                "propertyId": getattr(frame, "property_id", "") or "",
                "lineNo": int(getattr(frame, "line_no", 0) or 0),
                "moduleName": getattr(frame, "module_name", "") or "",
                "moduleType": getattr(frame, "module_type", "") or "",
                "extensionName": getattr(frame, "extension_name", "") or "",
            }
        )
    return {
        "targetId": getattr(stop, "target_id", "") or "",
        "frames": frames,
    }


def serialize_breakpoints(specs: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in specs or ():
        out.append(
            {
                "objectId": getattr(spec, "object_id", "") or "",
                "propertyId": getattr(spec, "property_id", "") or "",
                "lines": list(getattr(spec, "lines", ()) or ()),
                "extensionName": getattr(spec, "extension_name", "") or "",
            }
        )
    return out


def persist_session_runtime(
    root: Path,
    session: Any,
    *,
    url: str,
    alias: str,
    clear_last_stop: bool = False,
) -> None:
    """Write session.json including stop/targets/BP for the next CLI process."""
    write_session(
        root,
        url=url,
        alias=alias,
        session_id=str(getattr(session, "session_id", "") or ""),
        last_stop=(
            None
            if clear_last_stop
            else serialize_last_stop(getattr(session, "last_stop", None))
        ),
        attached_targets=sorted(getattr(session, "attached_targets", ()) or ()),
        breakpoints=serialize_breakpoints(getattr(session, "breakpoints", ())),
        last_target_id=str(getattr(session, "last_target_id", "") or ""),
        clear_last_stop=clear_last_stop,
        keep_existing_stop=True,
    )


def clear_session(root: Path) -> None:
    try:
        session_path(root).unlink(missing_ok=True)
    except OSError:
        pass


def ping_pid_path(root: Path) -> Path:
    return state_dir(root) / PING_PID_NAME


def ping_meta_path(root: Path) -> Path:
    return state_dir(root) / PING_META_NAME


def read_ping_pid(root: Path) -> int | None:
    path = ping_pid_path(root)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_ping_meta(root: Path) -> dict[str, Any]:
    path = ping_meta_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_ping_state(
    root: Path,
    *,
    pid: int,
    session_id: str,
    url: str,
) -> None:
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    ping_pid_path(root).write_text(f"{pid}\n", encoding="utf-8")
    meta: dict[str, Any] = {
        "pid": pid,
        "sessionId": session_id,
        "url": url,
        "startedAt": datetime.now(UTC).isoformat(),
    }
    ping_meta_path(root).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_ping_state(root: Path) -> None:
    for path in (ping_pid_path(root), ping_meta_path(root)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def alive_ping(
    root: Path,
    *,
    is_alive: Any | None = None,
) -> tuple[bool, int | None, dict[str, Any]]:
    """Return (running, pid, meta); clear stale pid."""
    check = is_alive or is_running
    pid = read_ping_pid(root)
    meta = read_ping_meta(root)
    if pid is None:
        return False, None, meta
    if check(pid):
        return True, pid, meta
    clear_ping_state(root)
    return False, None, {}


def manifest_debug_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize top-level ``debug`` block from project.yaml."""
    raw = data.get("debug")
    block: dict[str, Any] = raw if isinstance(raw, dict) else {}
    host = block.get("host")
    port = block.get("port")
    alias = block.get("infobaseAlias")
    types = block.get("autoAttachTypes")
    return {
        "host": host.strip() if isinstance(host, str) and host.strip() else DEFAULT_HOST,
        "port": int(port) if isinstance(port, int) else None,
        "alias": (
            alias.strip()
            if isinstance(alias, str) and alias.strip()
            else DEFAULT_ALIAS
        ),
        "autoAttachTypes": (
            [str(t) for t in types]
            if isinstance(types, list) and types
            else None
        ),
    }


def resolve_debugger_url(
    root: Path,
    data: dict[str, Any],
    *,
    explicit: str | None = None,
) -> str | None:
    """DebuggerURL order (ADR-031): explicit → live server state → manifest host+port."""
    if explicit and explicit.strip():
        return explicit.strip().rstrip("/")
    running, _pid, meta = alive_server(root)
    if running:
        url = meta.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip().rstrip("/")
        host = meta.get("host")
        port = meta.get("port")
        if isinstance(host, str) and isinstance(port, int):
            return f"http://{host}:{port}"
    settings = manifest_debug_settings(data)
    if settings["port"] is not None:
        return f"http://{settings['host']}:{settings['port']}"
    return None


EVAL_DIR_NAME = "eval"
_EVAL_KEEP = 50


def eval_dir(root: Path) -> Path:
    return state_dir(root) / EVAL_DIR_NAME


def write_eval_result(root: Path, result_id: str, body: str) -> None:
    """Daemon: keep an ``exprEvaluated`` ping body for the CLI that asked for it."""
    if not result_id or "/" in result_id or "\\" in result_id:
        return
    directory = eval_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result_id}.xml"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    files = sorted(directory.glob("*.xml"), key=lambda p: p.stat().st_mtime)
    for old in files[:-_EVAL_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def wait_eval_result(
    root: Path, result_id: str, timeout: float, *, poll_interval: float = 0.05
) -> str | None:
    """CLI: wait for the daemon to store the async result of ``result_id``."""
    import time

    path = eval_dir(root) / f"{result_id}.xml"
    deadline = time.perf_counter() + max(0.0, timeout)
    while True:
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except OSError:
            pass
        if time.perf_counter() >= deadline:
            return None
        time.sleep(poll_interval)
