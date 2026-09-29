"""Tests for ibcmd --extension argv and extension list (ADR-023 / #88)."""

from __future__ import annotations

from pathlib import Path

from adapters.platform_ibcmd.client import (
    IbcmdRunResult,
    apply_config,
    check_config,
    export_xml,
    import_xml,
    list_extensions,
    load_cf,
    parse_extension_list,
    save_cf,
)
from adapters.platform_ibcmd.constants import IB_MARKER


def _ok_run(argv: list[str]) -> IbcmdRunResult:
    if "create" in argv:
        for arg in argv:
            if arg.startswith("--db-path="):
                db_path = Path(arg.split("=", 1)[1])
                db_path.mkdir(parents=True, exist_ok=True)
                (db_path / IB_MARKER).write_bytes(b"")
                break
    return IbcmdRunResult(returncode=0, stdout="ok", stderr="", argv=argv)


def test_import_xml_extension_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    source = tmp_path / "src"
    source.mkdir()
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    import_xml(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        source_dir=source,
        extension="CustomExt",
        run=run,
    )
    argv = captured[0]
    assert "--extension=CustomExt" in argv
    assert argv.index("--extension=CustomExt") < argv.index(str(source))
    assert argv[-1] == str(source)


def test_import_xml_without_extension(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    import_xml(
        ibcmd,
        db_path=tmp_path / "ib",
        data_path=tmp_path / "data",
        source_dir=tmp_path / "src",
        run=run,
    )
    assert not any(a.startswith("--extension=") for a in captured[0])


def test_apply_save_load_export_check_extension_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cf_path = tmp_path / "out.cfe"
    target = tmp_path / "out"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    apply_config(
        ibcmd, db_path=db_path, data_path=data_path, extension="E1", run=run
    )
    save_cf(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        extension="E1",
        run=run,
    )
    load_cf(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cf_path,
        extension="E1",
        run=run,
    )
    export_xml(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        target_dir=target,
        extension="E1",
        run=run,
    )
    check_config(
        ibcmd, db_path=db_path, data_path=data_path, extension="E1", run=run
    )

    assert all("--extension=E1" in a for a in captured)
    assert captured[1][:3] == [str(ibcmd), "config", "save"]
    assert "--db" in captured[1]


def test_list_extensions_argv(tmp_path: Path) -> None:
    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return IbcmdRunResult(
            returncode=0,
            stdout="Name\nCustomExt\nTests\n",
            stderr="",
            argv=argv,
        )

    result, items = list_extensions(
        ibcmd, db_path=db_path, data_path=data_path, run=run
    )
    assert result.returncode == 0
    assert captured[0][:3] == [str(ibcmd), "extension", "list"]
    assert f"--db-path={db_path}" in captured[0]
    assert [i.name for i in items] == ["CustomExt", "Tests"]


def test_parse_extension_list_skips_headers() -> None:
    stdout = "Name Version\nCustomExt 1.0\n-----------\nTests\n"
    items = parse_extension_list(stdout)
    assert [i.name for i in items] == ["CustomExt", "Tests"]


def test_load_cf_with_ibcmd_extension_argv(tmp_path: Path) -> None:
    from adapters.platform_ibcmd import load_cf_with_ibcmd

    ibcmd = tmp_path / "ibcmd"
    ibcmd.write_text("", encoding="utf-8")
    db_path = tmp_path / "ib"
    data_path = tmp_path / "data"
    cfe = tmp_path / "ext.cfe"
    cfe.write_bytes(b"CFE")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> IbcmdRunResult:
        captured.append(argv)
        return _ok_run(argv)

    steps = load_cf_with_ibcmd(
        ibcmd,
        db_path=db_path,
        data_path=data_path,
        cf_path=cfe,
        extension="CustomExt",
        run=run,
    )
    assert steps == ["create", "load:CustomExt", "apply:CustomExt"]
    assert any(
        "load" in a and "--extension=CustomExt" in a and str(cfe) in a
        for a in captured
    )
    assert any("apply" in a and "--extension=CustomExt" in a for a in captured)
