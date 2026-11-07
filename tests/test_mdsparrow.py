"""Unit / smoke for md-sparrow resolve + apply-mutation (#153)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from adapters.edtcli.constants import MD_SPARROW_JDK_SKIP_MESSAGE
from adapters.source.mdsparrow import (
    ENV_UNAVAILABLE_CODE,
    GAP_CODE,
    MDSPARROW_JAR_ENV,
    MUTATION_FAILED_CODE,
    REGISTER_RECORDS_GAP_SUGGESTION,
    MdSparrowError,
    apply_mutation,
    coerce_list_str,
    resolve_jar,
    resolve_java,
)
from adapters.source.mdsparrow.resolve import ToolResolve
from adapters.source.mdsparrow.write import (
    _set_dto_property,
    update_edt_object,
)
from adapters.source.xmlgen.edit import EditOp

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "edt_spike"


def test_resolve_jar_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jar = tmp_path / "custom-md-sparrow.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setenv(MDSPARROW_JAR_ENV, str(jar))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    resolved = resolve_jar()
    assert resolved.found is True
    assert resolved.path == jar.resolve()


def test_resolve_jar_cache_stable_and_pinned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(MDSPARROW_JAR_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    tools = tmp_path / "xdg" / "1c-dev" / "tools"
    tools.mkdir(parents=True)
    pinned = tools / "md-sparrow-0.6.7.jar"
    pinned.write_bytes(b"pinned")
    resolved = resolve_jar()
    assert resolved.found is True
    assert resolved.path == pinned.resolve()

    stable = tools / "md-sparrow.jar"
    stable.write_bytes(b"stable")
    resolved2 = resolve_jar()
    assert resolved2.path == stable.resolve()


def test_resolve_jar_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(MDSPARROW_JAR_ENV, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "empty"))
    resolved = resolve_jar()
    assert resolved.found is False


def test_apply_mutation_missing_java_raises_1cs008(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=False),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object"})
    assert exc.value.code == ENV_UNAVAILABLE_CODE


def test_apply_mutation_missing_jar_raises_1cs008(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=Path("/usr/bin/java"), version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=False),
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object"})
    assert exc.value.code == ENV_UNAVAILABLE_CODE


def test_apply_mutation_subprocess_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=java, version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    proc = MagicMock()
    proc.returncode = 2
    proc.stdout = ""
    proc.stderr = "boom"
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.subprocess.run",
        lambda *_a, **_k: proc,
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object", "name": "X"})
    assert exc.value.code == MUTATION_FAILED_CODE
    assert "boom" in exc.value.message


def test_apply_mutation_timeout_raises_1cs011(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=java, version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )

    def boom_timeout(*_a: object, **_k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="java", timeout=360)

    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.subprocess.run",
        boom_timeout,
    )
    with pytest.raises(MdSparrowError) as exc:
        apply_mutation({"op": "add-md-object", "name": "X"}, timeout=300)
    assert exc.value.code == MUTATION_FAILED_CODE
    assert "timeout" in exc.value.message.lower()


def test_apply_mutation_success_mocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "md-sparrow.jar"
    jar.write_bytes(b"x")
    java = tmp_path / "java"
    java.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_java",
        lambda **_k: ToolResolve(found=True, path=java, version="25"),
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.resolve_jar",
        lambda **_k: ToolResolve(found=True, path=jar),
    )
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> MagicMock:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        out = MagicMock()
        out.returncode = 0
        out.stdout = "ok"
        out.stderr = ""
        return out

    monkeypatch.setattr(
        "adapters.source.mdsparrow.mutation.subprocess.run",
        fake_run,
    )
    result = apply_mutation({"op": "add-md-object", "name": "Partners"})
    assert result.stdout == "ok"
    assert captured["cmd"][0] == str(java)
    assert captured["cmd"][1] == "-jar"
    assert captured["cmd"][2] == str(jar)
    assert captured["cmd"][3] == "apply-mutation"
    assert captured["cmd"][4].startswith("--params=")
    assert captured["kwargs"].get("timeout") == 360


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


@pytest.mark.integration
def test_apply_mutation_smoke_on_edt_spike(tmp_path: Path) -> None:
    """Live apply-mutation add-md-object on a copy of edt_spike fixture."""
    java, jar = _require_mdsparrow_runtime()
    root = tmp_path / "edt_spike"
    shutil.copytree(_FIXTURE, root)
    cfg = root / "src" / "Configuration" / "Configuration.mdo"
    assert cfg.is_file()
    partners = root / "src" / "Catalogs" / "Partners" / "Partners.mdo"
    assert not partners.exists()

    apply_mutation(
        {
            "op": "add-md-object",
            "configurationXml": str(cfg.resolve()),
            "type": "CATALOG",
            "name": "Partners",
            "synonymRu": "Партнёры",
            "schemaVersion": "V2_17",
        },
        jar=jar,
        java=java,
    )
    assert partners.is_file()
    text = partners.read_text(encoding="utf-8")
    assert "mdclass:Catalog" in text
    assert "<name>Partners</name>" in text
    cfg_text = cfg.read_text(encoding="utf-8")
    assert "Catalog.Partners" in cfg_text


def test_coerce_list_str_wire_forms() -> None:
    """#167: CLI Prop=value → list[str] (JSON array / CSV / scalar)."""
    assert coerce_list_str("AccumulationRegister.Stock") == [
        "AccumulationRegister.Stock"
    ]
    assert coerce_list_str(
        "AccumulationRegister.A, InformationRegister.B"
    ) == ["AccumulationRegister.A", "InformationRegister.B"]
    assert coerce_list_str(
        '["AccumulationRegister.A","InformationRegister.B"]'
    ) == ["AccumulationRegister.A", "InformationRegister.B"]
    assert coerce_list_str(["AccumulationRegister.A", "  "]) == [
        "AccumulationRegister.A"
    ]
    with pytest.raises(ValueError):
        coerce_list_str('{"not":"array"}')


def test_set_dto_property_register_records_is_array_not_string() -> None:
    """#167: registerRecords must land as list[str] in DTO (Gson BEGIN_ARRAY)."""
    dto: dict[str, Any] = {
        "kind": "Document",
        "internalName": "Sale",
        "document": {"registerRecords": []},
    }
    _set_dto_property(dto, "registerRecords", "AccumulationRegister.Stock")
    assert dto["registerRecords"] == ["AccumulationRegister.Stock"]
    assert isinstance(dto["registerRecords"], list)
    assert not isinstance(dto["registerRecords"], str)
    assert dto["document"]["registerRecords"] == ["AccumulationRegister.Stock"]

    # Scalar CommonModule flags stay boolean (no list coerce).
    flags: dict[str, Any] = {
        "kind": "CommonModule",
        "commonModule": {"server": False},
    }
    _set_dto_property(flags, "Server", "true")
    assert flags["commonModule"]["server"] is True


def test_update_edt_register_records_hard_fail_when_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#167 worst case: array wire OK, .mdo silent no-op → 1CS010 + suggestion."""
    root = tmp_path / "edt"
    doc = root / "src" / "Documents" / "Sale" / "Sale.mdo"
    doc.parent.mkdir(parents=True)
    doc.write_text("<mdclass:Document/>", encoding="utf-8")

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

    payloads: list[dict[str, Any]] = []

    def fake_get(_object_mdo: Path, **_k: Any) -> dict[str, Any]:
        return {
            "kind": "Document",
            "internalName": "Sale",
            "registerRecords": None,
            "document": {"registerRecords": []},
        }

    def fake_set(
        _object_mdo: Path, dto: dict[str, Any], **_k: Any
    ) -> None:
        payloads.append(dto)
        # Simulate EDT writer accepting array but not persisting (probe result).

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto", fake_get
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write._set_object_dto", fake_set
    )

    with pytest.raises(MdSparrowError) as exc:
        update_edt_object(
            root,
            "Document",
            "Sale",
            [EditOp("modify-property", "registerRecords=AccumulationRegister.Stock")],
        )
    assert exc.value.code == GAP_CODE
    assert exc.value.suggestion == REGISTER_RECORDS_GAP_SUGGESTION
    assert payloads, "cf-md-object-set must be attempted with array wire"
    sent = payloads[0]["registerRecords"]
    assert sent == ["AccumulationRegister.Stock"]
    assert isinstance(sent, list)


def test_update_edt_register_records_success_when_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#167 best case: after set, get sees registerRecords → ok."""
    root = tmp_path / "edt"
    doc = root / "src" / "Documents" / "Sale" / "Sale.mdo"
    doc.parent.mkdir(parents=True)
    doc.write_text("<mdclass:Document/>", encoding="utf-8")

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

    state = {"after_set": False}

    def fake_get(_object_mdo: Path, **_k: Any) -> dict[str, Any]:
        if state["after_set"]:
            return {
                "kind": "Document",
                "internalName": "Sale",
                "registerRecords": ["AccumulationRegister.Stock"],
                "document": {
                    "registerRecords": ["AccumulationRegister.Stock"]
                },
            }
        return {
            "kind": "Document",
            "internalName": "Sale",
            "registerRecords": None,
            "document": {"registerRecords": []},
        }

    def fake_set(_object_mdo: Path, dto: dict[str, Any], **_k: Any) -> None:
        assert dto["registerRecords"] == ["AccumulationRegister.Stock"]
        # payloadJson must serialize as JSON array, not a quoted string.
        wire = json.dumps(dto["registerRecords"])
        assert wire.startswith("[")
        state["after_set"] = True

    monkeypatch.setattr(
        "adapters.source.mdsparrow.write.read_object_dto", fake_get
    )
    monkeypatch.setattr(
        "adapters.source.mdsparrow.write._set_object_dto", fake_set
    )

    result = update_edt_object(
        root,
        "Document",
        "Sale",
        [EditOp("modify-property", "registerRecords=AccumulationRegister.Stock")],
    )
    assert result.modified == 1
    assert state["after_set"] is True
