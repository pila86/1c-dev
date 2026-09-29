"""Tests for configuration.import / runtime.load (ADR-015 / ADR-028, #47)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.client import IbcmdRunResult
from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, IB_MARKER
from cli.main import app
from core.exit_codes import BUILD_FAILURE, ENV_UNAVAILABLE, PROJECT_ERROR, SUCCESS
from core.import_cf import run_import, run_runtime_load
from core.import_cf.constants import (
    CODE_CF_MISSING,
    CODE_DIRTY_SOURCE,
    CODE_EXPORT_MISSING,
    CODE_IBCMD_MISSING,
    CODE_PROJECT,
)
from core.project.constants import HOME_MANIFEST_REL
from core.project.load import load_manifest
from tests.helpers_project import bootstrap_configuration_project

runner = CliRunner()


def _fake_discovery(*, ibcmd: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=ibcmd is not None, path=ibcmd),
        onecv8=ToolInfo(found=False, path=None),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
    )


def _ok_run(argv: list[str]) -> IbcmdRunResult:
    if "create" in argv:
        db_path = None
        for arg in argv:
            if arg.startswith("--db-path="):
                db_path = Path(arg.split("=", 1)[1])
        if db_path is not None:
            db_path.mkdir(parents=True, exist_ok=True)
            (db_path / IB_MARKER).write_bytes(b"")
    if "export" in argv:
        target = Path(argv[-1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def _fail_run(argv: list[str]) -> IbcmdRunResult:
    return IbcmdRunResult(
        returncode=1,
        stdout="",
        stderr="simulated ibcmd failure",
        argv=argv,
    )


def test_run_import_cf_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no.cf"
    result = run_import(
        tmp_path,
        from_path=missing,
        discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_CF_MISSING for d in result.diagnostics)


def test_run_import_dirty_without_force(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    cfg = target / "src" / "cf" / "Configuration.xml"
    original = cfg.read_bytes()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")

    result = run_import(
        target,
        from_path=cf_path,
        force=False,
        discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")),
        import_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call")),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_DIRTY_SOURCE for d in result.diagnostics)
    assert cfg.read_bytes() == original


def test_run_import_ensure_manifest(tmp_path: Path) -> None:
    target = tmp_path / "imported"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok", result.to_payload()
    assert (target / HOME_MANIFEST_REL).is_file()
    assert ".1c-dev/project.yaml" in result.created
    assert (target / "src" / "main" / "Configuration.xml").is_file()
    assert not (target / "AGENTS.md").exists()
    assert result.steps == ["create", "load", "apply", "export"]
    payload = result.to_payload()
    assert payload["sourcePath"] == "src/main"
    assert payload["from"] == str(cf_path.resolve())
    data, _ = load_manifest(target / HOME_MANIFEST_REL)
    assert data is not None
    assert data["configurations"] == [
        {
            "id": "main",
            "type": "configuration",
            "source": {"format": "xml", "path": "src/main"},
            "default": True,
        }
    ]
    assert data["runtimes"][0]["id"] == "main"
    assert data["runtimes"][0]["path"] == ".1c-dev/runtime/main"


def test_run_import_after_empty_init(tmp_path: Path) -> None:
    from core.project import init_project

    target = tmp_path / "shop"
    target.mkdir()
    assert init_project(target, name="Shop", ide_target="none").status == "ok"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok", result.to_payload()
    data, _ = load_manifest(target / HOME_MANIFEST_REL)
    assert data is not None
    assert len(data["configurations"]) == 1
    assert data["configurations"][0]["source"]["path"] == "src/main"
    assert (target / "src" / "main" / "Configuration.xml").is_file()
    assert (target / "AGENTS.md").is_file()  # from init, not from import


def test_run_import_force_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    cfg = target / "src" / "cf" / "Configuration.xml"
    cfg.write_text("OLD", encoding="utf-8")
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        (source_dir / "Configuration.xml").write_text("NEW", encoding="utf-8")
        return ["load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        force=True,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "ok"
    assert cfg.read_text(encoding="utf-8") == "NEW"


def test_run_import_missing_ibcmd(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=None),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IBCMD_MISSING for d in result.diagnostics)
    assert (target / HOME_MANIFEST_REL).is_file()


def test_run_import_ibcmd_failure(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_fail_run,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_IBCMD_FAILED for d in result.diagnostics)


def test_run_import_export_missing_config(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def import_fn(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        return ["create", "load", "apply", "export"]

    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        import_fn=import_fn,
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_EXPORT_MISSING for d in result.diagnostics)


def test_run_import_happy_mock(tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_import(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    assert result.steps == ["create", "load", "apply", "export"]
    assert (target / "src" / "main" / "Configuration.xml").is_file()


def test_run_runtime_load_requires_manifest(tmp_path: Path) -> None:
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    result = run_runtime_load(
        tmp_path,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=Path("/fake/ibcmd")),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_PROJECT for d in result.diagnostics)


def test_run_runtime_load_happy_mock(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    result = run_runtime_load(
        target,
        from_path=cf_path,
        discover=lambda: _fake_discovery(ibcmd=ibcmd),
        run=_ok_run,
    )
    assert result.status == "ok"
    assert result.steps == ["create", "load", "apply"]
    assert (target / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()
    assert "export" not in result.steps


def test_cli_configuration_import(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    def fake_import(
        _ibcmd: Path,
        *,
        db_path: Path,
        data_path: Path,
        cf_path: Path,
        source_dir: Path,
        run: Any = None,
    ) -> list[str]:
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "Configuration.xml").write_text("<MetaDataObject/>", encoding="utf-8")
        db_path.mkdir(parents=True, exist_ok=True)
        (db_path / IB_MARKER).write_bytes(b"")
        return ["create", "load", "apply", "export"]

    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.import_cf.run.import_cf_with_ibcmd", fake_import)

    result = runner.invoke(
        app,
        ["configuration", "import", "--from", str(cf_path), "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert (tmp_path / HOME_MANIFEST_REL).is_file()


def test_cli_configuration_import_dirty_exit(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    assert bootstrap_configuration_project(tmp_path, name="Shop").status == "ok"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    result = runner.invoke(
        app,
        ["configuration", "import", "--from", str(cf_path), "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert any(d.get("code") == CODE_DIRTY_SOURCE for d in payload["diagnostics"])


def test_cli_runtime_load(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    assert bootstrap_configuration_project(tmp_path, name="Shop").status == "ok"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )
    monkeypatch.setattr("core.import_cf.run.load_cf_with_ibcmd", lambda *a, **k: ["load", "apply"])

    result = runner.invoke(
        app,
        ["runtime", "load", "--from", str(cf_path), "--output", "json"],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["steps"] == ["load", "apply"]


def test_cli_configuration_import_missing_cf_exit(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["configuration", "import", "--from", str(tmp_path / "missing.cf"), "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR
    payload = json.loads(result.output)
    assert any(d.get("code") == CODE_CF_MISSING for d in payload["diagnostics"])


def test_cli_configuration_import_ibcmd_missing_exit(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=None),
    )
    result = runner.invoke(
        app,
        ["configuration", "import", "--from", str(cf_path), "--output", "json"],
    )
    assert result.exit_code == ENV_UNAVAILABLE


def test_cli_configuration_import_ibcmd_fail_exit(tmp_path: Path, monkeypatch: Any) -> None:
    from adapters.platform_ibcmd import IbcmdError

    monkeypatch.chdir(tmp_path)
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "core.import_cf.run.discover_environment",
        lambda: _fake_discovery(ibcmd=ibcmd),
    )

    def boom(*_a: Any, **_k: Any) -> list[str]:
        raise IbcmdError(
            "boom",
            code=CODE_IBCMD_FAILED,
            diagnostics=[
                {
                    "severity": "error",
                    "code": CODE_IBCMD_FAILED,
                    "message": "boom",
                    "source": "platform",
                }
            ],
        )

    monkeypatch.setattr("core.import_cf.run.import_cf_with_ibcmd", boom)
    result = runner.invoke(
        app,
        ["configuration", "import", "--from", str(cf_path), "--output", "json"],
    )
    assert result.exit_code == BUILD_FAILURE


@pytest.mark.integration
def test_integration_configuration_import_roundtrip(tmp_path: Path) -> None:
    """build --artifact cf → configuration.import; skip if platform unavailable."""
    from adapters.platform import discover_environment
    from core.build import run_build

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — integration configuration.import пропущен")

    project = tmp_path / "shop"
    project.mkdir()
    assert bootstrap_configuration_project(project, name="Shop").status == "ok"

    build_result = run_build(project, artifact="cf")
    assert build_result.status == "ok", build_result.to_payload()
    built_cf = project / (build_result.artifact or "build/out/configuration.cf")
    assert built_cf.is_file()
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(built_cf.read_bytes())

    import_root = tmp_path / "imported"
    import_root.mkdir()
    result = run_import(import_root, from_path=cf_path)
    assert result.status == "ok", result.to_payload()
    assert "export" in result.steps
    assert (import_root / "src" / "main" / "Configuration.xml").is_file()
    assert (import_root / HOME_MANIFEST_REL).is_file()
    assert not (import_root / "AGENTS.md").exists()
