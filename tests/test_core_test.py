"""Unit tests for core.test (ADR-029 / #123)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from adapters.platform.discovery import DiscoveryResult, PlatformInfo, ToolInfo
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.test_yaxunit import TestCaseResult, TestRunResult, YaxunitError
from core.exit_codes import (
    CHECK_FAILURE,
    ENV_UNAVAILABLE,
    PROJECT_ERROR,
    SUCCESS,
    TEST_FAILURE,
)
from core.project.load import load_manifest
from core.test import (
    CODE_IB_MISSING,
    CODE_NO_SUITES,
    CODE_ONECV8_MISSING,
    CODE_RUNNER_UNSUPPORTED,
    CODE_SUITE_UNKNOWN,
    LAST_RESULT_REL,
    discover_tests,
    list_tests,
    report_tests,
    run_one_test,
    run_tests,
)
from core.test.discover import module_has_executable_scenarios
from tests.helpers_project import bootstrap_configuration_project


def _fake_discovery(*, onecv8: Path | None) -> DiscoveryResult:
    return DiscoveryResult(
        platform=PlatformInfo(found=True, version="8.3.25.1560", path=Path("/opt/1cv8")),
        ibcmd=ToolInfo(found=False, path=None),
        onecv8=ToolInfo(found=onecv8 is not None, path=onecv8),
        onecv8c=ToolInfo(found=False, path=None),
        ibsrv=ToolInfo(found=False, path=None),
        webinst=ToolInfo(found=False, path=None),
    )


def _ensure_ib(target: Path) -> Path:
    ib_dir = target / ".1c-dev" / "runtime" / "main"
    ib_dir.mkdir(parents=True, exist_ok=True)
    (ib_dir / IB_MARKER).write_bytes(b"")
    return ib_dir


def _write_test_module(ext_root: Path, module: str, *, with_export: bool = True) -> Path:
    mod_dir = ext_root / "CommonModules" / module / "Ext"
    mod_dir.mkdir(parents=True, exist_ok=True)
    if with_export:
        body = (
            "Процедура ИсполняемыеСценарии() Экспорт\n"
            '\tЮТТесты.ДобавитьТестовыйНабор("Demo").ДобавитьТест("Ok");\n'
            "КонецПроцедуры\n"
        )
    else:
        body = "Процедура НеТест() Экспорт\nКонецПроцедуры\n"
    path = mod_dir / "Module.bsl"
    path.write_text(body, encoding="utf-8")
    return path


def _patch_manifest_with_tests(
    target: Path,
    *,
    suites: list[dict[str, Any]] | None = None,
    extra_extensions: list[dict[str, Any]] | None = None,
) -> None:
    manifest = target / ".1c-dev" / "project.yaml"
    data, diags = load_manifest(manifest)
    assert data is not None, diags
    conf = data["configurations"][0]
    assert isinstance(conf, dict)
    extensions: list[dict[str, Any]] = [
        {
            "id": "yaxunit",
            "name": "YAXUNIT",
            "purpose": "tests",
            "source": {"format": "xml", "path": "src/cfe/yaxunit"},
        },
        {
            "id": "test_ext1",
            "name": "Tests1",
            "purpose": "tests",
            "source": {"format": "xml", "path": "src/cfe/test_ext1"},
        },
    ]
    if extra_extensions:
        extensions.extend(extra_extensions)
    conf["extensions"] = extensions
    conf["tests"] = suites or [
        {"id": "unit", "runner": "yaxunit", "extensions": ["test_ext1"]}
    ]
    manifest.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _bootstrap_test_project(tmp_path: Path) -> Path:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    _patch_manifest_with_tests(target)
    ext = target / "src" / "cfe" / "test_ext1"
    _write_test_module(ext, "ОМ_Арифметика", with_export=True)
    _write_test_module(ext, "ОМ_Служебный", with_export=False)
    (target / "src" / "cfe" / "yaxunit").mkdir(parents=True, exist_ok=True)
    return target


def _ok_run_result(*, total: int = 2, failed: int = 0, error: int = 0) -> TestRunResult:
    passed = total - failed - error
    cases = []
    for i in range(passed):
        cases.append(
            TestCaseResult(
                name=f"ОМ_Арифметика.T{i}.Сервер",
                test=f"T{i}",
                module="ОМ_Арифметика",
                extension="Tests1",
                test_set="Demo",
                context="Сервер",
                status="passed",
                duration_sec=0.01,
            )
        )
    for i in range(failed):
        cases.append(
            TestCaseResult(
                name=f"ОМ_Арифметика.F{i}.Сервер",
                test=f"F{i}",
                module="ОМ_Арифметика",
                extension="Tests1",
                test_set="Demo",
                context="Сервер",
                status="failed",
                duration_sec=0.01,
                message="fail",
            )
        )
    for i in range(error):
        cases.append(
            TestCaseResult(
                name=f"ОМ_Арифметика.E{i}.Сервер",
                test=f"E{i}",
                module="ОМ_Арифметика",
                extension="Tests1",
                test_set="Demo",
                context="Сервер",
                status="error",
                duration_sec=0.01,
                message="err",
            )
        )
    status: Any
    if total == 0:
        status = "empty"
    elif failed or error:
        status = "failed"
    else:
        status = "passed"
    return TestRunResult(
        status=status,
        passed=passed,
        failed=failed,
        error=error,
        skipped=0,
        total=total,
        duration_sec=0.05,
        tests=tuple(cases),
        report_path=Path("/tmp/junit.xml"),
        process_exit_code=0,
        yaxunit_exit_code=1 if failed or error else 0,
    )


def test_module_has_executable_scenarios() -> None:
    assert module_has_executable_scenarios(
        "Процедура ИсполняемыеСценарии() Экспорт\nКонецПроцедуры\n"
    )
    assert module_has_executable_scenarios(
        "Функция ИсполняемыеСценарии() Экспорт\nВозврат Неопределено;\nКонецФункции\n"
    )
    assert not module_has_executable_scenarios(
        "Процедура ИсполняемыеСценарии()\nКонецПроцедуры\n"
    )


def test_discover_tests_static(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    result = discover_tests(target)
    assert result.status == "ok"
    assert result.exit_code == SUCCESS
    assert result.suite_ids == ["unit"]
    assert len(result.suites) == 1
    names = {m["name"] for m in result.modules}
    assert names == {"ОМ_Арифметика"}
    assert all(m["extension"] == "Tests1" for m in result.modules)


def test_discover_no_suites(tmp_path: Path) -> None:
    target = tmp_path / "shop"
    target.mkdir()
    assert bootstrap_configuration_project(target, name="Shop").status == "ok"
    result = discover_tests(target)
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR
    assert any(d.get("code") == CODE_NO_SUITES for d in result.diagnostics)


def test_discover_unknown_suite(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    result = discover_tests(target, suite_id="ghost")
    assert result.status == "failed"
    assert any(d.get("code") == CODE_SUITE_UNKNOWN for d in result.diagnostics)


def test_list_best_effort_without_report(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    result = list_tests(target)
    assert result.status == "ok"
    assert result.source == "discover"
    assert result.incomplete is True
    assert result.tests
    assert result.tests[0]["status"] == "unknown"


def test_run_tests_mock_passed(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(onecv8_path: Path, **kwargs: Any) -> TestRunResult:
        captured["onecv8"] = onecv8_path
        captured["extensions"] = list(kwargs["extensions"])
        captured["ib_path"] = kwargs["ib_path"]
        captured["tests"] = kwargs.get("tests")
        return _ok_run_result(total=2)

    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=fake_run,
    )
    assert result.status == "passed"
    assert result.exit_code == SUCCESS
    assert result.total == 2
    assert result.passed == 2
    assert captured["extensions"] == ["Tests1"]
    assert captured["tests"] is None
    assert (target / LAST_RESULT_REL).is_file()
    payload = json.loads((target / LAST_RESULT_REL).read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["exitCode"] == SUCCESS


def test_run_tests_mock_failure_exit_5(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(total=2, failed=1),
    )
    assert result.status == "failed"
    assert result.exit_code == TEST_FAILURE
    assert result.failed == 1


def test_run_tests_empty_is_check_failure(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(total=0),
    )
    assert result.status == "empty"
    assert result.exit_code == CHECK_FAILURE


def test_run_tests_missing_ib(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(),
    )
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR
    assert any(d.get("code") == CODE_IB_MISSING for d in result.diagnostics)
    assert any("build" in (d.get("suggestion") or "").lower() for d in result.diagnostics)


def test_run_tests_missing_onecv8(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=None),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(),
    )
    assert result.status == "failed"
    assert result.exit_code == ENV_UNAVAILABLE
    assert any(d.get("code") == CODE_ONECV8_MISSING for d in result.diagnostics)


def test_run_tests_vanessa_unsupported(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _patch_manifest_with_tests(
        target,
        suites=[{"id": "bdd", "runner": "vanessa", "extensions": ["test_ext1"]}],
    )
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(),
    )
    assert result.status == "failed"
    assert any(d.get("code") == CODE_RUNNER_UNSUPPORTED for d in result.diagnostics)


def test_run_multi_suite_union_extensions(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _patch_manifest_with_tests(
        target,
        suites=[
            {"id": "unit", "runner": "yaxunit", "extensions": ["test_ext1"]},
            {"id": "unit2", "runner": "yaxunit", "extensions": ["test_ext2"]},
        ],
        extra_extensions=[
            {
                "id": "test_ext2",
                "name": "Tests2",
                "purpose": "tests",
                "source": {"format": "xml", "path": "src/cfe/test_ext2"},
            }
        ],
    )
    _write_test_module(target / "src" / "cfe" / "test_ext2", "ОМ_Строки")
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(_path: Path, **kwargs: Any) -> TestRunResult:
        captured["extensions"] = list(kwargs["extensions"])
        return _ok_run_result(total=1)

    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=fake_run,
    )
    assert result.status == "passed"
    assert set(result.suite_ids) == {"unit", "unit2"}
    assert captured["extensions"] == ["Tests1", "Tests2"]


def test_run_one_passes_filter_tests(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(_path: Path, **kwargs: Any) -> TestRunResult:
        captured["tests"] = list(kwargs.get("tests") or [])
        captured["extensions"] = list(kwargs["extensions"])
        return _ok_run_result(total=1)

    result = run_one_test(
        "ОМ_Арифметика.Сложение.Сервер",
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=fake_run,
    )
    assert result.status == "passed"
    assert captured["tests"] == ["ОМ_Арифметика.Сложение.Сервер"]
    assert captured["extensions"] == ["Tests1"]


def test_run_one_invalid_path(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    result = run_one_test("OnlyModule", target)
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR


def test_run_one_ambiguous_module_requires_suite(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _patch_manifest_with_tests(
        target,
        suites=[
            {"id": "unit", "runner": "yaxunit", "extensions": ["test_ext1"]},
            {"id": "unit2", "runner": "yaxunit", "extensions": ["test_ext2"]},
        ],
        extra_extensions=[
            {
                "id": "test_ext2",
                "name": "Tests2",
                "purpose": "tests",
                "source": {"format": "xml", "path": "src/cfe/test_ext2"},
            }
        ],
    )
    _write_test_module(target / "src" / "cfe" / "test_ext2", "ОМ_Арифметика")
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    result = run_one_test(
        "ОМ_Арифметика.Сложение",
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(total=1),
    )
    assert result.status == "failed"
    assert any("--suite" in (d.get("suggestion") or "") for d in result.diagnostics)

    ok = run_one_test(
        "ОМ_Арифметика.Сложение",
        target,
        suite_id="unit",
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(total=1),
    )
    assert ok.status == "passed"


def test_report_and_list_from_last_run(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")
    run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=lambda *a, **k: _ok_run_result(total=2, failed=1),
    )
    report = report_tests(target)
    assert report.status == "failed"
    assert report.exit_code == TEST_FAILURE
    assert report.total == 2
    assert report.tests

    listed = list_tests(target)
    assert listed.source == "report"
    assert listed.incomplete is False
    assert listed.total == 2


def test_report_missing(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    result = report_tests(target)
    assert result.status == "failed"
    assert result.exit_code == PROJECT_ERROR


def test_adapter_error_mapped(tmp_path: Path) -> None:
    target = _bootstrap_test_project(tmp_path)
    _ensure_ib(target)
    onecv8 = tmp_path / "1cv8"
    onecv8.write_text("", encoding="utf-8")

    def boom(*_a: Any, **_k: Any) -> TestRunResult:
        raise YaxunitError("таймаут", code="1CT004")

    result = run_tests(
        target,
        discover=lambda: _fake_discovery(onecv8=onecv8),
        run_unit_tests_fn=boom,
    )
    assert result.status == "failed"
    assert any(d.get("code") == "1CT004" for d in result.diagnostics)
