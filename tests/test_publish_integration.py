"""Integration: publish.up → HTTP 200 on publish.url (ADR-025 / #89)."""

from __future__ import annotations

import os
import signal
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from core.build import run_build
from core.publish import run_down, run_up, run_url
from tests.helpers_project import bootstrap_configuration_project


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _set_publish_port(root: Path, port: int) -> None:
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    publish = data.setdefault("publish", {})
    profiles = publish.setdefault("profiles", {})
    runtime_id = data["runtimes"][0]["id"]
    profile = profiles.setdefault(
        "local-ibsrv",
        {
            "backend": "ibsrv",
            "runtime": runtime_id,
            "config": ".1c-dev/publish/local-ibsrv/ibsrv.yaml",
        },
    )
    profile["port"] = port
    profile.setdefault("backend", "ibsrv")
    publish["default"] = "local-ibsrv"
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _wait_http_ok(url: str, *, timeout: float = 20.0) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read()
                return int(resp.getcode()), body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.25)
    raise AssertionError(f"HTTP не поднялся за {timeout}s: {url}: {last_err}")


def _can_signal(pid: int) -> bool:
    """False when sandbox/privileges deny kill(pid, 0)."""
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


@pytest.mark.integration
def test_publish_ibsrv_http_accessible(tmp_path: Path) -> None:
    """build → publish.up → GET url → 200; skip without ibcmd/ibsrv."""
    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — publish integration пропущен")
    if not discovery.ibsrv.found or discovery.ibsrv.path is None:
        pytest.skip("ibsrv не найден — publish integration пропущен")

    target = tmp_path / "shop"
    target.mkdir()
    init = bootstrap_configuration_project(target, name="Shop")
    assert init.status == "ok", init.to_payload()

    port = _free_port()
    _set_publish_port(target, port)

    build = run_build(target)
    assert build.status == "ok", build.to_payload()
    assert (target / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    up = run_up(target, settle_seconds=0.3, wait_lock_seconds=5.0)
    pid = up.pid
    try:
        assert up.status == "ok", up.to_payload()
        assert up.running is True
        assert pid is not None
        assert up.url is not None
        assert f":{port}" in up.url

        url_result = run_url(target)
        assert url_result.status == "ok", url_result.to_payload()
        assert url_result.url == up.url

        code, body = _wait_http_ok(up.url)
        assert code == 200
        assert body, "пустое тело ответа веб-клиента"
        # Spike #84: HTML клиента 1С
        lowered = body.lower()
        assert b"<" in lowered or b"1c" in lowered or b"e1cib" in lowered

        # Stop may be blocked in Cursor sandbox (PermissionError on kill); HTTP is the
        # acceptance criterion. Outside sandbox run_down must succeed.
        if _can_signal(pid):
            down = run_down(target)
            assert down.status == "ok", down.to_payload()
            assert down.running is False
    finally:
        if pid is not None and _can_signal(pid):
            run_down(target)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
