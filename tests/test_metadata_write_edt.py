"""metadata.create|update|delete on source.format: edt (#154)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from adapters.edtcli.constants import MD_SPARROW_JDK_SKIP_MESSAGE
from adapters.source.mdsparrow import (
    ENV_UNAVAILABLE_CODE,
    GAP_CODE,
    MDSPARROW_CONTENT_REFS_ISSUE,
    MDSPARROW_JAR_ENV,
    SUBSYSTEM_CONTENT_GAP_SUGGESTION,
    EdtWriteResult,
    MdSparrowError,
    resolve_jar,
    resolve_java,
)
from adapters.source.mdsparrow.resolve import ToolResolve
from adapters.source.mdsparrow.write import create_edt_object, update_edt_object
from adapters.source.xmlgen.edit import EditOp, EditResult
from cli.main import app
from core.exit_codes import ENV_UNAVAILABLE, RUNTIME_FAILURE, SUCCESS
from core.metadata import (
    MetadataResult,
    catalog_from_parts,
    create_metadata,
    delete_metadata,
    update_metadata,
)

runner = CliRunner()
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def _copy_edt_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "edt_proj"
    shutil.copytree(FIXTURE, target)
    return target


def _require_mdsparrow_runtime() -> tuple[ToolResolve, ToolResolve]:
    java = resolve_java()
    if not java.found:
        pytest.skip(MD_SPARROW_JDK_SKIP_MESSAGE)
    jar = resolve_jar()
    if not jar.found:
        pytest.skip(
            "md-sparrow jar не найден — выполните 1c-dev tools sync "
            f"или задайте {MDSPARROW_JAR_ENV}"
        )
    return java, jar


def test_create_edt_mock(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    calls: list[tuple[Path, Any]] = []

    def fake_create(edt_root: Path, catalog: Any) -> EdtWriteResult:
        calls.append((edt_root, catalog))
        mdo = (
            edt_root
            / "src"
            / "Catalogs"
            / catalog.name
            / f"{catalog.name}.mdo"
        )
        mdo.parent.mkdir(parents=True)
        mdo.write_text("<mdclass:Catalog/>", encoding="utf-8")
        return EdtWriteResult(
            changed_paths=[
                f"src/Catalogs/{catalog.name}/{catalog.name}.mdo",
                "src/Configuration/Configuration.mdo",
            ]
        )

    result = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Partners",
            synonym="Партнёры",
            attr_specs=["Article:String:50:Артикул"],
        ),
        edt_create_fn=fake_create,
    )
    assert result.status == "ok", result.diagnostics
    assert result.object == "Catalog.Partners"
    assert calls and calls[0][0] == target.resolve()
    assert any("Partners.mdo" in p for p in result.created)


def test_create_edt_already_exists(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    result = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Products", synonym="Товары"),
        edt_create_fn=lambda *_a, **_k: EdtWriteResult(),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM003" for d in result.diagnostics)


def test_create_edt_env_unavailable(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)

    def boom(_root: Path, _catalog: Any) -> EdtWriteResult:
        raise MdSparrowError("Java 25+ не найдена", code=ENV_UNAVAILABLE_CODE)

    result = create_metadata(
        target,
        catalog_from_parts(qualified_name="Catalog.Extra"),
        edt_create_fn=boom,
    )
    assert result.status == "error"
    assert any(d.get("code") == ENV_UNAVAILABLE_CODE for d in result.diagnostics)


def test_cli_metadata_1cs008_exit_env_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-032: 1CS008 (md-sparrow/JDK) → ENV_UNAVAILABLE (3)."""
    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)

    def fake_create(*_a: Any, **_k: Any) -> MetadataResult:
        return MetadataResult(
            status="error",
            diagnostics=[
                {
                    "severity": "error",
                    "code": ENV_UNAVAILABLE_CODE,
                    "message": "Java 25+ не найдена",
                    "source": "edt",
                }
            ],
        )

    monkeypatch.setattr("cli.metadata.create_metadata", fake_create)
    result = runner.invoke(
        app,
        ["metadata", "create", "Catalog.Extra", "--output", "json"],
    )
    assert result.exit_code == ENV_UNAVAILABLE


def test_cli_metadata_1cs010_exit_runtime_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-032: жёсткий 1CS010 (gap) → RUNTIME_FAILURE (4)."""
    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)

    def fake_update(*_a: Any, **_k: Any) -> MetadataResult:
        return MetadataResult(
            status="error",
            object="Catalog.Products",
            diagnostics=[
                {
                    "severity": "error",
                    "code": GAP_CODE,
                    "message": "известный gap path D",
                    "source": "edt",
                }
            ],
        )

    monkeypatch.setattr("cli.metadata.update_metadata", fake_update)
    result = runner.invoke(
        app,
        [
            "metadata",
            "update",
            "Catalog.Products",
            "--attr",
            "Price:Number:15.2",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == RUNTIME_FAILURE


def test_update_edt_mock(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    seen: list[EditOp] = []

    def fake_edit(
        edt_root: Path,
        obj_type: str,
        name: str,
        ops: list[EditOp],
    ) -> EditResult:
        assert edt_root == target.resolve()
        assert obj_type == "Catalog"
        assert name == "Products"
        seen.extend(ops)
        return EditResult(
            changed_paths=[
                str(edt_root / "src" / "Catalogs" / "Products" / "Products.mdo")
            ],
            added=1,
            warnings=[f"Number precision gap (code {GAP_CODE})"],
        )

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("add-attribute", "Price:Number(15,2)")],
        edt_edit_fn=fake_edit,
        get_fn=lambda *_a, **_k: MagicMock(status="ok", ir={"type": "Catalog"}),
    )
    assert result.status == "ok", result.diagnostics
    assert seen == [EditOp("add-attribute", "Price:Number(15,2)")]
    assert any(d.get("code") == GAP_CODE for d in result.diagnostics)


def test_delete_edt_mock(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    products = target / "src" / "Catalogs" / "Products" / "Products.mdo"
    assert products.is_file()

    def fake_delete(edt_root: Path, obj_type: str, name: str) -> EdtWriteResult:
        assert obj_type == "Catalog"
        assert name == "Products"
        path = edt_root / "src" / "Catalogs" / "Products" / "Products.mdo"
        path.unlink()
        return EdtWriteResult(
            changed_paths=[
                "src/Catalogs/Products/Products.mdo",
                "src/Configuration/Configuration.mdo",
            ]
        )

    result = delete_metadata(
        target,
        "Catalog.Products",
        edt_delete_fn=fake_delete,
    )
    assert result.status == "ok", result.diagnostics
    assert not products.is_file()


def test_delete_edt_not_found(tmp_path: Path) -> None:
    target = _copy_edt_fixture(tmp_path)
    result = delete_metadata(
        target,
        "Catalog.Missing",
        edt_delete_fn=lambda *_a, **_k: EdtWriteResult(),
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CM008" for d in result.diagnostics)


def test_parse_attr_shorthand_helpers() -> None:
    from adapters.source.mdsparrow.dto import parse_attr_shorthand

    a = parse_attr_shorthand("Article:String(50)")
    assert a.name == "Article"
    assert a.type == "String"
    assert a.length == 50
    n = parse_attr_shorthand("Price:Number(15,2)")
    assert n.type == "Number"
    assert n.precision == 15
    assert n.scale == 2
    ref = parse_attr_shorthand("Product:CatalogRef.Products")
    assert ref.type == "Ref"
    assert ref.reference == "Catalog.Products"


def test_parse_attr_shorthand_rejects_catalog_reference() -> None:
    """Fail-closed: CatalogReference / unknown *Ref must not parse as Ref."""
    from adapters.source.mdsparrow.dto import parse_attr_shorthand

    with pytest.raises(ValueError, match="CatalogRef"):
        parse_attr_shorthand("ТестСсылка:CatalogReference.Товары")
    with pytest.raises(ValueError, match="ссылочн"):
        parse_attr_shorthand("ТестСсылка:СправочникСсылка.Товары")
    with pytest.raises(ValueError, match="Неподдерживаемый ссылочный"):
        parse_attr_shorthand("X:FooRef.Bar")


def test_update_edt_register_records_gap_surfaces_1cs010(
    tmp_path: Path,
) -> None:
    """#167: metadata.update maps registerRecords EDT gap → error 1CS010."""
    from adapters.source.mdsparrow import REGISTER_RECORDS_GAP_SUGGESTION

    target = _copy_edt_fixture(tmp_path)

    def boom(
        _edt_root: Path,
        _obj_type: str,
        _name: str,
        _ops: list[EditOp],
    ) -> EditResult:
        raise MdSparrowError(
            f"registerRecords не сохранились в .mdo (gap; code {GAP_CODE})",
            code=GAP_CODE,
            suggestion=REGISTER_RECORDS_GAP_SUGGESTION,
        )

    result = update_metadata(
        target,
        "Catalog.Products",
        [EditOp("modify-property", "registerRecords=AccumulationRegister.Stock")],
        edt_edit_fn=boom,
        get_fn=lambda *_a, **_k: MagicMock(status="ok", ir={"type": "Catalog"}),
    )
    assert result.status == "error"
    gap = next(d for d in result.diagnostics if d.get("code") == GAP_CODE)
    assert gap.get("severity") == "error"
    assert gap.get("suggestion") == REGISTER_RECORDS_GAP_SUGGESTION


@pytest.mark.integration
def test_create_update_delete_edt_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live Catalog + attribute on edt_spike copy; skip без jar/JDK 25."""
    java, jar = _require_mdsparrow_runtime()
    monkeypatch.setenv(MDSPARROW_JAR_ENV, str(jar.path))
    # Ensure resolve_java sees JDK 25 (may already via JAVA_HOME).
    if java.path is not None:
        monkeypatch.setenv("JAVA_HOME", str(java.path.parent.parent))

    target = _copy_edt_fixture(tmp_path)
    partners = target / "src" / "Catalogs" / "Partners" / "Partners.mdo"
    assert not partners.exists()

    created = create_metadata(
        target,
        catalog_from_parts(
            qualified_name="Catalog.Partners",
            synonym="Партнёры",
            attr_specs=["Article:String:50:Артикул"],
        ),
    )
    assert created.status == "ok", created.diagnostics
    assert partners.is_file()
    text = partners.read_text(encoding="utf-8")
    assert "<name>Partners</name>" in text
    assert "Партнёры" in text
    assert "<name>Article</name>" in text
    assert "Артикул" in text
    assert "<length>50</length>" in text
    cfg = (target / "src" / "Configuration" / "Configuration.mdo").read_text(
        encoding="utf-8"
    )
    assert "Catalog.Partners" in cfg

    updated = update_metadata(
        target,
        "Catalog.Partners",
        [EditOp("add-attribute", "Comment:String(100)")],
    )
    assert updated.status == "ok", updated.diagnostics
    text2 = partners.read_text(encoding="utf-8")
    assert "<name>Comment</name>" in text2

    deleted = delete_metadata(target, "Catalog.Partners")
    assert deleted.status == "ok", deleted.diagnostics
    assert not partners.exists()
    cfg2 = (target / "src" / "Configuration" / "Configuration.mdo").read_text(
        encoding="utf-8"
    )
    assert "Catalog.Partners" not in cfg2


@pytest.mark.integration
def test_cli_metadata_create_edt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    java, jar = _require_mdsparrow_runtime()
    monkeypatch.setenv(MDSPARROW_JAR_ENV, str(jar.path))
    if java.path is not None:
        monkeypatch.setenv("JAVA_HOME", str(java.path.parent.parent))

    target = _copy_edt_fixture(tmp_path)
    monkeypatch.chdir(target)
    result = runner.invoke(
        app,
        [
            "metadata",
            "create",
            "Catalog.Goods",
            "--synonym",
            "Товары",
            "--attr",
            "Article:String:50:Артикул",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["object"] == "Catalog.Goods"
    mdo = target / "src" / "Catalogs" / "Goods" / "Goods.mdo"
    assert mdo.is_file()


def _stub_mdsparrow_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.resolve_java",
        lambda **_k: ToolResolve(
            found=True, path=Path("/usr/bin/java"), version="25"
        ),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=tmp_path / "md-sparrow.jar"),
    )


def test_create_subsystem_with_content_sets_content_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """md-sparrow ≥0.6.10: create Subsystem + content → contentRefs via object-set."""
    target = _copy_edt_fixture(tmp_path)
    mutations: list[dict[str, Any]] = []
    dto_state: dict[str, Any] = {"name": "Sales", "contentRefs": []}

    def fake_apply(params: dict[str, Any] | Path, **_k: Any) -> Any:
        assert isinstance(params, dict)
        mutations.append(params)
        op = params.get("op")
        if op == "add-md-object":
            name = params["name"]
            mdo = target / "src" / "Subsystems" / name / f"{name}.mdo"
            mdo.parent.mkdir(parents=True, exist_ok=True)
            mdo.write_text("<Subsystem/>", encoding="utf-8")
        elif op == "cf-md-object-set":
            payload = json.loads(params["payloadJson"])
            dto_state.clear()
            dto_state.update(payload)
        return MagicMock(stdout="OK", stderr="")

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.apply_mutation",
        fake_apply,
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto",
        lambda *_a, **_k: dict(dto_state),
    )
    _stub_mdsparrow_tools(monkeypatch, tmp_path)

    catalog = catalog_from_parts(
        qualified_name="Subsystem.Sales",
        content=["Catalog.Products"],
    )
    result = create_edt_object(target, catalog)
    assert any(m.get("op") == "add-md-object" for m in mutations)
    set_ops = [m for m in mutations if m.get("op") == "cf-md-object-set"]
    assert len(set_ops) == 1
    payload = json.loads(set_ops[0]["payloadJson"])
    assert payload.get("contentRefs") == ["Catalog.Products"]
    assert "src/Subsystems/Sales/Sales.mdo" in result.changed_paths


def test_add_remove_content_edt_updates_content_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """add-content / remove-content on EDT write contentRefs (upstream #78 fix)."""
    target = _copy_edt_fixture(tmp_path)
    sub_dir = target / "src" / "Subsystems" / "Sales"
    sub_dir.mkdir(parents=True)
    (sub_dir / "Sales.mdo").write_text(
        '<?xml version="1.0"?><mdclass:Subsystem xmlns:mdclass='
        '"http://g5.1c.ru/v8/dt/metadata/mdclass">'
        "<name>Sales</name></mdclass:Subsystem>",
        encoding="utf-8",
    )
    dto_state: dict[str, Any] = {"name": "Sales", "contentRefs": []}
    mutations: list[Any] = []

    def fake_apply(params: dict[str, Any] | Path, **_k: Any) -> Any:
        mutations.append(params)
        if isinstance(params, dict) and params.get("op") == "cf-md-object-set":
            payload = json.loads(params["payloadJson"])
            dto_state.clear()
            dto_state.update(payload)
        return MagicMock(stdout="OK", stderr="")

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.apply_mutation",
        fake_apply,
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto",
        lambda *_a, **_k: dict(dto_state),
    )
    _stub_mdsparrow_tools(monkeypatch, tmp_path)

    added = update_edt_object(
        target,
        "Subsystem",
        "Sales",
        [EditOp("add-content", "Catalog.Products")],
    )
    assert added.added == 1
    assert dto_state.get("contentRefs") == ["Catalog.Products"]

    removed = update_edt_object(
        target,
        "Subsystem",
        "Sales",
        [EditOp("remove-content", "Catalog.Products")],
    )
    assert removed.removed == 1
    assert dto_state.get("contentRefs") == []
    assert any(
        isinstance(m, dict) and m.get("op") == "cf-md-object-set" for m in mutations
    )


def test_content_refs_regression_gap_still_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If contentRefs still no-op after set → 1CS010 + suggestion (#78 regression)."""
    target = _copy_edt_fixture(tmp_path)
    sub_dir = target / "src" / "Subsystems" / "Sales"
    sub_dir.mkdir(parents=True)
    (sub_dir / "Sales.mdo").write_text("<Subsystem/>", encoding="utf-8")

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.apply_mutation",
        lambda *_a, **_k: MagicMock(stdout="OK", stderr=""),
    )
    # Always empty — simulates silent no-op write.
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto",
        lambda *_a, **_k: {"name": "Sales", "contentRefs": []},
    )
    _stub_mdsparrow_tools(monkeypatch, tmp_path)

    with pytest.raises(MdSparrowError) as exc_info:
        update_edt_object(
            target,
            "Subsystem",
            "Sales",
            [EditOp("add-content", "Catalog.Products")],
        )
    assert exc_info.value.code == GAP_CODE
    assert MDSPARROW_CONTENT_REFS_ISSUE in (exc_info.value.suggestion or "")
    assert exc_info.value.suggestion == SUBSYSTEM_CONTENT_GAP_SUGGESTION


def test_create_edt_object_unit_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """create_edt_object wires apply_mutation without real JVM."""
    target = _copy_edt_fixture(tmp_path)
    mutations: list[dict[str, Any]] = []

    def fake_apply(params: dict[str, Any] | Path, **_k: Any) -> Any:
        assert isinstance(params, dict)
        mutations.append(params)
        op = params.get("op")
        if op == "add-md-object":
            name = params["name"]
            mdo = target / "src" / "Catalogs" / name / f"{name}.mdo"
            mdo.parent.mkdir(parents=True)
            mdo.write_text(
                '<?xml version="1.0"?><mdclass:Catalog xmlns:mdclass="http://g5.1c.ru/v8/dt/metadata/mdclass">'
                f"<name>{name}</name><synonym><key>ru</key><value>{name}</value></synonym>"
                "</mdclass:Catalog>",
                encoding="utf-8",
            )
        elif op == "cf-md-attribute-add":
            pass
        elif op == "batch":
            for child in params.get("operations") or []:
                fake_apply(child)
        elif op == "cf-md-object-set":
            pass
        return MagicMock(stdout="OK", stderr="")

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.apply_mutation",
        fake_apply,
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.resolve_java",
        lambda **_k: ToolResolve(
            found=True, path=Path("/usr/bin/java"), version="25"
        ),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=tmp_path / "md-sparrow.jar"),
    )

    dto_calls = {"n": 0}

    def fake_get(object_mdo: Path, **_k: Any) -> dict[str, Any]:
        dto_calls["n"] += 1
        return {
            "kind": "catalog",
            "internalName": "Partners",
            "synonym": "Partners",
            "attributes": [
                {
                    "name": "Article",
                    "synonym": "Article",
                    "type": {
                        "types": ["xs:string"],
                        "typeSets": [],
                        "stringQualifiers": {
                            "length": "10",
                            "allowedLength": "VARIABLE",
                        },
                    },
                }
            ],
            "tabularSections": [],
            "enumValues": [],
            "dimensions": [],
            "resources": [],
        }

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto",
        fake_get,
    )

    catalog = catalog_from_parts(
        qualified_name="Catalog.Partners",
        synonym="Партнёры",
        attr_specs=["Article:String:50:Артикул"],
    )
    result = create_edt_object(target, catalog)
    assert result.changed_paths
    assert any(m.get("op") == "add-md-object" for m in mutations)
    assert dto_calls["n"] >= 1
    assert (target / "src" / "Catalogs" / "Partners" / "Partners.mdo").is_file()
