"""Unit tests for toolchain cache / tools sync / uninstall (#48)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.diagnostics import info
from core.toolchain.cache import cache_root, tools_cache_dir
from core.toolchain.manifest import ComponentSpec, ToolchainManifest, load_manifest
from core.toolchain.result import ComponentResult
from core.toolchain.sync import sync_tools
from core.toolchain.uninstall import clean_tools_cache, uninstall_tools


def test_cache_root_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    root = cache_root(platform="linux")
    assert root == tmp_path / "xdg" / "1c-dev"
    assert tools_cache_dir(platform="linux") == root / "tools"


def test_cache_root_win32(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    root = cache_root(platform="win32")
    assert root == local / "1c-dev"
    assert tools_cache_dir(platform="win32") == root / "tools"


def test_load_manifest_from_repo() -> None:
    manifest = load_manifest()
    ids = {c.id for c in manifest.components}
    assert "xml-gen" in ids
    assert "md-reader" in ids
    assert "bsl-language-server" in ids
    docs = manifest.get("docs-facade")
    assert docs is not None
    assert docs.deferred is True


def _fake_manifest() -> ToolchainManifest:
    return ToolchainManifest(
        version=1,
        components=(
            ComponentSpec(
                id="xml-gen",
                artifact="xml-gen.jar",
                pin="abc123456789",
                source={"type": "git"},
                min_java=17,
                env="ONEC_XMLGEN_JAR",
            ),
            ComponentSpec(
                id="md-reader",
                artifact="md-reader.jar",
                pin="mdclasses-0.20.0",
                source={"type": "local-build"},
                min_java=21,
                env="ONEC_MDREADER_JAR",
            ),
            ComponentSpec(
                id="bsl-language-server",
                artifact="bsl-language-server.jar",
                pin="1.0.6",
                source={"type": "github-release"},
                min_java=21,
                env="ONEC_BSLLS_JAR",
            ),
            ComponentSpec(
                id="docs-facade",
                artifact="docs-facade.jar",
                pin="deferred",
                source={"type": "deferred"},
                status="deferred",
                env="ONEC_DOCS_FACADE_JAR",
            ),
        ),
    )


def test_sync_tools_with_mocked_fetchers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    seen: list[str] = []

    def fake_xml(
        spec: ComponentSpec,
        tools_dir: Path,
        *,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[Path, list]:
        del env, kwargs
        path = tools_dir / spec.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"xml")
        return path, []

    def fake_md(
        spec: ComponentSpec,
        tools_dir: Path,
        *,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[Path, list]:
        del env, kwargs
        path = tools_dir / spec.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"md")
        return path, []

    def fake_bsl(
        spec: ComponentSpec,
        tools_dir: Path,
        *,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[Path, list]:
        del env, kwargs
        path = tools_dir / spec.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"bsl")
        return path, []

    monkeypatch.setattr("core.toolchain.sync.fetch_xml_gen", fake_xml)
    monkeypatch.setattr("core.toolchain.sync.fetch_md_reader", fake_md)
    monkeypatch.setattr("core.toolchain.sync.fetch_bsl_language_server", fake_bsl)

    result = sync_tools(manifest=_fake_manifest(), progress=seen.append, quiet=False)
    assert result.status == "ok"
    by_id = {c.id: c for c in result.components}
    assert by_id["xml-gen"].status == "ok"
    assert by_id["md-reader"].status == "ok"
    assert by_id["bsl-language-server"].status == "ok"
    assert by_id["docs-facade"].status == "deferred"
    assert any(d.get("code") == "1CT030" for d in result.diagnostics)
    assert seen[0] == "Toolchain sync…"
    assert any("✓ xml-gen" in m for m in seen)
    assert any("docs-facade: deferred" in m for m in seen)

    # idempotent second run
    result2 = sync_tools(manifest=_fake_manifest())
    assert result2.status == "ok"


def test_sync_soft_fail_bsl_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def ok_jar(
        spec: ComponentSpec,
        tools_dir: Path,
        *,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[Path, list]:
        del env, kwargs
        path = tools_dir / spec.artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path, []

    def fail_bsl(
        spec: ComponentSpec,
        tools_dir: Path,
        *,
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> tuple[None, list]:
        del spec, tools_dir, env, kwargs
        return None, [info("bsl fail", code="1CT020", source="toolchain")]

    monkeypatch.setattr("core.toolchain.sync.fetch_xml_gen", ok_jar)
    monkeypatch.setattr("core.toolchain.sync.fetch_md_reader", ok_jar)
    monkeypatch.setattr("core.toolchain.sync.fetch_bsl_language_server", fail_bsl)

    result = sync_tools(manifest=_fake_manifest())
    assert result.status == "degraded"
    assert any(c.id == "bsl-language-server" and c.status == "warning" for c in result.components)


def test_clean_tools_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    root = cache_root(platform="linux")
    tools = root / "tools"
    tools.mkdir(parents=True)
    (tools / "xml-gen.jar").write_bytes(b"x")

    result = clean_tools_cache(platform="linux")
    assert result.status == "ok"
    assert result.cache_removed is True
    assert result.package_uninstalled is None
    assert not root.exists()

    # idempotent
    result2 = clean_tools_cache(platform="linux")
    assert result2.status == "ok"


def test_uninstall_keep_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    root = cache_root(platform="linux")
    root.mkdir(parents=True)

    called: list[Any] = []

    def boom() -> tuple[bool, list]:
        called.append(True)
        return True, []

    monkeypatch.setattr("core.toolchain.uninstall.uninstall_uv_package", boom)
    result = uninstall_tools(keep_package=True, platform="linux")
    assert result.package_uninstalled is None
    assert called == []
    assert not root.exists()


def test_uninstall_calls_uv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    root = cache_root(platform="linux")
    root.mkdir(parents=True)

    monkeypatch.setattr(
        "core.toolchain.uninstall._find_uv",
        lambda: "/usr/bin/uv",
    )
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ""
    proc.stderr = ""
    monkeypatch.setattr(
        "core.toolchain.uninstall.subprocess.run",
        lambda *a, **k: proc,
    )

    result = uninstall_tools(keep_package=False, platform="linux")
    assert result.status == "ok"
    assert result.cache_removed is True
    assert result.package_uninstalled is True


def test_cli_tools_sync_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    def fake_sync(**kwargs: Any) -> Any:
        del kwargs
        from core.toolchain.result import SyncResult

        return SyncResult(
            status="ok",
            components=[
                ComponentResult(id="xml-gen", status="ok", path="/tmp/xml-gen.jar"),
                ComponentResult(id="docs-facade", status="deferred"),
            ],
            diagnostics=[],
        )

    monkeypatch.setattr("cli.tools.sync_tools", fake_sync)
    runner = CliRunner()
    result = runner.invoke(app, ["tools", "sync", "--output", "json"])
    assert result.exit_code == 0
    assert '"status": "ok"' in result.stdout
    assert "xml-gen" in result.stdout


def test_cli_tools_sync_text_progress(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    captured: dict[str, Any] = {}

    def fake_sync(**kwargs: Any) -> Any:
        captured.update(kwargs)
        progress = kwargs.get("progress")
        if progress is not None:
            progress("Toolchain sync…")
            progress("→ xml-gen: cache hit")
            progress("✓ xml-gen: ok")
        from core.toolchain.result import SyncResult

        return SyncResult(
            status="ok",
            components=[ComponentResult(id="xml-gen", status="ok", path="/tmp/x.jar")],
            diagnostics=[],
        )

    monkeypatch.setattr("cli.tools.sync_tools", fake_sync)
    runner = CliRunner()
    result = runner.invoke(app, ["tools", "sync"])
    assert result.exit_code == 0
    assert captured.get("quiet") is False
    assert captured.get("progress") is not None
    assert "Toolchain sync…" in result.stderr
    assert "→ xml-gen: cache hit" in result.stderr
    assert "Status: ok" in result.stdout


def test_cli_tools_clean_requires_yes() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["tools", "clean", "--output", "json"])
    assert result.exit_code != 0
    assert "1CT045" in result.stdout


def test_cli_uninstall_requires_yes() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["uninstall", "--output", "json"])
    assert result.exit_code != 0
    assert "1CT045" in result.stdout


def test_gradlew_cmd_win32(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.toolchain.fetchers import gradlew_cmd

    bat = tmp_path / "gradlew.bat"
    bat.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr("core.toolchain.fetchers.sys.platform", "win32")
    assert gradlew_cmd(tmp_path) == [str(bat)]


def test_gradlew_cmd_unix_via_sh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from core.toolchain.fetchers import gradlew_cmd

    script = tmp_path / "gradlew"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)  # no +x — wheel/checkout case
    monkeypatch.setattr("core.toolchain.fetchers.sys.platform", "linux")
    assert gradlew_cmd(tmp_path) == ["sh", str(script)]
