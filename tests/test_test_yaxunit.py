"""Unit tests for adapters.test_yaxunit (ADR-029 / #122)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.platform import discover_environment
from adapters.test_yaxunit import (
    CODE_ENV,
    CODE_FILTER,
    CODE_IB_MISSING,
    CODE_NO_REPORT,
    CODE_ONECV8_MISSING,
    CODE_TIMEOUT,
    ProcessRunResult,
    YaxunitConfigError,
    YaxunitError,
    build_enterprise_run_argv,
    build_run_config,
    parse_junit,
    prepare_filter_extensions,
    read_yaxunit_exit_code,
    run_unit_tests,
    validate_test_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yaxunit_junit"
SAMPLE_JUNIT = FIXTURES / "sample.xml"
EMPTY_JUNIT = FIXTURES / "empty.xml"


def test_prepare_filter_extensions_excludes_yaxunit() -> None:
    assert prepare_filter_extensions(["Tests1", "YAXUNIT", "Tests2", "yaxunit"]) == [
        "Tests1",
        "Tests2",
    ]


def test_prepare_filter_extensions_rejects_empty() -> None:
    with pytest.raises(YaxunitConfigError) as exc:
        prepare_filter_extensions(["YAXUNIT"])
    assert exc.value.code == CODE_FILTER


def test_validate_test_path() -> None:
    assert validate_test_path("ОМ_Арифметика.Сложение") == "ОМ_Арифметика.Сложение"
    assert (
        validate_test_path("ОМ_Арифметика.Сложение.Сервер")
        == "ОМ_Арифметика.Сложение.Сервер"
    )
    with pytest.raises(YaxunitConfigError):
        validate_test_path("OnlyModule")
    with pytest.raises(YaxunitConfigError):
        validate_test_path("a.b.c.d")


def test_build_run_config_paths_absolute(tmp_path: Path) -> None:
    report = tmp_path / "out" / "junit.xml"
    exit_code = tmp_path / "out" / "exit-code.txt"
    log = tmp_path / "out" / "yaxunit.log"
    cfg = build_run_config(
        report_path=report,
        exit_code_path=exit_code,
        log_path=log,
        extensions=["Tests1", "YAXUNIT"],
        tests=["ОМ_Арифметика.Сложение"],
    )
    assert cfg["reportFormat"] == "jUnit"
    assert cfg["closeAfterTests"] is True
    assert cfg["showReport"] is False
    assert cfg["filter"]["extensions"] == ["Tests1"]
    assert cfg["filter"]["tests"] == ["ОМ_Арифметика.Сложение"]
    assert Path(cfg["reportPath"]).is_absolute()
    assert Path(cfg["exitCode"]).is_absolute()
    assert Path(cfg["logging"]["file"]).is_absolute()


def test_parse_junit_sample() -> None:
    result = parse_junit(SAMPLE_JUNIT, details_limit=120)
    assert result.total == 7
    assert result.passed == 4
    assert result.failed == 1
    assert result.error == 1
    assert result.skipped == 1
    assert result.status == "failed"

    by_name = {t.name: t for t in result.tests}
    failed = by_name["ОМ_Арифметика.Деление.Сервер"]
    assert failed.status == "failed"
    assert failed.extension == "Tests1"
    assert failed.module == "ОМ_Арифметика"
    assert failed.test_set == "Арифметика"
    assert failed.context == "Сервер"
    assert "2,5" in failed.message
    assert len(failed.details) <= 120 + len("\n…[truncated]")

    error = by_name["ОМ_Арифметика.ДелениеНаНоль.Сервер"]
    assert error.status == "error"
    assert "Деление на 0" in error.message

    skipped = by_name["ОМ_Арифметика.Пропущенный.Сервер"]
    assert skipped.status == "skipped"

    passed = by_name["ОМ_Строки.Длина.Сервер"]
    assert passed.status == "passed"
    assert passed.extension == "Tests2"

    payload = result.to_dict()
    assert payload["durationSec"] >= 0
    assert payload["failed"] == 1
    assert payload["error"] == 1


def test_parse_junit_empty() -> None:
    result = parse_junit(EMPTY_JUNIT)
    assert result.total == 0
    assert result.status == "empty"
    assert dict(result.properties).get("ТестовыйДвижок") == "YAXUNIT"


def test_read_yaxunit_exit_code_bom(tmp_path: Path) -> None:
    path = tmp_path / "exit-code.txt"
    path.write_bytes(b"\xef\xbb\xbf1\n")
    assert read_yaxunit_exit_code(path) == 1


def test_build_enterprise_run_argv(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.log"
    argv = build_enterprise_run_argv(
        onecv8,
        ib_path=ib,
        config_path=cfg,
        out_log=out,
        use_xvfb=False,
    )
    assert argv[0] == str(onecv8)
    assert argv[1] == "ENTERPRISE"
    assert argv[2] == f"/F{ib.resolve()}"
    assert "/DisableStartupDialogs" in argv
    assert f"/CRunUnitTests={cfg.resolve()}" in argv


def test_run_unit_tests_mocked(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()
    work = tmp_path / "work"
    sample = SAMPLE_JUNIT.read_bytes()

    def fake_run(argv: list[str], timeout: float) -> ProcessRunResult:
        assert timeout > 0
        assert any(a.startswith("/CRunUnitTests=") for a in argv)
        cfg_arg = next(a for a in argv if a.startswith("/CRunUnitTests="))
        cfg_path = Path(cfg_arg.split("=", 1)[1])
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["filter"]["extensions"] == ["Tests1"]
        report = Path(cfg["reportPath"])
        report.write_bytes(sample)
        Path(cfg["exitCode"]).write_bytes(b"\xef\xbb\xbf1\n")
        return ProcessRunResult(returncode=0, argv=argv, timed_out=False)

    result = run_unit_tests(
        onecv8,
        ib_path=ib,
        work_dir=work,
        extensions=["Tests1", "YAXUNIT"],
        use_xvfb=False,
        run=fake_run,
    )
    assert result.status == "failed"
    assert result.total == 7
    assert result.yaxunit_exit_code == 1
    assert result.process_exit_code == 0
    assert result.argv


def test_run_unit_tests_missing_onecv8(tmp_path: Path) -> None:
    with pytest.raises(YaxunitError) as exc:
        run_unit_tests(
            tmp_path / "missing-1cv8",
            ib_path=tmp_path / "ib",
            work_dir=tmp_path / "work",
            extensions=["Tests1"],
            use_xvfb=False,
        )
    assert exc.value.code == CODE_ONECV8_MISSING
    assert exc.value.diagnostics


def test_run_unit_tests_missing_ib(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    with pytest.raises(YaxunitError) as exc:
        run_unit_tests(
            onecv8,
            ib_path=tmp_path / "no-ib",
            work_dir=tmp_path / "work",
            extensions=["Tests1"],
            use_xvfb=False,
        )
    assert exc.value.code == CODE_IB_MISSING


def test_run_unit_tests_timeout(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()

    def fake_run(argv: list[str], timeout: float) -> ProcessRunResult:
        return ProcessRunResult(returncode=124, argv=argv, timed_out=True)

    with pytest.raises(YaxunitError) as exc:
        run_unit_tests(
            onecv8,
            ib_path=ib,
            work_dir=tmp_path / "work",
            extensions=["Tests1"],
            use_xvfb=False,
            run=fake_run,
        )
    assert exc.value.code == CODE_TIMEOUT


def test_run_unit_tests_no_report(tmp_path: Path) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()

    def fake_run(argv: list[str], timeout: float) -> ProcessRunResult:
        return ProcessRunResult(returncode=0, argv=argv, timed_out=False)

    with pytest.raises(YaxunitError) as exc:
        run_unit_tests(
            onecv8,
            ib_path=ib,
            work_dir=tmp_path / "work",
            extensions=["Tests1"],
            use_xvfb=False,
            run=fake_run,
        )
    assert exc.value.code == CODE_NO_REPORT


def test_run_unit_tests_env_no_display(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    ib = tmp_path / "ib"
    ib.mkdir()
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        "adapters.test_yaxunit.client.shutil.which",
        lambda name: None,
    )
    with pytest.raises(YaxunitError) as exc:
        run_unit_tests(
            onecv8,
            ib_path=ib,
            work_dir=tmp_path / "work",
            extensions=["Tests1"],
            use_xvfb=None,
        )
    assert exc.value.code == CODE_ENV


@pytest.mark.integration
def test_run_unit_tests_integration_skip_without_platform() -> None:
    """Real 1cv8 + YaXUnit IB is out of scope for #122 unit slice."""
    env = discover_environment()
    if not env.onecv8.found or env.onecv8.path is None:
        pytest.skip("1cv8 не найден — integration RunUnitTests пропущен")
    pytest.skip(
        "YaXUnit fixture/ИБ не подключены в #122 — полный E2E в #129; "
        f"1cv8={env.onecv8.path}"
    )
