"""Tests for platform templates discovery / *.mft (ADR-024 / #91)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from adapters.platform.templates import (
    discover_template_roots,
    parse_configuration_templates_locations,
)
from cli.main import app
from core.doctor import run_doctor
from core.exit_codes import PROJECT_ERROR, SUCCESS
from core.templates import (
    make_template_id,
    parse_mft_text,
    templates_get,
    templates_list,
    templates_roots,
)

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
    """Create a fake tmplts tree with one *.mft and source files."""
    tmplts = root / "tmplts"
    package = tmplts / "1c" / "demo" / "1_2_3_4"
    package.mkdir(parents=True)
    (package / "1cv8.mft").write_text(_SAMPLE_MFT, encoding="utf-8-sig")
    (package / "1Cv8.cf").write_bytes(b"cf")
    (package / "1Cv8.dt").write_bytes(b"dt")
    return tmplts


def test_parse_configuration_templates_locations() -> None:
    text = (
        "UseHWLicenses=1\n"
        "ConfigurationTemplatesLocation=/opt/tmplts\n"
        "ConfigurationTemplatesLocation=/extra/a;/extra/b\n"
    )
    locs = parse_configuration_templates_locations(text)
    assert [p.as_posix() for p in locs] == ["/opt/tmplts", "/extra/a", "/extra/b"]


def test_discover_template_roots_from_cfg(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    cfg = tmp_path / "1cestart.cfg"
    cfg.write_text(
        f"ConfigurationTemplatesLocation={tmplts.as_posix()}\n",
        encoding="utf-8",
    )
    empty_default = tmp_path / "missing-default"
    result = discover_template_roots(
        cfg_paths=[cfg],
        default_roots=[empty_default],
    )
    assert result.roots == [tmplts.resolve()]
    assert cfg.resolve() in result.cfg_paths


def test_discover_falls_back_to_default(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    missing_cfg = tmp_path / "no-such.cfg"
    result = discover_template_roots(
        cfg_paths=[missing_cfg],
        default_roots=[tmplts],
    )
    assert result.roots == [tmplts.resolve()]


def test_parse_mft_text_sections() -> None:
    manifest = parse_mft_text(_SAMPLE_MFT)
    assert manifest.vendor == 'Фирма "1С"'
    assert manifest.name == "ДемоКонфигурация"
    assert manifest.version == "1.2.3.4"
    assert manifest.app_version == "8.3"
    assert len(manifest.sections) == 2
    assert manifest.sections[0].source == "1Cv8.cf"
    assert manifest.sections[1].source == "1Cv8.dt"
    assert manifest.sections[0].catalog is not None


def test_templates_list_and_get(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    listed = templates_list(roots=[tmplts])
    assert listed.status == "ok"
    assert len(listed.templates) == 2
    kinds = {t.source_kind for t in listed.templates}
    assert kinds == {"cf", "dt"}
    cf_item = next(t for t in listed.templates if t.source_kind == "cf")
    assert cf_item.name == "ДемоКонфигурация"
    assert cf_item.source_path is not None
    assert cf_item.source_path.is_file()
    assert cf_item.id == make_template_id(cf_item.mft_path, cf_item.section)

    got = templates_get(cf_item.id, roots=[tmplts])
    assert got.status == "ok"
    assert got.template is not None
    assert got.template.id == cf_item.id
    assert got.template.source_kind == "cf"

    missing = templates_get("deadbeefdeadbeef", roots=[tmplts])
    assert missing.status == "error"


def test_templates_list_filters(tmp_path: Path) -> None:
    tmplts = _write_tmplts_tree(tmp_path)
    only_cf = templates_list(roots=[tmplts], source_kind_filter="cf")
    assert len(only_cf.templates) == 1
    assert only_cf.templates[0].source_kind == "cf"
    by_query = templates_list(roots=[tmplts], query="демобаза")
    assert len(by_query.templates) == 1
    assert by_query.templates[0].source_kind == "dt"


def test_templates_list_empty_roots(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    listed = templates_list(roots=[empty])
    assert listed.status == "ok"
    assert listed.templates == []


def test_templates_roots_gap(tmp_path: Path) -> None:
    result = templates_roots(
        cfg_paths=[tmp_path / "missing.cfg"],
        default_roots=[tmp_path / "no-tmplts"],
    )
    assert result.status == "ok"
    assert result.roots == []
    assert any(d.get("code") == "1CT002" for d in result.diagnostics)


def test_cli_templates_list_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tmplts = _write_tmplts_tree(tmp_path)

    def _list(**_kwargs: object) -> object:
        return templates_list(roots=[tmplts])

    monkeypatch.setattr("cli.templates.templates_list", _list)
    result = runner.invoke(app, ["templates", "list", "--output", "json"])
    assert result.exit_code == SUCCESS
    assert "ДемоКонфигурация" in result.stdout


def test_cli_templates_get_unknown() -> None:
    result = runner.invoke(
        app,
        ["templates", "get", "0000000000000000", "--output", "json"],
    )
    assert result.exit_code == PROJECT_ERROR


def test_doctor_templates_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    install = tmp_path / "8.3.27.1549"
    install.mkdir()
    for name in ("ibcmd", "1cv8"):
        binary = install / name
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)

    tmplts = _write_tmplts_tree(tmp_path)
    ok = run_doctor(
        search_roots=[tmp_path],
        template_cfg_paths=[tmp_path / "missing.cfg"],
        template_default_roots=[tmplts],
    )
    assert ok.tools["templates"]["found"] is True
    assert ok.capabilities["templates"]["available"] is True
    assert not any(d.get("code") == "1CD012" for d in ok.diagnostics)
    assert not any(g["capability"] == "templates" for g in ok.gaps)

    missing = run_doctor(
        search_roots=[tmp_path],
        template_cfg_paths=[tmp_path / "missing.cfg"],
        template_default_roots=[tmp_path / "no-tmplts"],
    )
    assert missing.tools["templates"]["found"] is False
    assert missing.capabilities["templates"]["available"] is False
    assert any(d.get("code") == "1CD012" for d in missing.diagnostics)
    assert missing.status == "ok"  # templates gap ≠ hard-fail
