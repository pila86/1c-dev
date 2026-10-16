"""Shared helpers for debug unit tests (core.debug / CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from adapters.debug_http import StopEvent
from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from core.debug.state import read_session, serialize_last_stop, write_session
from tests.helpers_project import bootstrap_configuration_project

SPIKE_OBJECT = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"
SPIKE_TARGET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def make_tool(found: bool, path: Path | None = None) -> ToolInfo:
    return ToolInfo(found=found, path=path)


def make_discovery(*, dbgs: Path | None = None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=make_tool(True, Path("/fake/ibcmd")),
        onecv8=make_tool(True, Path("/fake/1cv8")),
        onecv8c=make_tool(False),
        ibsrv=make_tool(False),
        webinst=make_tool(False),
        dbgs=make_tool(dbgs is not None, dbgs),
    )


def init_project(tmp_path: Path, *, debug_port: int | None = 2550) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    if debug_port is not None:
        manifest = target / ".1c-dev" / "project.yaml"
        text = manifest.read_text(encoding="utf-8")
        if "debug:" not in text:
            text += (
                f"\ndebug:\n  host: localhost\n  port: {debug_port}\n  infobaseAlias: DefAlias\n"
            )
            manifest.write_text(text, encoding="utf-8")
    return target


def fake_session(**methods: Any) -> MagicMock:
    session = MagicMock()
    session.session_id = "sid-test"
    session.attached = True
    session.last_stop = None
    for name, value in methods.items():
        setattr(session, name, value)
    return session


def persist_stop(root: Path, stop: StopEvent, *, session_id: str = "sid-1") -> None:
    """Simulate ping_worker writing callStackFormed → session.json lastStop."""
    cur = read_session(root) or {}
    write_session(
        root,
        url=str(cur.get("url") or "http://localhost:2550"),
        alias=str(cur.get("alias") or "DefAlias"),
        session_id=str(cur.get("sessionId") or session_id),
        last_stop=serialize_last_stop(stop),
        last_target_id=stop.target_id or None,
        attached_targets=[stop.target_id] if stop.target_id else None,
    )
