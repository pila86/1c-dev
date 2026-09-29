"""Tests for configuration.import --from-template (ADR-024 / #92)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.constants import IB_MARKER
from cli.main import app
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.import_cf import run_import
from core.import_cf.constants import CODE_PROJECT, CODE_TEMPLATE_SOURCE
from core.import_cf.result import ImportResult
from core.project.constants import HOME_MANIFEST_REL
from core.templates import CODE_NOT_FOUND, templates_get, templates_list

runner = CliRunner()

_SAMPLE_MFT = """\ufeffVendor=Фирма "1С"
Name=ДемоКонфигурация
Version=1.2.3.4
AppVersion=8.3
[Config1]
Catalog=1С:Демо/Основная
Destination=1C\\Demo
Source=1Cv8.cf
[Config2]
Catalog=1С:Демо/Демобаза
Destination=1C\\DemoDB
Source=1Cv8.dt
"""


def _write_tmplts_tree(root: Path) -> Path:
    tmplts = root / "tmplts"
    package = tmplts / "1c" / "demo" / "1_2_3_4"
    package.mkdir(parents=True)
    (package / "1cv8.mft").write_text(_SAMPLE_MFT, encoding="utf-8-sig")
    (package / "1Cv8.cf").write_bytes(b"CF")
    (package / "1Cv8.dt").write_bytes(b"DT")
    return tmplts


def _fake_discovery(*, ibcmd: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
        webinst=ToolInfo(found=False, path=None),
    )


def _fake_import_fn(
    _ibcmd: Path,
    *,
    db_path: Path,
    data_path: Path,
    cf_path: Path,
    source_dir: Path,
    run: Any = None,
) -> list[str]:
    assert cf_path.is_file()
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
    db_path.mkdir(parents=True, exist_ok=True)
    (db_path / IB_MARKER).write_bytes(b"")
    return ["create", "load", "apply", "export"]


def test_run_import_from_template_cf(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    cf_item = next(t for t in listed.templates if t.source_kind == "cf")
    target = tmp_path / "imported"
    target.mkdir()
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_import(
        target,
        from_template=cf_item.id,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=_fake_import_fn,
        templates_get_fn=lambda tid: templates_get(tid, roots=[tmplts]),
    )
    assert result.status == "ok"
    assert result.from_path == cf_item.source_path.resolve()
    assert (target / HOME_MANIFEST_REL).is_file()
    assert (target / "src" / "main" / "Configuration.xml").is_file()


def test_run_import_from_template_rejects_dt(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    dt_item = next(t for t in listed.templates if t.source_kind == "dt")
    target = tmp_path / "imported"
    target.mkdir()

    result = run_import(
        target,
        from_template=dt_item.id,
        discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")),
        import_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no import")),
        templates_get_fn=lambda tid: templates_get(tid, roots=[tmplts]),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_TEMPLATE_SOURCE for d in result.diagnostics)
    assert not (target / HOME_MANIFEST_REL).exists()


def test_run_import_from_template_unknown(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    target = tmp_path / "imported"
    target.mkdir()
    result = run_import(
        target,
        from_template="deadbeefdeadbeef",
        templates_get_fn=lambda tid: templates_get(tid, roots=[tmplts]),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_NOT_FOUND for d in result.diagnostics)


def test_run_import_from_and_template_mutex(tmp_path: Path) -> None:
    result = run_import(
        tmp_path,
        from_path=tmp_path / "x.cf",
        from_template="abc",
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_run_import_requires_source(tmp_path: Path) -> None:
    result = run_import(tmp_path)
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_cli_configuration_import_from_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    cf_item = next(t for t in listed.templates if t.source_kind == "cf")
    monkeypatch.chdir(tmp_path)
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.import_cf.run.import_cf_with_ibcmd", _fake_import_fn)
    monkeypatch.setattr(
        "core.import_cf.run.templates_get",
        lambda tid, **_k: templates_get(tid, roots=[tmplts]),
    )

    result = runner.invoke(
        app,
        [
            "configuration",
            "import",
            "--from-template",
            cf_item.id,
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert (tmp_path / HOME_MANIFEST_REL).is_file()


def test_cli_from_template_dt_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    dt_item = next(t for t in listed.templates if t.source_kind == "dt")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "core.import_cf.run.templates_get",
        lambda tid, **_k: templates_get(tid, roots=[tmplts]),
    )
    result = runner.invoke(
        app,
        ["configuration", "import", "--from-template", dt_item.id, "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert any(d.get("code") == CODE_TEMPLATE_SOURCE for d in payload["diagnostics"])


def test_mcp_configuration_import_from_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from mcp_server import create_server

    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    cf_item = next(t for t in listed.templates if t.source_kind == "cf")
    target = tmp_path / "imported"
    target.mkdir()

    def fake_import(
        start: Path | None = None,
        *,
        from_path: Path | str | None = None,
        from_template: str | None = None,
        **_kwargs: Any,
    ) -> ImportResult:
        assert from_template == cf_item.id
        assert from_path is None
        return ImportResult(
            status="ok",
            root=start,
            from_path=cf_item.source_path,
            steps=["create", "load", "apply", "export"],
            created=[".1c-dev/project.yaml"],
        )

    monkeypatch.setattr("mcp_server.tools.run_import", fake_import)
    server = create_server()

    async def _run() -> dict[str, Any]:
        result = await server.call_tool(
            "configuration.import",
            {"path": str(target), "from_template": cf_item.id},
        )
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
            return result[1]
        raise AssertionError(f"Unexpected call_tool result: {result!r}")

    payload = asyncio.run(_run())
    assert payload["status"] == "ok"
    assert payload["steps"] == ["create", "load", "apply", "export"]
