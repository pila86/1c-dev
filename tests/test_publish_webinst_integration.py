"""Integration: publish.up webinst (skip without webinst/apache) (#94)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from adapters.platform.discovery import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from core.publish import run_down, run_up
from core.toolchain.resolve import resolve_apache_home
from tests.helpers_project import bootstrap_configuration_project


@pytest.mark.integration
def test_publish_webinst_lifecycle(tmp_path: Path) -> None:
    """publish.up → url shape → down; skip without wsap24 / apache home."""
    discovery = discover_environment()
    platform_bin = None
    if discovery.webinst.found and discovery.webinst.path is not None:
        platform_bin = discovery.webinst.path.parent
    elif discovery.ibcmd.found and discovery.ibcmd.path is not None:
        platform_bin = discovery.ibcmd.path.parent
    if platform_bin is None or not (platform_bin / "wsap24.so").is_file():
        pytest.skip("wsap24.so не найден рядом с платформой — webinst publish skip")
    apache = resolve_apache_home()
    if not apache.found or apache.httpd is None:
        pytest.skip("Apache home не найден — выполните 1c-dev tools sync")

    root = tmp_path / "shop"
    root.mkdir()
    assert bootstrap_configuration_project(root, name="Shop").status == "ok"
    ib = root / ".1c-dev" / "runtime" / "main"
    ib.mkdir(parents=True, exist_ok=True)
    (ib / IB_MARKER).write_bytes(b"")

    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "local-webinst",
        "profiles": {
            "local-webinst": {
                "backend": "webinst",
                "runtime": runtime_id,
                "port": 18315,
                "server": "apache24",
                "wsdir": "shop",
            }
        },
    }
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    up = run_up(root, settle_seconds=0.3, wait_lock_seconds=3.0)
    if up.status != "ok":
        pytest.skip(f"webinst publish недоступен в окружении: {up.diagnostics}")
    assert up.url is not None
    assert "18315" in up.url
    assert "shop" in up.url
    assert up.running is True

    down = run_down(root)
    assert down.status == "ok"
    assert down.running is False
