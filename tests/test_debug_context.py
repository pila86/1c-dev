"""core.debug.context.DebugContext: project resolve, identity in results, session restore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.debug import CODE_NO_SESSION, CODE_PROJECT, DebugResult
from core.debug.context import DebugContext, RestoredSession
from core.debug.state import write_session
from tests.helpers_debug import fake_session, init_project

pytestmark = pytest.mark.usefixtures("stub_background_ping")


def test_open_without_manifest_returns_failed_result(tmp_path: Path) -> None:
    ctx = DebugContext.open(tmp_path)
    assert isinstance(ctx, DebugResult)
    assert ctx.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in ctx.diagnostics)


def test_open_resolves_target_and_builds_results(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    ctx = DebugContext.open(target)
    assert isinstance(ctx, DebugContext)
    assert ctx.config_id
    assert ctx.runtime_id is None  # project without runtimes[]

    ok = ctx.ok(url="http://localhost:2550")
    assert ok.status == "ok"
    assert ok.config_id == ctx.config_id
    assert ok.runtime_id == ctx.runtime_id
    assert ok.url == "http://localhost:2550"

    failed = ctx.fail([])
    assert failed.status == "failed"
    assert failed.config_id == ctx.config_id


def test_restore_without_session_fails_with_no_session(tmp_path: Path) -> None:
    ctx = DebugContext.open(init_project(tmp_path))
    assert isinstance(ctx, DebugContext)
    restored = ctx.restore()
    assert isinstance(restored, DebugResult)
    assert any(d.get("code") == CODE_NO_SESSION for d in restored.diagnostics)


def test_restore_uses_session_factory_and_ok_attached(tmp_path: Path) -> None:
    target = init_project(tmp_path)
    write_session(target, url="http://localhost:2550", alias="DefAlias", session_id="sid-ctx")
    seen: dict[str, Any] = {}

    def factory(client: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return fake_session()

    ctx = DebugContext.open(target, session_factory=factory)
    assert isinstance(ctx, DebugContext)
    restored = ctx.restore()
    assert isinstance(restored, RestoredSession)
    assert restored.url == "http://localhost:2550"
    assert restored.alias == "DefAlias"
    assert seen["session_id"] == "sid-ctx"

    result = ctx.ok_attached(restored, target_id="t1")
    assert result.status == "ok"
    assert result.attached is True
    assert result.url == "http://localhost:2550"
    assert result.alias == "DefAlias"
    assert result.session_id == "sid-test"  # fake_session.session_id
    assert result.target_id == "t1"
