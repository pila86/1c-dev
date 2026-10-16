"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def stub_background_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid real ping_worker; track synthetic pids for alive_ping/stop."""
    from adapters.platform_1cv8 import is_running as real_is_running

    fake_pids: set[int] = set()
    next_pid = {"n": 910000}

    def fake_spawn(root: Path, log_path: Path) -> int:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_bytes(b"")
        next_pid["n"] += 1
        pid = next_pid["n"]
        fake_pids.add(pid)
        return pid

    def hybrid_is_running(pid: int) -> bool:
        if pid in fake_pids:
            return True
        return real_is_running(pid)

    def fake_terminate(pid: int, *, timeout: float = 5.0) -> bool:
        fake_pids.discard(pid)
        return True

    monkeypatch.setattr("core.debug.ping.default_spawn_ping", fake_spawn)
    monkeypatch.setattr("core.debug.ping.is_running", hybrid_is_running)
    monkeypatch.setattr("core.debug.ping.terminate", fake_terminate)
    monkeypatch.setattr("core.debug.state.is_running", hybrid_is_running)
