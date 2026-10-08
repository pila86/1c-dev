"""Unit tests for Designer /CheckModules adapter (ADR-030)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.platform_1cv8.check_modules import (
    CheckModulesError,
    ProcessRunResult,
    build_check_modules_argv,
    check_modules,
    normalize_modes,
    parse_check_modules_out,
)
from adapters.platform_ibcmd.constants import CODE_CHECK_FAILED


def test_normalize_modes_default() -> None:
    assert normalize_modes(None) == ["Server"]
    assert normalize_modes([]) == ["Server"]


def test_normalize_modes_dedupe_and_strip() -> None:
    assert normalize_modes(["-Server", "ThinClient", "Server"]) == [
        "Server",
        "ThinClient",
    ]


def test_normalize_modes_empty_raises() -> None:
    with pytest.raises(CheckModulesError) as exc:
        normalize_modes(["  ", "-"])
    assert exc.value.code == CODE_CHECK_FAILED


def test_build_check_modules_argv(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    ib = tmp_path / "ib"
    out = tmp_path / "out.log"
    argv = build_check_modules_argv(
        onecv8,
        ib_path=ib,
        out_log=out,
        modes=["Server", "ThinClient"],
    )
    assert argv[0] == str(onecv8)
    assert argv[1] == "DESIGNER"
    assert f"/F{ib.resolve()}" in argv
    assert "/CheckModules" in argv
    assert "-Server" in argv
    assert "-ThinClient" in argv
    assert "/Out" in argv
    assert str(out.resolve()) in argv


def test_parse_success_ru() -> None:
    text = "\ufeffСинтаксических ошибок не обнаружено!\n"
    assert parse_check_modules_out(text) == []


def test_parse_syntax_error() -> None:
    text = (
        "\ufeff{ОбщийМодуль.BrokenServer.Модуль(2,8)}: Ожидается выражение\n"
        "    А =<<?>> ; (Проверка: Сервер)\n"
    )
    diags = parse_check_modules_out(text)
    assert len(diags) == 1
    d = diags[0]
    assert d["object"] == "CommonModule.BrokenServer"
    assert d["module"] == "Module"
    assert d["line"] == 2
    assert d["column"] == 8
    assert d["code"] == CODE_CHECK_FAILED
    assert d["source"] == "platform"
    assert "Ожидается выражение" in d["message"]


def test_parse_unclosed() -> None:
    text = (
        "{ОбщийМодуль.BrokenServer.Модуль(3,1)}: "
        "Ожидается ключевое слово 'КонецПроцедуры' ('EndProcedure') "
        "(Проверка: Сервер)\n"
    )
    diags = parse_check_modules_out(text)
    assert len(diags) == 1
    assert diags[0]["line"] == 3
    assert diags[0]["column"] == 1


def test_parse_multiple_and_english() -> None:
    text = (
        "{CommonModule.A.Module(1,1)}: err one\n"
        "{ОбщийМодуль.B.Модуль(4,2)}: err two\n"
    )
    diags = parse_check_modules_out(text)
    assert len(diags) == 2
    assert diags[0]["object"] == "CommonModule.A"
    assert diags[1]["object"] == "CommonModule.B"


def test_check_modules_ok(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()
    out = tmp_path / "out.log"

    def run(argv: list[str], timeout: float) -> ProcessRunResult:
        out.write_text("Синтаксических ошибок не обнаружено!\n", encoding="utf-8-sig")
        return ProcessRunResult(returncode=0, argv=argv)

    check_modules(onecv8, ib_path=ib, out_log=out, run=run)


def test_check_modules_failure_parses_out(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()
    out = tmp_path / "out.log"

    def run(argv: list[str], timeout: float) -> ProcessRunResult:
        out.write_text(
            "{ОбщийМодуль.BrokenServer.Модуль(2,8)}: Ожидается выражение\n",
            encoding="utf-8-sig",
        )
        return ProcessRunResult(returncode=101, argv=argv)

    with pytest.raises(CheckModulesError) as exc:
        check_modules(onecv8, ib_path=ib, out_log=out, run=run)
    assert len(exc.value.diagnostics) == 1
    assert exc.value.diagnostics[0]["line"] == 2
