"""Tests for ibcmd import from .cf (ADR-014)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.platform_ibcmd import IbcmdError, import_cf_with_ibcmd, load_cf_with_ibcmd
from adapters.platform_ibcmd.client import IbcmdRunResult, export_xml, load_cf
from adapters.platform_ibcmd.constants import CODE_IBCMD_FAILED, IB_MARKER
from core.project import init_project


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


def test_load_cf_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    load_cf(ibcmd, db_path=db_path, data_path=data_path, cf_path=cf_path, run=run)
    assert len(captured) == 1
    argv = captured[0]
    assert argv[:4] == [str(ibcmd), "infobase", "config", "load"]
    assert f"--db-path={db_path}" in argv
    assert f"--data={data_path}" in argv
    assert argv[-1] == str(cf_path)


def test_export_xml_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    target = tmp_path / "src"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    export_xml(ibcmd, db_path=db_path, data_path=data_path, target_dir=target, run=run)
    assert target.is_dir()
    assert len(captured) == 1
    argv = captured[0]
    assert argv[:4] == [str(ibcmd), "infobase", "config", "export"]
    assert argv[-1] == str(target)


def test_load_cf_with_ibcmd_happy_path(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    steps = load_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        run=run,
    )
    assert steps == ["create", "load", "apply"]
    assert (db_path / IB_MARKER).is_file()
    assert any("create" in a for a in captured)
    assert any("load" in a for a in captured)
    assert any("apply" in a for a in captured)
    assert not any("export" in a for a in captured)


def test_load_cf_with_ibcmd_skips_create_when_ib_exists(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    db_path.mkdir()
    (db_path / IB_MARKER).write_bytes(b"")
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")

    steps = load_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        run=_ok_run,
    )
    assert steps == ["load", "apply"]


def test_import_cf_happy_path(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    source_dir = tmp_path / "src"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    steps = import_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        source_dir=source_dir,
        run=run,
    )
    assert steps == ["create", "load", "apply", "export"]
    assert (db_path / IB_MARKER).is_file()
    assert (source_dir / "Configuration.xml").is_file()

    assert any("create" in a for a in captured)
    load_argv = next(a for a in captured if "load" in a)
    assert load_argv[:4] == [str(ibcmd), "infobase", "config", "load"]
    export_argv = next(a for a in captured if "export" in a)
    assert export_argv[:4] == [str(ibcmd), "infobase", "config", "export"]
    assert any("apply" in a for a in captured)


def test_import_cf_skips_create_when_ib_exists(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    db_path.mkdir()
    (db_path / IB_MARKER).write_bytes(b"")
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    source_dir = tmp_path / "src"

    steps = import_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        source_dir=source_dir,
        run=_ok_run,
    )
    assert steps == ["load", "apply", "export"]


def test_import_cf_ibcmd_failure(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cf_path = tmp_path / "configuration.cf"
    cf_path.write_bytes(b"CF")
    source_dir = tmp_path / "src"

    with pytest.raises(IbcmdError) as exc_info:
        import_cf_with_ibcmd(
            ibcmd,
            db_path=db_path,
            data_path=data_path,
            cf_path=cf_path,
            source_dir=source_dir,
            run=_fail_run,
        )
    err = exc_info.value
    assert err.code == CODE_IBCMD_FAILED
    assert err.diagnostics
    assert err.diagnostics[0].get("source") == "platform"
    assert err.diagnostics[0].get("code") == CODE_IBCMD_FAILED


@pytest.mark.integration
def test_integration_import_cf_roundtrip(tmp_path: Path) -> None:
    """build → .cf → import_cf_with_ibcmd; skip if platform unavailable."""
    from adapters.platform import discover_environment
    from core.build import run_build

    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — integration import_cf пропущен")

    project = tmp_path / "shop"
    project.mkdir()
    assert init_project(project, project_type="configuration", name="Shop").status == "ok"

    cf_path = tmp_path / "configuration.cf"
    build_result = run_build(project, artifact="cf")
    assert build_result.status == "ok", build_result.to_payload()
    assert "save" in build_result.steps
    # run_build writes under project/build/out/; copy path from result
    built_cf = project / (build_result.artifact or "build/out/configuration.cf")
    assert built_cf.is_file()
    # Keep .cf outside project tree (do not rely on build/out layout for import)
    cf_path.write_bytes(built_cf.read_bytes())

    ibcmd = discovery.ibcmd.path
    import_root = tmp_path / "imported"
    import_root.mkdir()
    import_db = import_root / "ib"
    import_data = import_root / "ibcmd-data"
    import_src = import_root / "src"

    import_steps = import_cf_with_ibcmd(
        ibcmd,
        db_path=import_db,
        data_path=import_data,
        cf_path=cf_path,
        source_dir=import_src,
    )
    assert import_steps == ["create", "load", "apply", "export"]
    assert (import_db / IB_MARKER).is_file()
    assert (import_src / "Configuration.xml").is_file()
