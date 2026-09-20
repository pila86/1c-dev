"""Run xml-gen meta compile (ADR-007 / #23)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java

# Designer folder names for create-supported types.
_TYPE_DIRS: dict[str, str] = {
    "Catalog": "Catalogs",
    "Document": "Documents",
    "Enum": "Enums",
    "InformationRegister": "InformationRegisters",
    "AccumulationRegister": "AccumulationRegisters",
}


class XmlGenError(Exception):
    """xml-gen subprocess or environment failure."""

    def __init__(self, message: str, *, code: str = "1CM007") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def attr_ir_to_xmlgen_type(attr: dict[str, Any]) -> str:
    """Map one IR attribute dict to xml-gen type shorthand (String(10), CatalogRef.X, …)."""
    atype = str(attr.get("type", "String"))
    if atype == "String":
        length = int(attr.get("length") or 10)
        return f"String({length})"
    if atype == "Number":
        precision = int(attr.get("precision") or 15)
        scale = int(attr.get("scale") or 2)
        return f"Number({precision},{scale})"
    if atype == "Boolean":
        return "Boolean"
    if atype == "Date":
        return "Date"
    if atype == "Ref":
        reference = str(attr.get("reference") or "")
        if "." not in reference:
            raise XmlGenError(
                f"Ref-атрибут {attr.get('name')!r} без reference QName",
                code="1CM004",
            )
        type_part, name_part = reference.split(".", 1)
        return f"{type_part}Ref.{name_part}"
    # Already xml-gen-shaped (e.g. String(50) from tests / passthrough)
    return atype


def _attr_to_xmlgen_entry(attr: dict[str, Any]) -> dict[str, Any]:
    name = str(attr["name"])
    entry: dict[str, Any] = {"name": name, "type": attr_ir_to_xmlgen_type(attr)}
    synonym = attr.get("synonym")
    if synonym:
        entry["synonym"] = str(synonym)
    return entry


def ir_to_xmlgen_dsl(ir: dict[str, Any]) -> dict[str, Any]:
    """
    Map our IR dict to xml-gen meta compile JSON DSL.

    Tabular sections: IR uses an array of {name, synonym?, attributes[]};
    xml-gen expects a map ``{TSName: [attr, …]}`` (synonym applied later via
    ``meta edit --op modify-ts``).

    Enum: ``values`` → xml-gen ``values`` (``{name, synonym?}``).
    Registers: ``dimensions`` / ``resources`` → same attr entry shape as attributes.
    """
    attrs_out = [
        _attr_to_xmlgen_entry(attr)
        for attr in (ir.get("attributes") or [])
        if isinstance(attr, dict)
    ]

    dsl: dict[str, Any] = {
        "type": ir["type"],
        "name": ir["name"],
    }
    if ir.get("synonym"):
        dsl["synonym"] = ir["synonym"]
    if attrs_out:
        dsl["attributes"] = attrs_out

    values_out = _enum_values_to_xmlgen(ir.get("values"))
    if values_out:
        dsl["values"] = values_out

    dims_out = [
        _attr_to_xmlgen_entry(attr)
        for attr in (ir.get("dimensions") or [])
        if isinstance(attr, dict)
    ]
    if dims_out:
        dsl["dimensions"] = dims_out

    res_out = [
        _attr_to_xmlgen_entry(attr)
        for attr in (ir.get("resources") or [])
        if isinstance(attr, dict)
    ]
    if res_out:
        dsl["resources"] = res_out

    ts_raw = ir.get("tabularSections")
    if isinstance(ts_raw, dict):
        # Already xml-gen map form (or mixed); normalize attribute entries.
        ts_map: dict[str, list[dict[str, Any]]] = {}
        for ts_name, body in ts_raw.items():
            if isinstance(body, list):
                items = body
            elif isinstance(body, dict):
                items = list(body.get("attributes") or [])
            else:
                continue
            normalized: list[dict[str, Any]] = []
            for item in items:
                if isinstance(item, dict):
                    normalized.append(_attr_to_xmlgen_entry(item))
                elif isinstance(item, str):
                    normalized.append({"name": item, "type": "String(10)"})
            ts_map[str(ts_name)] = normalized
        if ts_map:
            dsl["tabularSections"] = ts_map
    elif isinstance(ts_raw, list) and ts_raw:
        ts_map = {}
        for section in ts_raw:
            if not isinstance(section, dict):
                continue
            ts_name = str(section["name"])
            ts_map[ts_name] = [
                _attr_to_xmlgen_entry(attr)
                for attr in (section.get("attributes") or [])
                if isinstance(attr, dict)
            ]
        dsl["tabularSections"] = ts_map

    return dsl


def _enum_values_to_xmlgen(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
            if not name:
                continue
            entry: dict[str, Any] = {"name": str(name)}
            synonym = item.get("synonym")
            if synonym:
                entry["synonym"] = str(synonym)
            out.append(entry)
        elif isinstance(item, str) and item.strip():
            out.append({"name": item.strip()})
    return out


def compile_metadata(
    source_dir: Path,
    dsl: dict[str, Any],
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> list[str]:
    """
    Invoke `xml-gen meta compile <json> <source_dir>`.

    Returns relative paths (posix) of created/changed artifacts under source_dir.
    """
    jar_r = jar if jar is not None else resolve_jar()
    java_r = java if java is not None else resolve_java()
    if not java_r.found or java_r.path is None:
        raise XmlGenError(
            f"Java {17}+ не найдена (нужна для xml-gen)",
            code="1CM006",
        )
    if not jar_r.found or jar_r.path is None:
        raise XmlGenError(
            "xml-gen jar не найден",
            code="1CM006",
        )

    source_dir = source_dir.resolve()
    before = _snapshot(source_dir)

    with tempfile.TemporaryDirectory(prefix="1c-dev-xmlgen-") as tmp:
        json_path = Path(tmp) / "object.json"
        json_path.write_text(
            json.dumps(dsl, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cmd = [
            str(java_r.path),
            "-jar",
            str(jar_r.path),
            "meta",
            "compile",
            str(json_path),
            str(source_dir),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            msg = "xml-gen meta compile завершился с ошибкой"
            if detail:
                msg = f"{msg}: {detail[:500]}"
            raise XmlGenError(msg, code="1CM007")

    after = _snapshot(source_dir)
    created = sorted(after - before)
    # Always report main object file if present
    name = str(dsl.get("name", ""))
    obj_type = str(dsl.get("type", ""))
    folder = _TYPE_DIRS.get(obj_type)
    if name and folder:
        object_xml = source_dir / folder / f"{name}.xml"
        if object_xml.is_file():
            rel = object_xml.relative_to(source_dir).as_posix()
            if rel not in created:
                created.append(rel)
    return created


def _snapshot(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    out: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file():
            out.add(path.relative_to(root).as_posix())
    return out
