"""Tests for environment doctor / platform discovery."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from typer.testing import CliRunner

from adapters.platform.discovery import discover_environment, version_from_path
from cli.main import app
from core.doctor import run_doctor
from core.exit_codes import ENV_UNAVAILABLE, SUCCESS
from core.metadata.ir import (
    CREATE_OBJECT_TYPES,
    M2_OBJECT_TYPES,
    UPDATE_OBJECT_TYPES,
)

runner = CliRunner()
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "doctor.schema.json"


def _make_install(root: Path, version: str, *, tools: tuple[str, ...] = ("ibcmd", "1cv8")) -> Path:
    """Create fake platform tree: root/<version>/{ibcmd,1cv8}."""
    install = root / version
    install.mkdir(parents=True)
    for name in tools:
        binary = install / name
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
    return install


def _clear_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")


def test_version_from_path() -> None:
    assert version_from_path(Path("/opt/1cv8/x86_64/8.3.27.1549/ibcmd")) == "8.3.27.1549"
    assert version_from_path(Path("/tmp/no-version/ibcmd")) is None


def test_discover_from_search_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    result = discover_environment(search_roots=[tmp_path])
    assert result.platform.found is True
    assert result.platform.version == "8.3.27.1549"
    assert result.ibcmd.found is True
    assert result.onecv8.found is True
    assert result.ibcmd.path is not None
    assert result.ibcmd.path.name == "ibcmd"


def test_discover_picks_newest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.25.1000")
    _make_install(tmp_path, "8.3.27.1549")
    result = discover_environment(search_roots=[tmp_path])
    assert result.platform.version == "8.3.27.1549"


def test_discover_ibcmd_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549", tools=("ibcmd",))
    result = discover_environment(search_roots=[tmp_path])
    assert result.ibcmd.found is True
    assert result.onecv8.found is False
    assert result.platform.found is True


def test_discover_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    result = discover_environment(search_roots=[tmp_path])
    assert result.platform.found is False
    assert result.ibcmd.found is False
    assert result.onecv8.found is False


def test_discover_via_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _make_install(tmp_path, "8.3.27.1549", tools=("ibcmd",))
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(install))
    result = discover_environment(search_roots=[empty])
    assert result.ibcmd.found is True
    assert result.platform.found is True
    assert result.platform.version == "8.3.27.1549"


def test_run_doctor_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    result = run_doctor(search_roots=[tmp_path])
    assert result.status == "ok"
    assert result.capabilities["build"]["available"] is True
    assert result.capabilities["check"]["available"] is True
    assert result.capabilities["project.import"]["available"] is True
    # metadata.create may be unavailable without java/xml-gen; platform ok ≠ no gaps
    assert not any(g["capability"] in {"build", "check", "project.import"} for g in result.gaps)
    assert not any(d.get("code") == "1CD002" for d in result.diagnostics)


def test_run_doctor_supported_write_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    result = run_doctor(search_roots=[tmp_path])
    payload = result.to_payload()
    create = payload["capabilities"]["metadata.create"]
    update = payload["capabilities"]["metadata.update"]
    delete = payload["capabilities"]["metadata.delete"]
    assert create["supportedTypes"] == sorted(CREATE_OBJECT_TYPES)
    assert update["supportedTypes"] == sorted(UPDATE_OBJECT_TYPES)
    assert delete["supportedTypes"] == sorted(M2_OBJECT_TYPES)
    assert "supportedTypes" not in payload["capabilities"]["build"]
    assert "supportedTypes" not in payload["capabilities"]["check"]
    assert "supportedTypes" not in payload["capabilities"]["project.import"]
    assert "supportedTypes" not in payload["capabilities"]["metadata.read"]
    # Types are advertised even when tools are missing (available may be false).
    assert "supportedTypes" in result.capabilities["metadata.create"]


def test_run_doctor_metadata_create_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_path(monkeypatch)
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.delenv("ONEC_XMLGEN_JAR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    _make_install(tmp_path, "8.3.27.1549")
    result = run_doctor(search_roots=[tmp_path])
    assert result.status == "ok"
    assert result.capabilities["metadata.create"]["available"] is False
    gap = next(g for g in result.gaps if g["capability"] == "metadata.create")
    assert "java" in gap["missing"] or "xml-gen" in gap["missing"]
    codes = {d.get("code") for d in result.diagnostics}
    assert "1CD004" in codes or "1CD005" in codes
    jar_diags = [d for d in result.diagnostics if d.get("code") in {"1CD005", "1CD006", "1CD007"}]
    assert jar_diags
    assert any(
        "doctor --fix" in (d.get("suggestion") or "") or "tools sync" in (d.get("suggestion") or "")
        for d in jar_diags
    )


def test_run_doctor_reports_all_toolchain_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_path(monkeypatch)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    for key in (
        "ONEC_XMLGEN_JAR",
        "ONEC_MDREADER_JAR",
        "ONEC_BSLLS_JAR",
        "ONEC_DOCS_FACADE_JAR",
    ):
        monkeypatch.delenv(key, raising=False)
    _make_install(tmp_path, "8.3.27.1549")
    result = run_doctor(search_roots=[tmp_path])
    for key in (
        "cli",
        "ibcmd",
        "1cv8",
        "java",
        "xml-gen",
        "md-reader",
        "bsl-language-server",
        "docs-facade",
    ):
        assert key in result.tools
        assert "found" in result.tools[key]
    codes = {d.get("code") for d in result.diagnostics}
    assert "1CD008" in codes  # docs-facade deferred
    docs_diag = next(d for d in result.diagnostics if d.get("code") == "1CD008")
    assert docs_diag["severity"] == "info"


def test_run_doctor_env_override_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    jar = tmp_path / "custom-xml-gen.jar"
    jar.write_bytes(b"pk\x03\x04")
    monkeypatch.setenv("ONEC_XMLGEN_JAR", str(jar))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    result = run_doctor(search_roots=[tmp_path])
    xmlgen = result.tools["xml-gen"]
    assert xmlgen["found"] is True
    assert xmlgen["source"] == "env"
    assert xmlgen["path"] == str(jar.resolve())


def test_run_doctor_bsl_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    jar = tmp_path / "bsl-language-server.jar"
    jar.write_bytes(b"pk\x03\x04")
    monkeypatch.setenv("ONEC_BSLLS_JAR", str(jar))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty-cache"))
    result = run_doctor(search_roots=[tmp_path])
    bsl = result.tools["bsl-language-server"]
    assert bsl["found"] is True
    assert bsl["source"] == "env"
    assert bsl["path"] == str(jar.resolve())
    assert not any(d.get("code") == "1CD007" for d in result.diagnostics)


def test_run_doctor_missing_ibcmd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    result = run_doctor(search_roots=[tmp_path])
    assert result.status == "error"
    assert result.capabilities["build"]["available"] is False
    assert any(g["capability"] == "build" for g in result.gaps)
    codes = {d.get("code") for d in result.diagnostics}
    assert "1CD001" in codes
    assert "1CD002" in codes
    assert "1CD003" in codes


def test_run_doctor_warning_without_1cv8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549", tools=("ibcmd",))
    result = run_doctor(search_roots=[tmp_path])
    assert result.status == "ok"
    warn = next(d for d in result.diagnostics if d.get("code") == "1CD003")
    assert warn["severity"] == "warning"


def test_doctor_payload_matches_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    payload = run_doctor(search_roots=[tmp_path]).to_payload()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    diagnostics = json.loads(
        (SCHEMA_PATH.parent / "diagnostics.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resources(
        [
            ("diagnostics.schema.json", Resource.from_contents(diagnostics)),
            (diagnostics["$id"], Resource.from_contents(diagnostics)),
        ]
    )
    jsonschema.Draft202012Validator(schema, registry=registry).validate(payload)


def test_cli_doctor_json_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_path(monkeypatch)
    monkeypatch.setattr(
        "cli.doctor.run_doctor",
        lambda: run_doctor(search_roots=[tmp_path]),
    )
    result = runner.invoke(app, ["--output", "json", "doctor"])
    assert result.exit_code == ENV_UNAVAILABLE
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["tools"]["ibcmd"]["found"] is False
    assert any(g["capability"] == "build" for g in payload["gaps"])


def test_cli_doctor_json_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    monkeypatch.setattr(
        "cli.doctor.run_doctor",
        lambda: run_doctor(search_roots=[tmp_path]),
    )
    result = runner.invoke(app, ["--output", "json", "doctor"])
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["platform"]["version"] == "8.3.27.1549"
    assert payload["capabilities"]["build"]["available"] is True


def test_cli_doctor_text_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    monkeypatch.setattr(
        "cli.doctor.run_doctor",
        lambda: run_doctor(search_roots=[tmp_path]),
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == SUCCESS
    assert "1C Dev Runtime" in result.stdout
    assert "8.3.27.1549" in result.stdout
    assert "build: available" in result.stdout
    assert "metadata.create:" in result.stdout
    assert "md-reader:" in result.stdout
    assert "bsl-language-server:" in result.stdout
    assert "docs-facade:" in result.stdout
    assert "cli:" in result.stdout
    expected_types = (
        "types: AccumulationRegister, Catalog, CommonModule, "
        "Document, Enum, InformationRegister"
    )
    assert expected_types in result.stdout


def test_cli_doctor_fix_runs_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.toolchain.result import ComponentResult, SyncResult

    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")
    called: list[bool] = []

    def fake_sync(**_kwargs: object) -> SyncResult:
        called.append(True)
        return SyncResult(
            status="ok",
            components=[
                ComponentResult(id="xml-gen", status="ok", path="/tmp/xml-gen.jar"),
                ComponentResult(id="md-reader", status="ok"),
                ComponentResult(id="bsl-language-server", status="ok"),
                ComponentResult(id="docs-facade", status="deferred"),
            ],
        )

    monkeypatch.setattr("cli.doctor.sync_tools", fake_sync)
    monkeypatch.setattr(
        "cli.doctor.run_doctor",
        lambda: run_doctor(search_roots=[tmp_path]),
    )
    result = runner.invoke(app, ["--output", "json", "doctor", "--fix"])
    assert result.exit_code == SUCCESS
    assert called == [True]
    payload = json.loads(result.stdout)
    assert payload["fix"]["status"] == "ok"
    assert payload["doctor"]["status"] == "ok"
    assert "xml-gen" in payload["doctor"]["tools"]


def test_cli_doctor_fix_sync_error_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from core.toolchain.result import ComponentResult, SyncResult

    _clear_path(monkeypatch)
    _make_install(tmp_path, "8.3.27.1549")

    def fake_sync(**_kwargs: object) -> SyncResult:
        return SyncResult(
            status="error",
            components=[ComponentResult(id="xml-gen", status="error")],
        )

    monkeypatch.setattr("cli.doctor.sync_tools", fake_sync)
    monkeypatch.setattr(
        "cli.doctor.run_doctor",
        lambda: run_doctor(search_roots=[tmp_path]),
    )
    result = runner.invoke(app, ["doctor", "--fix"])
    assert result.exit_code == ENV_UNAVAILABLE
    assert "Toolchain sync" in result.stdout
