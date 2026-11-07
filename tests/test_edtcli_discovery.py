"""Unit tests for adapters.edtcli discovery (#149)."""

from __future__ import annotations

from pathlib import Path

from adapters.edtcli import discover_edtcli, version_from_edt_path


def test_version_from_edt_path() -> None:
    path = Path("/opt/1C/1CE/components/1c-edt-2026.2.2+21-x86_64/1cedtcli")
    assert version_from_edt_path(path) == "2026.2.2+21"
    assert version_from_edt_path(Path("/usr/bin/1cedtcli")) is None


def test_discover_override_missing(tmp_path: Path) -> None:
    info = discover_edtcli(
        env={"ONEC_EDTCLI": str(tmp_path / "missing")},
        search_roots=[],
    )
    assert info.found is False
    assert info.path is None


def test_discover_override_file(tmp_path: Path) -> None:
    root = tmp_path / "1c-edt-2025.2.1+3-x86_64"
    root.mkdir()
    binary = root / "1cedtcli"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)

    info = discover_edtcli(env={"ONEC_EDTCLI": str(binary)}, search_roots=[])
    assert info.found is True
    assert info.path == binary.resolve()
    assert info.version == "2025.2.1+3"


def test_discover_newest_under_roots(tmp_path: Path) -> None:
    components = tmp_path / "components"
    old = components / "1c-edt-2024.2.6+7-x86_64"
    new = components / "1c-edt-2026.2.2+21-x86_64"
    for folder in (old, new):
        folder.mkdir(parents=True)
        binary = folder / "1cedtcli"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)

    info = discover_edtcli(env={}, search_roots=[components])
    assert info.found is True
    assert info.version == "2026.2.2+21"
    assert info.path == (new / "1cedtcli").resolve()


def test_edt_spike_fixture_layout() -> None:
    root = Path(__file__).resolve().parent / "fixtures" / "edt_spike"
    assert (root / ".project").is_file()
    assert (root / "DT-INF" / "PROJECT.PMF").is_file()
    assert (root / "src" / "Configuration" / "Configuration.mdo").is_file()
    products = root / "src" / "Catalogs" / "Products" / "Products.mdo"
    assert products.is_file()
    project_xml = (root / ".project").read_text(encoding="utf-8")
    assert "EdtSpike" in project_xml
    assert "com._1c.g5.v8.dt.core.V8ConfigurationNature" in project_xml
    cfg = (root / "src" / "Configuration" / "Configuration.mdo").read_text(encoding="utf-8")
    assert "<catalogs>Catalog.Products</catalogs>" in cfg
    assert "Товары" in products.read_text(encoding="utf-8")
    manifest = (root / ".1c-dev" / "project.yaml").read_text(encoding="utf-8")
    assert "format: edt" in manifest
