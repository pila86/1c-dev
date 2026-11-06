"""Unit tests: EdtSourceAdapter detect / inspect (#152)."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.source.edt import (
    CODE_LAYOUT_NOT_EDT,
    CODE_PATH_NOT_EDT_ROOT,
    V8_CONFIGURATION_NATURE,
    EdtSourceAdapter,
    detect_edt,
    inspect_edt,
    is_edt_project_root,
    validate_edt_source_dir,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def test_edt_spike_is_project_root() -> None:
    assert is_edt_project_root(FIXTURE)
    detected = detect_edt(FIXTURE)
    assert detected.is_edt is True
    assert detected.kind == "root"
    assert detected.has_configuration_mdo is True
    assert detected.has_v8_nature is True
    assert detected.project_name == "EdtSpike"
    assert detected.code is None


def test_inspect_edt_spike() -> None:
    info = inspect_edt(FIXTURE)
    assert info.format == "edt"
    assert info.is_edt is True
    assert info.project_name == "EdtSpike"
    assert info.has_configuration_mdo is True
    assert info.has_v8_nature is True
    payload = info.to_dict()
    assert payload["projectName"] == "EdtSpike"
    assert payload["isEdt"] is True


def test_adapter_detect_inspect() -> None:
    adapter = EdtSourceAdapter()
    assert adapter.detect(FIXTURE).is_edt is True
    assert adapter.inspect(FIXTURE).project_name == "EdtSpike"
    assert adapter.validate(FIXTURE).is_edt is True


def test_detect_src_subdirectory_is_not_root() -> None:
    src = FIXTURE / "src"
    detected = detect_edt(src)
    assert detected.is_edt is False
    assert detected.kind == "src_like"
    assert detected.code == CODE_PATH_NOT_EDT_ROOT
    assert detected.suggestion is not None


def test_detect_empty_dir_not_edt(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    detected = validate_edt_source_dir(empty)
    assert detected.is_edt is False
    assert detected.code == CODE_LAYOUT_NOT_EDT
    assert V8_CONFIGURATION_NATURE.split(".")[-1] in (detected.message or "")


def test_detect_nature_only_without_mdo(tmp_path: Path) -> None:
    root = tmp_path / "edt"
    root.mkdir()
    (root / ".project").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<projectDescription>\n"
        "  <name>NatureOnly</name>\n"
        "  <natures>\n"
        f"    <nature>{V8_CONFIGURATION_NATURE}</nature>\n"
        "  </natures>\n"
        "</projectDescription>\n",
        encoding="utf-8",
    )
    assert is_edt_project_root(root)
    assert detect_edt(root).project_name == "NatureOnly"


def test_detect_mdo_only_without_project(tmp_path: Path) -> None:
    root = tmp_path / "edt"
    mdo = root / "src" / "Configuration" / "Configuration.mdo"
    mdo.parent.mkdir(parents=True)
    mdo.write_text("<mdclass:Configuration/>\n", encoding="utf-8")
    assert is_edt_project_root(root)
    assert detect_edt(root).has_configuration_mdo is True
    assert detect_edt(root).project_name is None


@pytest.mark.integration
def test_adapter_read_list_on_fixture() -> None:
    from adapters.source.mdclasses.resolve import resolve_jar, resolve_java

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(
            "md-reader jar / Java 21+ недоступны (запустите scripts/fetch-md-reader.sh)"
        )

    adapter = EdtSourceAdapter()
    payload = adapter.read("list", FIXTURE)
    assert payload["status"] == "ok"
    qnames = {obj["qname"] for obj in payload["objects"]}
    assert "Catalog.Products" in qnames
