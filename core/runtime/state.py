"""Persist detached client pid + meta under .runtime/ (ADR-019)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapters.platform_1cv8.constants import (
    CLIENT_META_REL,
    CLIENT_PID_REL,
    CLIENT_THICK,
    MODE_ENTERPRISE,
)


def pid_path(root: Path) -> Path:
    return root / CLIENT_PID_REL


def meta_path(root: Path) -> Path:
    return root / CLIENT_META_REL


def read_pid(root: Path) -> int | None:
    path = pid_path(root)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text)
    except (OSError, ValueError):
        return None


def _default_meta() -> dict[str, Any]:
    return {
        "mode": MODE_ENTERPRISE,
        "client": CLIENT_THICK,
        "debug": {"enabled": False},
    }


def read_meta(root: Path) -> dict[str, Any]:
    path = meta_path(root)
    if not path.is_file():
        return _default_meta()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_meta()
    if not isinstance(data, dict):
        return _default_meta()
    mode = data.get("mode") or MODE_ENTERPRISE
    client = data.get("client") or CLIENT_THICK
    debug_raw = data.get("debug")
    debug: dict[str, Any] = debug_raw if isinstance(debug_raw, dict) else {}
    enabled = bool(debug.get("enabled", False))
    return {
        "mode": str(mode),
        "client": str(client),
        "debug": {"enabled": enabled},
    }


def write_state(
    root: Path,
    *,
    pid: int,
    debug: bool,
    mode: str = MODE_ENTERPRISE,
    client: str = CLIENT_THICK,
) -> None:
    pid_file = pid_path(root)
    meta_file = meta_path(root)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{pid}\n", encoding="utf-8")
    meta = {"mode": mode, "client": client, "debug": {"enabled": debug}}
    meta_file.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clear_state(root: Path) -> None:
    for path in (pid_path(root), meta_path(root)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
