"""Shared fixtures / skips for Source Adapter contract tests (#158)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from adapters.edtcli import EDTCLI_SKIP_MESSAGE, discover_edtcli
from adapters.edtcli.constants import MD_SPARROW_JDK_SKIP_MESSAGE
from adapters.source.mdsparrow import MDSPARROW_JAR_ENV, resolve_jar, resolve_java
from adapters.source.mdsparrow.resolve import ToolResolve
from adapters.source.xmlgen.resolve import resolve_jar as resolve_xmlgen_jar
from adapters.source.xmlgen.resolve import resolve_java as resolve_xmlgen_java

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EDT_SPIKE = FIXTURES / "edt_spike"

_VSCODE_MDSPARROW = Path.home() / (
    ".config/Code/User/globalStorage/yellow-hammer.1c-platform-tools/"
    "md-sparrow/v0.6.7/md-sparrow-0.6.7-all.jar"
)

XMLGEN_SKIP_MESSAGE = (
    "xml-gen jar / Java 17+ недоступны — XML write contract пропущен "
    "(scripts/fetch-xml-gen.sh / 1c-dev tools sync)"
)

MDREADER_SKIP_MESSAGE = (
    "md-reader jar / Java 21+ недоступны — Source Adapter read contract пропущен "
    "(scripts/fetch-md-reader.sh / 1c-dev tools sync)"
)


def copy_edt_spike(tmp_path: Path) -> Path:
    target = tmp_path / "edt_proj"
    shutil.copytree(EDT_SPIKE, target)
    return target


def write_xml_contract_project(tmp_path: Path) -> Path:
    """
    Minimal schema-2 XML project with Catalog.Products (parity with edt_spike).

    Layout: ``src/cf/Configuration.xml`` + ``Catalogs/Products.xml``.
    """
    root = tmp_path / "xml_proj"
    root.mkdir()
    source = root / "src" / "cf"
    source.mkdir(parents=True)
    (source / "Configuration.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">\n'
        "  <Configuration>\n"
        "    <InternalInfo/>\n"
        "    <Properties>\n"
        "      <Name>XmlContract</Name>\n"
        "      <Synonym>\n"
        "        <v8:item xmlns:v8=\"http://v8.1c.ru/8.1/data/core\">\n"
        "          <v8:lang>ru</v8:lang>\n"
        "          <v8:content>XmlContract</v8:content>\n"
        "        </v8:item>\n"
        "      </Synonym>\n"
        "    </Properties>\n"
        "    <ChildObjects>\n"
        "      <Language>Русский</Language>\n"
        "      <Catalog>Products</Catalog>\n"
        "    </ChildObjects>\n"
        "  </Configuration>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    (source / "Catalogs").mkdir()
    (source / "Catalogs" / "Products.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">\n'
        "  <Catalog uuid=\"00000000-0000-0000-0000-000000000001\">\n"
        "    <InternalInfo/>\n"
        "    <Properties>\n"
        "      <Name>Products</Name>\n"
        "      <Synonym>\n"
        "        <v8:item xmlns:v8=\"http://v8.1c.ru/8.1/data/core\">\n"
        "          <v8:lang>ru</v8:lang>\n"
        "          <v8:content>Товары</v8:content>\n"
        "        </v8:item>\n"
        "      </Synonym>\n"
        "    </Properties>\n"
        "    <ChildObjects/>\n"
        "  </Catalog>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    (source / "Languages").mkdir()
    (source / "Languages" / "Русский.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<MetaDataObject xmlns="http://v8.1c.ru/8.3/MDClasses" version="2.17">\n'
        "  <Language uuid=\"00000000-0000-0000-0000-000000000002\">\n"
        "    <Properties>\n"
        "      <Name>Русский</Name>\n"
        "      <LanguageCode>ru</LanguageCode>\n"
        "    </Properties>\n"
        "  </Language>\n"
        "</MetaDataObject>\n",
        encoding="utf-8",
    )
    home = root / ".1c-dev"
    home.mkdir()
    (home / "project.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "2",
                "project": {"name": "XmlContract", "type": "configuration"},
                "platform": {"version": "8.5.1"},
                "configurations": [
                    {
                        "id": "main",
                        "type": "configuration",
                        "source": {"format": "xml", "path": "src/cf"},
                        "default": True,
                    }
                ],
                "runtimes": [
                    {
                        "id": "main",
                        "configuration": "main",
                        "type": "file",
                        "path": ".1c-dev/runtime/main",
                        "default": True,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def require_md_reader() -> None:
    from adapters.source.mdclasses.resolve import resolve_jar, resolve_java

    java = resolve_java()
    jar = resolve_jar()
    if not java.found or not jar.found:
        pytest.skip(MDREADER_SKIP_MESSAGE)


def require_xmlgen() -> None:
    java = resolve_xmlgen_java()
    jar = resolve_xmlgen_jar()
    if not java.found or not jar.found:
        pytest.skip(XMLGEN_SKIP_MESSAGE)


def require_edtcli() -> None:
    info = discover_edtcli()
    if not info.found or info.path is None:
        pytest.skip(EDTCLI_SKIP_MESSAGE)


def require_mdsparrow(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ToolResolve, ToolResolve]:
    java = resolve_java()
    if not java.found:
        pytest.skip(MD_SPARROW_JDK_SKIP_MESSAGE)
    jar = resolve_jar()
    if not jar.found and _VSCODE_MDSPARROW.is_file():
        jar = ToolResolve(found=True, path=_VSCODE_MDSPARROW.resolve())
    if not jar.found:
        pytest.skip(
            "md-sparrow jar не найден — выполните 1c-dev tools sync "
            f"или задайте {MDSPARROW_JAR_ENV}"
        )
    monkeypatch.setenv(MDSPARROW_JAR_ENV, str(jar.path))
    if java.path is not None:
        monkeypatch.setenv("JAVA_HOME", str(java.path.parent.parent))
    return java, jar
