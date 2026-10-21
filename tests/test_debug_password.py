"""dbgs password: env-only resolution, no leaks into state / payload / diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.debug_http import AttachResult, HttpResponse
from core.debug import run_attach, run_server_start
from core.debug.common import PASSWORD_ENV, mask_secret, resolve_debug_password
from core.debug.state import write_server_state
from tests.helpers_debug import fake_session, init_project, make_discovery

pytestmark = pytest.mark.usefixtures("stub_background_ping")

SECRET = "s3cret-pwd"


def _transport(url: str, data: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
    return HttpResponse(200, "<ok/>")


def _all_state_text(root: Path) -> str:
    chunks = []
    for path in (root / ".1c-dev").rglob("*"):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def test_resolve_debug_password_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert resolve_debug_password() == ""
    monkeypatch.setenv(PASSWORD_ENV, "from-env")
    assert resolve_debug_password() == "from-env"
    assert resolve_debug_password("explicit") == "explicit"
    # explicit empty value disables the env password
    assert resolve_debug_password("") == ""


def test_mask_secret() -> None:
    assert mask_secret(f"boom --password={SECRET} x", SECRET) == "boom --password=*** x"
    assert mask_secret("nothing", SECRET) == "nothing"
    assert mask_secret("keep", None) == "keep"
    assert mask_secret("keep", "") == "keep"


def test_server_start_passes_env_password_to_argv_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, SECRET)
    monkeypatch.setattr("core.debug.server._port_free", lambda _h, _p: True)
    target = init_project(tmp_path)
    spawned: list[list[str]] = []

    def spawn(argv: list[str], log_path: Path) -> int:
        spawned.append(list(argv))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        notify = target / ".1c-dev" / "debug" / "server.notify"
        notify.parent.mkdir(parents=True, exist_ok=True)
        notify.write_bytes("ok".encode("utf-16"))
        return 9101

    result = run_server_start(
        target,
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        is_alive=lambda pid: pid == 9101,
        transport=_transport,
        settle_seconds=0,
        notify_timeout=1.0,
    )
    assert result.status == "ok"
    assert f"--password={SECRET}" in spawned[0]
    assert SECRET not in json.dumps(result.to_payload(), ensure_ascii=False)
    assert SECRET not in _all_state_text(target)


def test_server_start_explicit_empty_password_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, SECRET)
    monkeypatch.setattr("core.debug.server._port_free", lambda _h, _p: True)
    target = init_project(tmp_path)
    spawned: list[list[str]] = []

    def spawn(argv: list[str], log_path: Path) -> int:
        spawned.append(list(argv))
        notify = target / ".1c-dev" / "debug" / "server.notify"
        notify.parent.mkdir(parents=True, exist_ok=True)
        notify.write_bytes("ok".encode("utf-16"))
        return 9102

    run_server_start(
        target,
        password="",
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        is_alive=lambda pid: pid == 9102,
        transport=_transport,
        settle_seconds=0,
        notify_timeout=1.0,
    )
    assert not any(a.startswith("--password") for a in spawned[0])


def test_server_start_spawn_error_masks_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, SECRET)
    monkeypatch.setattr("core.debug.server._port_free", lambda _h, _p: True)
    target = init_project(tmp_path)

    def spawn(argv: list[str], log_path: Path) -> int:
        raise OSError(f"exec failed: {' '.join(argv)}")

    result = run_server_start(
        target,
        discover=lambda: make_discovery(dbgs=Path("/fake/dbgs")),
        spawn=spawn,
        transport=_transport,
        settle_seconds=0,
        notify_timeout=1.0,
    )
    assert result.status == "failed"
    text = json.dumps(result.to_payload(), ensure_ascii=False)
    assert SECRET not in text
    assert "--password=***" in text


def test_attach_uses_env_password_and_does_not_persist_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, SECRET)
    target = init_project(tmp_path)
    write_server_state(target, pid=1, host="localhost", port=2550)
    attach = MagicMock(return_value=AttachResult(session_id="sid-pwd", result="registered"))

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(attach=attach, stop_ping=MagicMock(), start_ping=MagicMock())

    result = run_attach(target, transport=_transport, session_factory=factory)
    assert result.status == "ok"
    attach.assert_called_once_with(password=SECRET, start_ping=False)
    assert SECRET not in json.dumps(result.to_payload(), ensure_ascii=False)
    assert SECRET not in _all_state_text(target)


def test_attach_without_password_sends_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    target = init_project(tmp_path)
    write_server_state(target, pid=1, host="localhost", port=2550)
    attach = MagicMock(return_value=AttachResult(session_id="sid-np", result="registered"))

    def factory(client: Any, **kwargs: Any) -> MagicMock:
        return fake_session(attach=attach, stop_ping=MagicMock(), start_ping=MagicMock())

    run_attach(target, transport=_transport, session_factory=factory)
    attach.assert_called_once_with(password="", start_ping=False)
