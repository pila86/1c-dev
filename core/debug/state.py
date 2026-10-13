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
) -> None:
    directory = state_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "alias": alias,
        "sessionId": session_id,
        "attachedAt": datetime.now(UTC).isoformat(),
    }
    session_path(root).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
