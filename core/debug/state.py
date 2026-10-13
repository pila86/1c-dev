"""Debug server / session state under ``.1c-dev/debug/`` (ADR-031)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adapters.debug_http.index import debug_state_dir
from adapters.platform_1cv8 import is_running
from core.debug.constants import (
    DEFAULT_ALIAS,
    DEFAULT_HOST,
    NOTIFY_NAME,
    SERVER_META_NAME,
    SERVER_PID_NAME,
    SESSION_NAME,
)


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
) -> None:
    """Persist debug UI session; merge runtime fields for short-lived CLI."""
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    existing = read_session(root) or {}
    payload: dict[str, Any] = {
        "url": url,
        "alias": alias,
        "sessionId": session_id,
        "attachedAt": existing.get("attachedAt") or datetime.now(UTC).isoformat(),
    }
    if clear_last_stop:
        payload.pop("lastStop", None)
    elif last_stop is not None:
        payload["lastStop"] = last_stop
    elif isinstance(existing.get("lastStop"), dict):
        payload["lastStop"] = existing["lastStop"]

    if attached_targets is not None:
        payload["attachedTargets"] = list(attached_targets)
    elif isinstance(existing.get("attachedTargets"), list):
        payload["attachedTargets"] = list(existing["attachedTargets"])

    if breakpoints is not None:
        payload["breakpoints"] = list(breakpoints)
    elif isinstance(existing.get("breakpoints"), list):
        payload["breakpoints"] = list(existing["breakpoints"])

    if last_target_id is not None:
        if last_target_id:
            payload["lastTargetId"] = last_target_id
    elif isinstance(existing.get("lastTargetId"), str) and existing["lastTargetId"]:
        payload["lastTargetId"] = existing["lastTargetId"]

    session_path(root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
        attached_targets=sorted(getattr(session, "_attached_targets", set()) or []),
        breakpoints=serialize_breakpoints(getattr(session, "_breakpoints", [])),
        last_target_id=str(getattr(session, "_last_target_id", "") or ""),
        clear_last_stop=clear_last_stop,
    )


def clear_session(root: Path) -> None:
    try:
        session_path(root).unlink(missing_ok=True)
    except OSError:
        pass


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
