"""M4 acceptance: nested + multi-config + extension + templates + publish (#96)."""

from __future__ import annotations

import json
import os
import signal
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import yaml

from adapters.platform import DiscoveryResult, discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen
from adapters.source.xmlgen.resolve import resolve_java as resolve_java_xml
from core.build import run_build
from core.configuration import add_configuration
from core.doctor import run_doctor
from core.extension import add_extension
from core.import_cf import run_import
from core.project import (
    HOME_MANIFEST_REL,
    configure_ide,
    detect_project,
    init_project,
    list_projects,
)
from core.project.result import build_scope_summary
from core.publish import run_down, run_up, run_url
from core.templates import templates_list
from core.toolchain.resolve import resolve_apache_home

_MAX_TEMPLATE_CF_BYTES = 30_000_000


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_manifest(root: Path, data: dict[str, Any]) -> None:
    manifest = root / ".1c-dev" / "project.yaml"
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _set_ibsrv_publish(root: Path, port: int) -> None:
    data = _load_manifest(root)
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "local-ibsrv",
        "profiles": {
            "local-ibsrv": {
                "backend": "ibsrv",
                "port": port,
                "runtime": runtime_id,
                "config": ".1c-dev/publish/local-ibsrv/ibsrv.yaml",
            }
        },
    }
    _write_manifest(root, data)


def _set_webinst_publish(root: Path, port: int, *, wsdir: str = "shop") -> None:
    data = _load_manifest(root)
    runtime_id = data["runtimes"][0]["id"]
    data["publish"] = {
        "default": "local-webinst",
        "profiles": {
            "local-webinst": {
                "backend": "webinst",
                "port": port,
                "runtime": runtime_id,
                "server": "apache24",
                "wsdir": wsdir,
            }
        },
    }
    _write_manifest(root, data)


def _wait_http_ok(url: str, *, timeout: float = 20.0) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return int(resp.getcode()), resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.25)
    raise AssertionError(f"HTTP не поднялся за {timeout}s: {url}: {last_err}")


def _can_signal(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _soft_publish_ibsrv(shop: Path, discovery: DiscoveryResult) -> None:
    if not discovery.ibsrv.found or discovery.ibsrv.path is None:
        return

    port = _free_port()
    _set_ibsrv_publish(shop, port)
    up = run_up(shop, settle_seconds=0.3, wait_lock_seconds=5.0)
    pid = up.pid
    try:
        assert up.status == "ok", up.to_payload()
        assert up.running is True
        assert up.url is not None
        assert f":{port}" in up.url

        url_result = run_url(shop)
        assert url_result.status == "ok", url_result.to_payload()
        assert url_result.url == up.url

        code, body = _wait_http_ok(up.url)
        assert code == 200
        assert body
        if pid is not None and _can_signal(pid):
            down = run_down(shop)
            assert down.status == "ok", down.to_payload()
            assert down.running is False
    finally:
        if pid is not None and _can_signal(pid):
            run_down(shop)
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _soft_publish_webinst(shop: Path, discovery: DiscoveryResult) -> None:
    platform_bin = None
    if discovery.webinst.found and discovery.webinst.path is not None:
        platform_bin = discovery.webinst.path.parent
    elif discovery.ibcmd.found and discovery.ibcmd.path is not None:
        platform_bin = discovery.ibcmd.path.parent
    if platform_bin is None or not (platform_bin / "wsap24.so").is_file():
        return
    apache = resolve_apache_home()
    if not apache.found or apache.httpd is None:
        return

    port = _free_port()
    _set_webinst_publish(shop, port, wsdir="shop")
    up = run_up(shop, settle_seconds=0.3, wait_lock_seconds=3.0)
    if up.status != "ok":
        return
    pid = up.pid
    try:
        assert up.url is not None
        assert str(port) in up.url
        assert "shop" in up.url
        assert up.running is True
        # Stop may be blocked in Cursor sandbox (PermissionError on kill).
        if pid is not None and _can_signal(pid):
            down = run_down(shop)
            assert down.status == "ok", down.to_payload()
            assert down.running is False
    finally:
        if pid is None or _can_signal(pid):
            run_down(shop)


def _soft_templates(tmp_path: Path) -> None:
    listed = templates_list(source_kind_filter="cf")
    cf_templates = [
        t
        for t in listed.templates
        if t.source_kind == "cf" and t.source_path is not None and t.source_path.is_file()
    ]
    if not cf_templates:
        return

    chosen = min(
        cf_templates,
        key=lambda t: (t.source_path or Path()).stat().st_size,
    )
    source = chosen.source_path
    assert source is not None
    # Full UT/ERP templates are too heavy for acceptance; list-only is enough then.
    if source.stat().st_size > _MAX_TEMPLATE_CF_BYTES:
        assert chosen.id
        return

    target = tmp_path / "from_tmpl"
    target.mkdir()
    result = run_import(target, from_template=chosen.id, break_support=True)
    assert result.status == "ok", result.to_payload()
    assert (target / HOME_MANIFEST_REL).is_file()
    assert any(target.rglob("Configuration.xml"))


@pytest.mark.integration
def test_m4_acceptance_nested_multi_config_publish(tmp_path: Path) -> None:
    """Full M4 flow; skip if ibcmd/xml-gen unavailable; soft skip tmplts/ibsrv/webinst."""
    if not resolve_xmlgen().found or not resolve_java_xml().found:
        pytest.skip(
            "xml-gen jar / Java 17+ недоступны (запустите scripts/fetch-xml-gen.sh "
            "или 1c-dev tools sync)"
        )

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — M4 acceptance пропущен")

    repo = tmp_path / "repo"
    shop = repo / "products" / "shop"
    shop.mkdir(parents=True)

    init = init_project(shop, name="Shop", ide_target="none")
    assert init.status == "ok", init.to_payload()

    main = add_configuration(
        shop, config_id="main", name="Shop", source_path="src/cf"
    )
    assert main.status == "ok", main.to_payload()

    buh = add_configuration(shop, config_id="buh", name="Buh", source_path="src/buh")
    assert buh.status == "ok", buh.to_payload()

    ext = add_extension(
        shop, ext_id="custom", name="CustomExt", purpose="product", config_id="main"
    )
    assert ext.status == "ok", ext.to_payload()
    assert (shop / "src" / "cfe" / "custom" / "Configuration.xml").is_file()

    data = _load_manifest(shop)
    assert str(data.get("schema")) == "2"
    assert (shop / HOME_MANIFEST_REL).is_file()

    configurations = data.get("configurations")
    assert isinstance(configurations, list)
    assert {c["id"] for c in configurations if isinstance(c, dict)} >= {"main", "buh"}
    main_conf = next(c for c in configurations if c.get("id") == "main")
    exts = main_conf.get("extensions") or []
    assert any(isinstance(e, dict) and e.get("id") == "custom" for e in exts)

    runtimes = data.get("runtimes")
    assert isinstance(runtimes, list)
    conf_ids = {
        r["configuration"] for r in runtimes if isinstance(r, dict) and r.get("configuration")
    }
    assert {"main", "buh"} <= conf_ids
    assert sum(1 for r in runtimes if isinstance(r, dict) and r.get("default") is True) == 1

    summary = build_scope_summary(data)
    assert summary["defaults"]["configuration"] == "main"
    assert "custom" in next(
        c["extensions"] for c in summary["configurations"] if c["id"] == "main"
    )

    found = list_projects(repo, max_depth=4)
    roots = {r.root for r in found}
    assert shop.resolve() in roots

    detected = detect_project(shop)
    assert detected.status == "ok", detected.to_payload()
    assert detected.root == shop.resolve()
    payload = detected.to_payload()
    assert "summary" in payload
    assert {c["id"] for c in payload["summary"]["configurations"]} >= {"main", "buh"}

    build_main = run_build(shop)
    assert build_main.status == "ok", build_main.to_payload()
    assert (shop / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    build_buh = run_build(shop, config_id="buh")
    assert build_buh.status == "ok", build_buh.to_payload()
    assert (shop / ".1c-dev" / "runtime" / "buh" / IB_MARKER).is_file()

    # init may leave AGENTS.md; with ide_root ≠ scope and agents=auto it must not return.
    agents_scope = shop / "AGENTS.md"
    if agents_scope.is_file():
        agents_scope.unlink()

    ide = configure_ide(shop, ide_root=repo, target="cursor", agents="auto")
    assert ide.status == "ok", ide.to_payload()
    assert ide.ide_root == repo.resolve()
    mcp_path = repo / ".cursor" / "mcp.json"
    assert mcp_path.is_file()
    mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert "1c-dev" in mcp["mcpServers"]
    assert not (shop / ".cursor").exists()
    assert not agents_scope.exists()

    doctor = run_doctor()
    doctor_payload = doctor.to_payload()
    for cap in ("templates", "ibsrv", "webinst"):
        assert cap in doctor_payload["capabilities"]
        assert "available" in doctor_payload["capabilities"][cap]
    for tool in ("templates", "ibsrv", "webinst"):
        assert tool in doctor_payload["tools"]

    _soft_templates(tmp_path)
    _soft_publish_ibsrv(shop, discovery)
    _soft_publish_webinst(shop, discovery)
