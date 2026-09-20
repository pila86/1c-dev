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


# Object types writable via metadata.create (ADR-011 / #23 / #24).
CREATE_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        "Catalog",
        "Document",
        "Enum",
        "InformationRegister",
        "AccumulationRegister",
    }
)

# Object types writable via metadata.update (Catalog/Document + attr/TS ops).
UPDATE_OBJECT_TYPES: frozenset[str] = frozenset({"Catalog", "Document"})

_REGISTER_TYPES: frozenset[str] = frozenset(
    {"InformationRegister", "AccumulationRegister"}
)


@dataclass
class CatalogObject:
    name: str
    synonym: str | None = None
    attributes: list[Attribute] = field(default_factory=list)
    tabular_sections: list[TabularSection] = field(default_factory=list)
    values: list[EnumValue] = field(default_factory=list)
    dimensions: list[Attribute] = field(default_factory=list)
    resources: list[Attribute] = field(default_factory=list)
    type: ObjectType = "Catalog"

    @property
    def qualified_name(self) -> str:
        return f"{self.type}.{self.name}"

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "name": self.name,
        }
        if self.synonym:
            data["synonym"] = self.synonym
        if self.type == "Enum":
            data["values"] = [v.to_dict() for v in self.values]
            return data
        if self.type in _REGISTER_TYPES:
            data["dimensions"] = [a.to_dict() for a in self.dimensions]
            data["resources"] = [a.to_dict() for a in self.resources]
            return data
        data["attributes"] = [a.to_dict() for a in self.attributes]
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


def parse_ts_attr_spec(spec: str) -> tuple[str, Attribute]:
    """Parse CLI --ts-attr: TabularSection.Name:Type[:Qual][:Synonym]."""
    raw = spec.strip()
    if "." not in raw:
        raise IrError(
            f"Ожидается --ts-attr вида TSName.AttrSpec, получено: {spec!r}",
            code="1CM004",
        )
    ts_name, attr_spec = raw.split(".", 1)
    ts_clean = _check_name(ts_name, what="табличной части")
    if not attr_spec.strip():
        raise IrError(f"В --ts-attr отсутствует спецификация реквизита: {spec!r}")
    return ts_clean, parse_attr_spec(attr_spec)


def parse_ts_spec(spec: str) -> TabularSection:
    """Parse CLI --ts: Name[:Synonym]."""
    raw = spec.strip()
    if not raw:
        raise IrError("Пустой --ts")
    if ":" in raw:
        name_part, synonym_part = raw.split(":", 1)
        synonym = synonym_part.strip() or None
    else:
        name_part, synonym = raw, None
    return TabularSection(name=_check_name(name_part, what="табличной части"), synonym=synonym)


def parse_enum_value_spec(spec: str) -> EnumValue:
    """Parse CLI --value: Name[:Synonym]."""
    raw = spec.strip()
    if not raw:
        raise IrError("Пустой --value")
    if ":" in raw:
        name_part, synonym_part = raw.split(":", 1)
        synonym = synonym_part.strip() or None
    else:
        name_part, synonym = raw, None
    return EnumValue(name=_check_name(name_part, what="значения перечисления"), synonym=synonym)


def catalog_from_parts(
    *,
    qualified_name: str,
    synonym: str | None = None,
    attr_specs: list[str] | None = None,
    ts_specs: list[str] | None = None,
    ts_attr_specs: list[str] | None = None,
    value_specs: list[str] | None = None,
    dimension_specs: list[str] | None = None,
    resource_specs: list[str] | None = None,
) -> CatalogObject:
    """Build create IR from CLI pieces (ADR-011 / #23 / #24)."""
    obj_type, name = parse_qualified_name(qualified_name)
    if obj_type not in CREATE_OBJECT_TYPES:
        raise IrError(
            f"metadata.create поддерживает только "
            f"{', '.join(sorted(CREATE_OBJECT_TYPES))}.<Name>, получено: {qualified_name!r}",
            code="1CM002",
        )
    attrs = [parse_attr_spec(s) for s in (attr_specs or [])]
    sections = _tabular_sections_from_cli(
        ts_specs=list(ts_specs or []),
        ts_attr_specs=list(ts_attr_specs or []),
    )
    values = [parse_enum_value_spec(s) for s in (value_specs or [])]
    dimensions = [parse_attr_spec(s) for s in (dimension_specs or [])]
    resources = [parse_attr_spec(s) for s in (resource_specs or [])]
    obj = CatalogObject(
        name=name,
        synonym=synonym,
        attributes=attrs,
        tabular_sections=sections,
        values=values,
        dimensions=dimensions,
        resources=resources,
        type=obj_type,
    )
    _validate_create_shape(obj)
    return obj


def catalog_from_json(
    data: dict[str, Any],
    *,
    qualified_name: str | None = None,
) -> CatalogObject:
    """Build create IR from JSON body (ADR-011 / #24)."""
    name_raw = data.get("name")
    obj_type: ObjectType
    name: str
    if qualified_name:
        q_type, q_name = parse_qualified_name(qualified_name)
        if q_type not in CREATE_OBJECT_TYPES:
            raise IrError(
                f"metadata.create поддерживает только "
                f"{', '.join(sorted(CREATE_OBJECT_TYPES))}.<Name>, "
                f"получено: {qualified_name!r}",
                code="1CM002",
            )
        if name_raw and str(name_raw) != q_name:
            raise IrError("name в JSON не совпадает с QualifiedName")
        type_raw = data.get("type")
        if type_raw is not None and str(type_raw) != q_type:
            raise IrError("type в JSON не совпадает с QualifiedName", code="1CM002")
        obj_type, name = q_type, q_name
    else:
        type_raw = data.get("type", "Catalog")
        if type_raw not in CREATE_OBJECT_TYPES:
            raise IrError(
                f"metadata.create поддерживает только "
                f"{', '.join(sorted(CREATE_OBJECT_TYPES))}, получено: {type_raw!r}",
                code="1CM002",
            )
        if not name_raw:
            raise IrError("В JSON отсутствует name")
        obj_type = type_raw  # validated against CREATE_OBJECT_TYPES
        name = _check_name(str(name_raw), what="объекта")

    synonym = data.get("synonym")
    synonym_s = str(synonym) if synonym else None
    attrs = _attributes_from_json_list(list(data.get("attributes") or []))
    sections = _tabular_sections_from_json(data.get("tabularSections"))
    values = _enum_values_from_json(data.get("values"))
    dimensions = _attributes_from_json_list(list(data.get("dimensions") or []))
    resources = _attributes_from_json_list(list(data.get("resources") or []))
    obj = CatalogObject(
        name=name,
        synonym=synonym_s,
        attributes=attrs,
        tabular_sections=sections,
        values=values,
        dimensions=dimensions,
        resources=resources,
        type=obj_type,
    )
    _validate_create_shape(obj)
    return obj


def _validate_create_shape(obj: CatalogObject) -> None:
    """Reject IR fields that do not belong to the object type (ADR-011)."""
    if obj.type == "Enum":
        if obj.attributes or obj.tabular_sections or obj.dimensions or obj.resources:
            raise IrError(
                "Enum не поддерживает attributes / tabularSections / "
                "dimensions / resources",
                code="1CM004",
            )
        return
    if obj.type in _REGISTER_TYPES:
        if obj.attributes or obj.tabular_sections or obj.values:
            raise IrError(
                f"{obj.type} не поддерживает attributes / tabularSections / values",
                code="1CM004",
            )
        return
    # Catalog / Document
    if obj.values or obj.dimensions or obj.resources:
        raise IrError(
            f"{obj.type} не поддерживает values / dimensions / resources",
            code="1CM004",
        )


def _enum_values_from_json(raw: Any) -> list[EnumValue]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise IrError("values должен быть массивом")
    values: list[EnumValue] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            value = parse_enum_value_spec(item)
        elif isinstance(item, dict):
            name = _check_name(str(item.get("name", "")), what="значения перечисления")
            syn = item.get("synonym")
            value = EnumValue(name=name, synonym=str(syn) if syn else None)
        else:
            raise IrError("Элемент values должен быть объектом или строкой")
        if value.name in seen:
            raise IrError(f"Дублирующееся значение перечисления: {value.name!r}")
        seen.add(value.name)
        values.append(value)
    return values


def _tabular_sections_from_cli(
    *,
    ts_specs: list[str],
    ts_attr_specs: list[str],
) -> list[TabularSection]:
    by_name: dict[str, TabularSection] = {}
    for spec in ts_specs:
        section = parse_ts_spec(spec)
        if section.name in by_name:
            raise IrError(f"Дублирующаяся табличная часть: {section.name!r}")
        by_name[section.name] = section
    for spec in ts_attr_specs:
        ts_name, attr = parse_ts_attr_spec(spec)
        existing = by_name.get(ts_name)
        if existing is None:
            existing = TabularSection(name=ts_name)
            by_name[ts_name] = existing
        if any(a.name == attr.name for a in existing.attributes):
            raise IrError(
                f"Дублирующийся реквизит {attr.name!r} в табличной части {ts_name!r}"
            )
        existing.attributes.append(attr)
    return list(by_name.values())


def _tabular_sections_from_json(raw: Any) -> list[TabularSection]:
    if raw is None:
        return []
    if isinstance(raw, dict):
        # xml-gen-native map form: {TSName: [attrs...] | {synonym?, attributes}}
        sections: list[TabularSection] = []
        for name_raw, body in raw.items():
            name = _check_name(str(name_raw), what="табличной части")
            synonym: str | None = None
            attr_items: list[Any]
            if isinstance(body, list):
                attr_items = body
            elif isinstance(body, dict):
                syn = body.get("synonym")
                synonym = str(syn) if syn else None
                attr_items = list(body.get("attributes") or [])
            else:
                raise IrError(
                    f"tabularSections[{name!r}] должен быть массивом или объектом"
                )
            attrs = _attributes_from_json_list(attr_items)
            sections.append(
                TabularSection(name=name, synonym=synonym, attributes=attrs)
            )
        return sections
    if not isinstance(raw, list):
        raise IrError("tabularSections должен быть массивом или объектом")
    sections = []
    for item in raw:
        if not isinstance(item, dict):
            raise IrError("Элемент tabularSections должен быть объектом")
        name = _check_name(str(item.get("name", "")), what="табличной части")
        syn = item.get("synonym")
        attrs = _attributes_from_json_list(item.get("attributes") or [])
        sections.append(
            TabularSection(
                name=name,
                synonym=str(syn) if syn else None,
                attributes=attrs,
            )
        )
    return sections


def _attributes_from_json_list(items: list[Any]) -> list[Attribute]:
    attrs: list[Attribute] = []
    for item in items:
        if isinstance(item, str):
            attrs.append(parse_attr_spec(item))
            continue
        if not isinstance(item, dict):
            raise IrError("Элемент attributes должен быть объектом или строкой")
        attrs.append(_attribute_from_dict(item))
    return attrs


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
