"""Unit tests for module UUID index / XmlObjectIdResolver (#139)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters.debug_http import (
    CODE_MODULE_UNRESOLVED,
    PROPERTY_ID_APPLICATION_MODULE,
    PROPERTY_ID_COMMON_MODULE,
    DebugHttpError,
    SourceRoot,
    StubObjectIdResolver,
    XmlObjectIdResolver,
    build_modules_index,
    load_or_build_index,
    modules_cache_path,
    reload_metadata,
    scan_source_root,
    source_roots_from_configuration,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "debug_http" / "modules"
MAIN = FIXTURES / "main"
EXT = FIXTURES / "ext"

SPIKE_OBJECT_ID = "b7e2c4a1-8f3d-4a6e-9c1b-2d5e8f0a3b6c"
SPIKE_CONFIG_ID = "d4e5f6a7-b8c9-4d0e-1f2a-3b4c5d6e7f80"
EXT_DEMO_ID = "11111111-2222-3333-4444-555555555555"
EXT_ONLY_ID = "66666666-7777-8888-9999-aaaaaaaaaaaa"


def _roots() -> list[SourceRoot]:
    return [
        SourceRoot(path=MAIN, extension_name=""),
        SourceRoot(path=EXT, extension_name="DemoExt"),
    ]


def test_scan_common_and_application_module() -> None:
    entries = scan_source_root(MAIN)
    by_type = {(e.module_type, e.module_name): e for e in entries}
    common = by_type[("CommonModule", "ОтладкаДемо")]
    assert common.object_id == SPIKE_OBJECT_ID
    assert common.property_id == PROPERTY_ID_COMMON_MODULE
    app = by_type[("ManagedApplicationModule", "DebugSpike")]
    assert app.object_id == SPIKE_CONFIG_ID
    assert app.property_id == PROPERTY_ID_APPLICATION_MODULE


def test_xml_resolver_main_and_app_aliases() -> None:
    index = build_modules_index(_roots())
    resolver = XmlObjectIdResolver(index)

    ref = resolver.resolve("ОтладкаДемо", "CommonModule")
    assert ref.object_id == SPIKE_OBJECT_ID
    assert ref.property_id == PROPERTY_ID_COMMON_MODULE
    assert ref.extension_name == ""

    app = resolver.resolve("DebugSpike", "ManagedApplicationModule")
    assert app.object_id == SPIKE_CONFIG_ID
    assert app.property_id == PROPERTY_ID_APPLICATION_MODULE

    app2 = resolver.resolve("ManagedApplicationModule", "ApplicationModule")
    assert app2.object_id == SPIKE_CONFIG_ID


def test_extension_requires_extension_name() -> None:
    resolver = XmlObjectIdResolver(build_modules_index(_roots()))

    with pytest.raises(DebugHttpError) as exc:
        resolver.resolve("ТолькоРасширение", "CommonModule")
    assert exc.value.code == CODE_MODULE_UNRESOLVED
    assert "extensionName" in str(exc.value.diagnostics[0].get("suggestion") or "")

    ref = resolver.resolve(
        "ТолькоРасширение", "CommonModule", extension_name="DemoExt"
    )
    assert ref.object_id == EXT_ONLY_ID
    assert ref.extension_name == "DemoExt"


def test_same_name_main_vs_extension() -> None:
    """Пустой extensionName → основная conf; для расширения — явно DemoExt."""
    resolver = XmlObjectIdResolver(build_modules_index(_roots()))

    main = resolver.resolve("ОтладкаДемо", "CommonModule")
    assert main.object_id == SPIKE_OBJECT_ID
    assert main.extension_name == ""

    ext = resolver.resolve(
        "ОтладкаДемо", "CommonModule", extension_name="DemoExt"
    )
    assert ext.object_id == EXT_DEMO_ID
    assert ext.extension_name == "DemoExt"


def test_cache_mtime_invalidate(tmp_path: Path) -> None:
    scope = tmp_path / "proj"
    scope.mkdir()
    roots = [SourceRoot(path=MAIN, extension_name="")]
    cache = modules_cache_path(scope)

    index1 = load_or_build_index(scope, roots)
    assert cache.is_file()
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert any(m["moduleName"] == "ОтладкаДемо" for m in data["modules"])

    # Second load hits cache (same fingerprint)
    index2 = load_or_build_index(scope, roots)
    assert index2.built_at == index1.built_at

    # Force reload updates builtAt
    index3 = reload_metadata(scope, roots)
    assert len(index3.modules) == len(index1.modules)
    assert cache.is_file()


def test_source_roots_from_configuration(tmp_path: Path) -> None:
    # layout: scope/src/main, scope/src/cfe/ext
    main = tmp_path / "src" / "main"
    ext = tmp_path / "src" / "cfe" / "ext"
    main.mkdir(parents=True)
    ext.mkdir(parents=True)
    (main / "Configuration.xml").write_text(
        MAIN.joinpath("Configuration.xml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    conf = {
        "id": "main",
        "source": {"format": "xml", "path": "src/main"},
        "extensions": [
            {
                "id": "demo",
                "name": "DemoExt",
                "source": {"format": "xml", "path": "src/cfe/ext"},
            }
        ],
    }
    roots = source_roots_from_configuration(tmp_path, conf)
    assert len(roots) == 2
    assert roots[0].extension_name == ""
    assert roots[1].extension_name == "DemoExt"
    assert roots[0].path == main.resolve()


def test_stub_still_raises() -> None:
    with pytest.raises(DebugHttpError) as exc:
        StubObjectIdResolver().resolve("X", "CommonModule")
    assert exc.value.code == CODE_MODULE_UNRESOLVED


def test_resolver_from_roots_writes_cache(tmp_path: Path) -> None:
    resolver = XmlObjectIdResolver.from_roots(tmp_path, _roots())
    ref = resolver.resolve(
        "ТолькоРасширение", "CommonModule", extension_name="DemoExt"
    )
    assert ref.object_id == EXT_ONLY_ID
    assert modules_cache_path(tmp_path).is_file()
    # reload API on instance
    resolver.reload(tmp_path, _roots())
    assert resolver.resolve("ОтладкаДемо", "CommonModule", extension_name="DemoExt").object_id == (
        EXT_DEMO_ID
    )
