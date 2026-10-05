"""M5 acceptance: tools sync → build → test.run without manual YAXUNIT (#129)."""

from __future__ import annotations

import shutil
import urllib.error
from pathlib import Path
from typing import Any

import pytest
import yaml

from adapters.platform import discover_environment
from adapters.platform_ibcmd.constants import IB_MARKER
from adapters.test_yaxunit import RUNNER_EXTENSION_NAME
from core.build import run_build
from core.exit_codes import SUCCESS, TEST_FAILURE
from core.test import (
    discover_tests,
    list_tests,
    report_tests,
    run_one_test,
    run_tests,
)
from core.toolchain.cache import tools_cache_dir
from core.toolchain.fetchers.yaxunit import fetch_yaxunit
from core.toolchain.manifest import load_manifest
from core.toolchain.resolve import resolve_yaxunit_cfe

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "yaxunit_spike"


def _load_manifest(root: Path) -> dict[str, Any]:
    manifest = root / ".1c-dev" / "project.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _ensure_yaxunit_cfe() -> Path:
    """Return YAxUnit.cfe: cache / ONEC_YAXUNIT_CFE, else soft fetch (tools sync path)."""
    resolved = resolve_yaxunit_cfe()
    if resolved.found and resolved.path is not None:
        return resolved.path

    env_name = resolved.env_name or "ONEC_YAXUNIT_CFE"
    skip_msg = (
        f"YAxUnit.cfe не найден — выполните 1c-dev tools sync "
        f"или задайте {env_name}=/path/to/YAxUnit.cfe"
    )
    manifest = load_manifest()
    spec = manifest.get("yaxunit")
    if spec is None:
        pytest.skip(skip_msg)

    try:
        path, _diags = fetch_yaxunit(spec, tools_cache_dir(), quiet=True)
    except (OSError, urllib.error.URLError) as exc:
        pytest.skip(f"{skip_msg} ({exc})")

    if path is None or not path.is_file():
        # Re-resolve in case env/cache changed during fetch.
        resolved = resolve_yaxunit_cfe()
        if resolved.found and resolved.path is not None:
            return resolved.path
        pytest.skip(skip_msg)
    return path


@pytest.mark.integration
def test_m5_acceptance_tools_sync_build_test_run(tmp_path: Path) -> None:
    """Full M5 YAxUnit flow; skip without ibcmd / 1cv8 / yaxunit.cfe."""
    discovery = discover_environment()
    if not discovery.ibcmd.found or discovery.ibcmd.path is None:
        pytest.skip("ibcmd не найден — M5 acceptance пропущен")
    if not discovery.onecv8.found or discovery.onecv8.path is None:
        pytest.skip("1cv8 не найден — M5 acceptance пропущен")

    yaxunit_cfe = _ensure_yaxunit_cfe()
    assert yaxunit_cfe.is_file()

    project = tmp_path / "yaxunit_spike"
    shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns("run_yaxunit.py"))

    data = _load_manifest(project)
    assert str(data.get("schema")) == "2"
    configurations = data.get("configurations")
    assert isinstance(configurations, list) and configurations
    main = next(c for c in configurations if isinstance(c, dict) and c.get("id") == "main")
    extensions = main.get("extensions") or []
    assert any(isinstance(e, dict) and e.get("id") == "test_ext1" for e in extensions)
    assert any(isinstance(e, dict) and e.get("purpose") == "tests" for e in extensions)
    # Runner is not declared in project.yaml (ADR-029 §7a).
    assert all(
        not (
            isinstance(e, dict)
            and str(e.get("name") or "").upper() == RUNNER_EXTENSION_NAME
        )
        for e in extensions
    )
    tests = main.get("tests")
    assert isinstance(tests, list) and tests
    assert any(
        isinstance(s, dict) and s.get("id") == "unit" and s.get("runner") == "yaxunit"
        for s in tests
    )

    build = run_build(project)
    assert build.status == "ok", build.to_payload()
    assert (project / ".1c-dev" / "runtime" / "main" / IB_MARKER).is_file()

    # Core API = CLI/MCP contract (thin wrappers); exercise discover / list / run / report.
    discovered = discover_tests(project)
    assert discovered.status == "ok", discovered.to_payload()
    assert "unit" in discovered.suite_ids
    module_names = {m.get("name") for m in discovered.modules if isinstance(m, dict)}
    assert {"ОМ_Арифметика", "ОМ_Логика", "ОМ_Строки"} <= module_names

    listed_before = list_tests(project)
    assert listed_before.status == "ok", listed_before.to_payload()

    run_result = run_tests(project)
    payload = run_result.to_payload()
    assert run_result.status == "failed", payload
    assert run_result.exit_code == TEST_FAILURE, payload
    assert (run_result.failed or 0) + (run_result.error or 0) > 0, payload
    assert (run_result.passed or 0) > 0, payload

    ensure = run_result.runner_ensure
    assert isinstance(ensure, dict), payload
    assert ensure.get("status") == "ok", payload
    assert ensure.get("cfePath"), payload
    # Fresh IB after build → implicit ensure loads YAXUNIT from cache (no extension add).
    assert ensure.get("loaded") is True, payload

    report = report_tests(project)
    assert report.status == "failed", report.to_payload()
    assert report.exit_code == TEST_FAILURE, report.to_payload()
    assert report.tests, report.to_payload()

    listed_after = list_tests(project)
    assert listed_after.status == "ok", listed_after.to_payload()
    assert listed_after.source == "report", listed_after.to_payload()
    assert listed_after.tests, listed_after.to_payload()

    # runOne on a known-passing test (MCP test.runOne parity via core).
    one = run_one_test("ОМ_Строки.Конкатенация", project)
    assert one.status == "passed", one.to_payload()
    assert one.exit_code == SUCCESS, one.to_payload()
