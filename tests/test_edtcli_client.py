"""Unit tests: 1cedtcli export client (#155)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.edtcli import (
    CODE_EDTCLI_COLLISION,
    CODE_EDTCLI_EMPTY_EXPORT,
    CODE_EDTCLI_FAILED,
    CODE_EDTCLI_MISSING,
    CODE_EDTCLI_VERSION,
    EdtCliError,
    EdtCliInfo,
    EdtCliRunResult,
    export_configuration,
    is_edt_version_supported,
    prepare_export_dir,
    require_edtcli,
    version_tuple,
)


def test_version_tuple_and_supported() -> None:
    assert version_tuple("2026.2.2+21") == (2026, 2, 2, 21)
    assert version_tuple("2025.1") == (2025, 1)
    assert version_tuple(None) is None
    assert is_edt_version_supported("2025.1")
    assert is_edt_version_supported("2026.2.2+21")
    assert not is_edt_version_supported("2024.2.6+7")
    assert is_edt_version_supported(None)  # unknown → allow


def test_require_edtcli_missing() -> None:
    with pytest.raises(EdtCliError) as exc:
        require_edtcli(info=EdtCliInfo(found=False))
    assert exc.value.code == CODE_EDTCLI_MISSING


def test_require_edtcli_old_version(tmp_path: Path) -> None:
    binary = tmp_path / "1cedtcli"
    binary.write_text("", encoding="utf-8")
    with pytest.raises(EdtCliError) as exc:
        require_edtcli(
            info=EdtCliInfo(found=True, path=binary, version="2024.2.6+7"),
        )
    assert exc.value.code == CODE_EDTCLI_VERSION


def test_prepare_export_dir_recreates(tmp_path: Path) -> None:
    export_dir = tmp_path / "export" / "main"
    export_dir.mkdir(parents=True)
    stale = export_dir / "stale.xml"
    stale.write_text("x", encoding="utf-8")
    prepared = prepare_export_dir(export_dir)
    assert prepared == export_dir.resolve()
    assert prepared.is_dir()
    assert not stale.exists()


def test_export_configuration_ok(tmp_path: Path) -> None:
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    export_dir = tmp_path / "out"
    captured: list[list[str]] = []

    def run(argv: list[str]) -> EdtCliRunResult:
        captured.append(argv)
        out = Path(argv[argv.index("--configuration-files") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "Configuration.xml").write_text(
            '<?xml version="1.0"?>\n<MetaDataObject>\n'
            "<ChildObjects><Catalog>Products</Catalog></ChildObjects>\n"
            "</MetaDataObject>\n",
            encoding="utf-8",
        )
        return EdtCliRunResult(returncode=0, stdout="ok", stderr="", argv=argv)

    result = export_configuration(
        edtcli,
        project=project,
        configuration_files=export_dir,
        workspace=tmp_path / "ws",
        run=run,
    )
    assert result.returncode == 0
    assert len(captured) == 1
    assert captured[0][0] == str(edtcli)
    assert "-command" in captured[0]
    assert "export" in captured[0]
    assert (export_dir / "Configuration.xml").is_file()


def test_export_configuration_rc204(tmp_path: Path) -> None:
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()

    def run(argv: list[str]) -> EdtCliRunResult:
        return EdtCliRunResult(
            returncode=204,
            stdout="",
            stderr="уже существует",
            argv=argv,
        )

    with pytest.raises(EdtCliError) as exc:
        export_configuration(
            edtcli,
            project=project,
            configuration_files=tmp_path / "out",
            workspace=tmp_path / "ws",
            run=run,
        )
    assert exc.value.code == CODE_EDTCLI_COLLISION


def test_export_configuration_nonzero(tmp_path: Path) -> None:
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()

    def run(argv: list[str]) -> EdtCliRunResult:
        return EdtCliRunResult(returncode=200, stdout="", stderr="boom", argv=argv)

    with pytest.raises(EdtCliError) as exc:
        export_configuration(
            edtcli,
            project=project,
            configuration_files=tmp_path / "out",
            workspace=tmp_path / "ws",
            run=run,
        )
    assert exc.value.code == CODE_EDTCLI_FAILED


def test_export_configuration_empty_xml(tmp_path: Path) -> None:
    edtcli = tmp_path / "1cedtcli"
    edtcli.write_text("", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()

    def run(argv: list[str]) -> EdtCliRunResult:
        out = Path(argv[argv.index("--configuration-files") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "Configuration.xml").write_text(
            "<MetaDataObject/>\n",
            encoding="utf-8",
        )
        return EdtCliRunResult(returncode=0, stdout="", stderr="", argv=argv)

    with pytest.raises(EdtCliError) as exc:
        export_configuration(
            edtcli,
            project=project,
            configuration_files=tmp_path / "out",
            workspace=tmp_path / "ws",
            run=run,
        )
    assert exc.value.code == CODE_EDTCLI_EMPTY_EXPORT
