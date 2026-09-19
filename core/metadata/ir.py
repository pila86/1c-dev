"""Metadata IR v1 (ADR-011) — model + parsers shared by create/read."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

AttrType = Literal["String", "Number", "Boolean", "Date", "Ref"]
ObjectType = Literal[
    "Catalog",
    "Document",
    "Enum",
    "InformationRegister",
    "AccumulationRegister",
]

# Types accepted in QualifiedName for read/update paths (M2).
M2_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        "Catalog",
        "Document",
        "Enum",
        "InformationRegister",
        "AccumulationRegister",
    }
)

_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$")
_ATTR_SPEC_RE = re.compile(
    r"^(?P<name>[^:]+):(?P<type>[^:]+)(?::(?P<qual>[^:]+))?(?::(?P<synonym>.*))?$"
)


class IrError(ValueError):
    """Invalid IR / CLI input."""

    def __init__(self, message: str, *, code: str = "1CM004") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Attribute:
    name: str
    type: AttrType
    synonym: str | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.synonym:
            data["synonym"] = self.synonym
        if self.type == "String" and self.length is not None:
            data["length"] = self.length
        if self.type == "Number":
            if self.precision is not None:
                data["precision"] = self.precision
            if self.scale is not None:
                data["scale"] = self.scale
        if self.type == "Ref" and self.reference:
            data["reference"] = self.reference
        return data


@dataclass
class TabularSection:
    name: str
    synonym: str | None = None
    attributes: list[Attribute] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "attributes": [a.to_dict() for a in self.attributes],
        }
        if self.synonym:
            data["synonym"] = self.synonym
        return data


@dataclass
class EnumValue:
    name: str
    synonym: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.synonym:
            data["synonym"] = self.synonym
        return data


@dataclass
class CatalogObject:
    name: str
    synonym: str | None = None
    attributes: list[Attribute] = field(default_factory=list)
    tabular_sections: list[TabularSection] = field(default_factory=list)
    type: ObjectType = "Catalog"

    @property
    def qualified_name(self) -> str:
        return f"Catalog.{self.name}"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "name": self.name,
            "attributes": [a.to_dict() for a in self.attributes],
        }
        if self.synonym:
            data["synonym"] = self.synonym
        if self.tabular_sections:
            data["tabularSections"] = [t.to_dict() for t in self.tabular_sections]
        return data


@dataclass
class MetadataSummary:
    """list/find item (ADR-011)."""

    type: str
    name: str
    qname: str
    synonym: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "name": self.name,
            "qname": self.qname,
        }
        if self.synonym:
            data["synonym"] = self.synonym
        return data


def _check_name(name: str, *, what: str) -> str:
    cleaned = name.strip()
    if not cleaned or not _NAME_RE.match(cleaned):
        raise IrError(f"Некорректное имя {what}: {name!r}")
    return cleaned


def parse_qualified_name(ref: str) -> tuple[ObjectType, str]:
    """Parse `Catalog.Products` → (Catalog, Products). Accepts M2 object types."""
    raw = ref.strip()
    if "." not in raw:
        raise IrError(
            f"Ожидается QualifiedName вида Type.Name, получено: {ref!r}",
            code="1CM002",
        )
    type_part, name_part = raw.split(".", 1)
    if type_part not in M2_OBJECT_TYPES or not name_part or "." in name_part:
        raise IrError(
            f"Неподдерживаемый QualifiedName (ожидается один из "
            f"{', '.join(sorted(M2_OBJECT_TYPES))}): {ref!r}",
            code="1CM002",
        )
    obj_type: ObjectType = type_part  # type: ignore[assignment]
    return obj_type, _check_name(name_part, what="объекта")


def parse_attr_spec(spec: str) -> Attribute:
    """Parse CLI --attr: Name:Type[:Qual][:Synonym] (IR v1 types)."""
    m = _ATTR_SPEC_RE.match(spec.strip())
    if not m:
        raise IrError(f"Некорректный --attr: {spec!r}")
    name = _check_name(m.group("name"), what="реквизита")
    type_raw = m.group("type").strip()
    if type_raw not in ("String", "Number", "Boolean", "Date", "Ref"):
        raise IrError(f"Неподдерживаемый тип атрибута: {type_raw!r}")
    atype: AttrType = type_raw  # type: ignore[assignment]
    qual = (m.group("qual") or "").strip()
    synonym = (m.group("synonym") or "").strip() or None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    reference: str | None = None
    if atype == "String":
        length = int(qual) if qual else 10
        if length < 1:
            raise IrError(f"length должен быть >= 1: {spec!r}")
    elif atype == "Number":
        if qual:
            if "." in qual:
                p, s = qual.split(".", 1)
                precision, scale = int(p), int(s)
            else:
                precision, scale = int(qual), 0
        else:
            precision, scale = 15, 2
        if precision < 1 or scale < 0 or scale >= precision:
            raise IrError(f"Некорректные precision/scale: {spec!r}")
    elif atype == "Ref":
        if not qual:
            raise IrError(f"Для Ref нужен reference QName: {spec!r}")
        parse_qualified_name(qual)  # validate
        reference = qual
    # Boolean / Date: no qualifiers
    return Attribute(
        name=name,
        type=atype,
        synonym=synonym,
        length=length,
        precision=precision,
        scale=scale,
        reference=reference,
    )


def catalog_from_parts(
    *,
    qualified_name: str,
    synonym: str | None = None,
    attr_specs: list[str] | None = None,
) -> CatalogObject:
    """Build Catalog IR from CLI pieces (M1 create: String/Number only)."""
    obj_type, name = parse_qualified_name(qualified_name)
    if obj_type != "Catalog":
        raise IrError(
            f"M1 create поддерживает только Catalog.<Name>, получено: {qualified_name!r}",
            code="1CM002",
        )
    attrs = [parse_attr_spec(s) for s in (attr_specs or [])]
    for attr in attrs:
        if attr.type not in ("String", "Number"):
            raise IrError(
                f"M1 create поддерживает только String/Number, получено: {attr.type!r}",
                code="1CM002",
            )
    return CatalogObject(name=name, synonym=synonym, attributes=attrs)


def catalog_from_json(
    data: dict[str, Any],
    *,
    qualified_name: str | None = None,
) -> CatalogObject:
    """Build Catalog IR from JSON body (PRD §17 style)."""
    type_raw = data.get("type", "Catalog")
    name_raw = data.get("name")
    if qualified_name:
        q_type, q_name = parse_qualified_name(qualified_name)
        if q_type != "Catalog":
            raise IrError(
                f"M1 create поддерживает только Catalog.<Name>, получено: {qualified_name!r}",
                code="1CM002",
            )
        if name_raw and str(name_raw) != q_name:
            raise IrError("name в JSON не совпадает с QualifiedName")
        if type_raw and str(type_raw) != q_type:
            raise IrError("type в JSON не совпадает с QualifiedName", code="1CM002")
        obj_type, name = q_type, q_name
    else:
        if type_raw != "Catalog":
            raise IrError(
                f"M1 поддерживает только Catalog, получено: {type_raw!r}",
                code="1CM002",
            )
        if not name_raw:
            raise IrError("В JSON отсутствует name")
        obj_type, name = "Catalog", _check_name(str(name_raw), what="объекта")

    synonym = data.get("synonym")
    synonym_s = str(synonym) if synonym else None
    attrs: list[Attribute] = []
    for item in data.get("attributes") or []:
        if isinstance(item, str):
            attrs.append(parse_attr_spec(item))
            continue
        if not isinstance(item, dict):
            raise IrError("Элемент attributes должен быть объектом или строкой")
        attrs.append(_attribute_from_dict(item))
    return CatalogObject(name=name, synonym=synonym_s, attributes=attrs, type=obj_type)


def _attribute_from_dict(item: dict[str, Any]) -> Attribute:
    aname = _check_name(str(item.get("name", "")), what="реквизита")
    atype_raw = str(item.get("type", "String"))
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    reference: str | None = None
    if atype_raw.startswith("String"):
        atype: AttrType = "String"
        m = re.match(r"String\((\d+)\)", atype_raw)
        if m:
            length = int(m.group(1))
        elif "length" in item:
            length = int(item["length"])
        else:
            length = 10
    elif atype_raw.startswith("Number") or atype_raw == "Number":
        atype = "Number"
        m = re.match(r"Number\((\d+)\s*,\s*(\d+)\)", atype_raw)
        if m:
            precision, scale = int(m.group(1)), int(m.group(2))
        else:
            precision = int(item.get("precision") or 15)
            scale = int(item.get("scale") or 2)
    elif atype_raw == "Boolean":
        atype = "Boolean"
    elif atype_raw == "Date":
        atype = "Date"
    elif atype_raw == "Ref":
        atype = "Ref"
        ref = item.get("reference")
        if not ref:
            raise IrError(f"Ref-атрибут {aname!r} без reference")
        parse_qualified_name(str(ref))
        reference = str(ref)
    elif atype_raw in ("String", "Number"):
        atype = atype_raw  # type: ignore[assignment]
        if atype == "String":
            length = int(item["length"]) if "length" in item else 10
        else:
            precision = int(item.get("precision") or 15)
            scale = int(item.get("scale") or 2)
    else:
        raise IrError(f"Неподдерживаемый тип атрибута: {atype_raw!r}")
    asyn = item.get("synonym")
    return Attribute(
        name=aname,
        type=atype,
        synonym=str(asyn) if asyn else None,
        length=length,
        precision=precision,
        scale=scale,
        reference=reference,
    )


def summary_from_dict(data: dict[str, Any]) -> MetadataSummary:
    """Parse list/find item from md-reader JSON."""
    type_s = str(data.get("type") or "")
    name_s = str(data.get("name") or "")
    qname = str(data.get("qname") or f"{type_s}.{name_s}")
    synonym = data.get("synonym")
    return MetadataSummary(
        type=type_s,
        name=name_s,
        qname=qname,
        synonym=str(synonym) if synonym else None,
    )


def load_json_input(path: str) -> dict[str, Any]:
    """Load IR JSON from file path or stdin (`-`)."""
    if path == "-":
        import sys

        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise IrError("JSON IR должен быть объектом")
    return data
