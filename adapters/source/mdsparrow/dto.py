"""Attribute shorthand / type DTO helpers for md-sparrow (ADR-032 / #154).

Does not import ``core.metadata`` (circular-import safe).
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol


class _AttrLike(Protocol):
    name: str
    type: Any
    synonym: str | None
    length: int | None
    precision: int | None
    scale: int | None
    reference: str | None


# add-attribute shorthand: Name:String(50) | Name:Number(15,2) | Name:Boolean | Name:Ref…
_SHORTHAND_RE = re.compile(
    r"^(?P<name>[^:]+):(?P<body>.+)$",
)
_STRING_RE = re.compile(r"^String\((?P<length>\d+)\)$", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"^Number\((?P<precision>\d+)\s*,\s*(?P<scale>\d+)\)$",
    re.IGNORECASE,
)
_REF_RE = re.compile(
    r"^(?P<type>[A-Za-zА-Яа-яЁё]+)Ref\.(?P<name>.+)$",
)


def attr_type_dto(attr: _AttrLike) -> dict[str, Any]:
    """Build md-sparrow attribute ``type`` DTO from IR-like Attribute."""
    if attr.type == "String":
        length = int(attr.length or 10)
        return {
            "types": ["xs:string"],
            "typeSets": [],
            "stringQualifiers": {
                "length": str(length),
                "allowedLength": "VARIABLE",
            },
        }
    if attr.type == "Number":
        precision = int(attr.precision or 15)
        scale = int(attr.scale or 2)
        return {
            "types": ["xs:decimal"],
            "typeSets": [],
            "numberQualifiers": {
                "precision": str(precision),
                "scale": str(scale),
                "nonNegative": False,
            },
        }
    if attr.type == "Boolean":
        return {"types": ["xs:boolean"], "typeSets": []}
    if attr.type == "Date":
        return {
            "types": ["xs:dateTime"],
            "typeSets": [],
            "dateQualifiers": {"dateFractions": "DATE"},
        }
    if attr.type == "Ref":
        if not attr.reference or "." not in attr.reference:
            raise ValueError(f"Ref-атрибут {attr.name!r} без reference")
        type_part, name_part = attr.reference.split(".", 1)
        return {
            "types": [f"{type_part}Ref.{name_part}"],
            "typeSets": [],
        }
    raise ValueError(f"Неподдерживаемый тип атрибута: {attr.type!r}")


def number_precision_gap(attr: _AttrLike) -> bool:
    """True if Number precision/scale may not persist in .mdo (bake-off gap)."""
    return attr.type == "Number" and (
        attr.precision is not None or attr.scale is not None
    )


class ParsedAttr:
    """Minimal attribute carrier from xml-gen shorthand (no core.metadata import)."""

    __slots__ = (
        "name",
        "type",
        "synonym",
        "length",
        "precision",
        "scale",
        "reference",
    )

    def __init__(
        self,
        name: str,
        type: str,  # noqa: A002 — mirrors IR Attribute.type
        *,
        synonym: str | None = None,
        length: int | None = None,
        precision: int | None = None,
        scale: int | None = None,
        reference: str | None = None,
    ) -> None:
        self.name = name
        self.type = type
        self.synonym = synonym
        self.length = length
        self.precision = precision
        self.scale = scale
        self.reference = reference


def parse_attr_shorthand(value: str) -> ParsedAttr:
    """Parse xml-gen add-attribute shorthand into ParsedAttr."""
    raw = value.strip()
    m = _SHORTHAND_RE.match(raw)
    if not m:
        raise ValueError(f"Ожидался shorthand Name:Type…, получено: {value!r}")
    name = m.group("name").strip()
    body = m.group("body").strip()
    if body.lower() == "boolean":
        return ParsedAttr(name=name, type="Boolean")
    if body.lower() == "date":
        return ParsedAttr(name=name, type="Date")
    sm = _STRING_RE.match(body)
    if sm:
        return ParsedAttr(name=name, type="String", length=int(sm.group("length")))
    nm = _NUMBER_RE.match(body)
    if nm:
        return ParsedAttr(
            name=name,
            type="Number",
            precision=int(nm.group("precision")),
            scale=int(nm.group("scale")),
        )
    if body.lower().startswith("string"):
        return ParsedAttr(name=name, type="String", length=10)
    if body.lower().startswith("number"):
        return ParsedAttr(name=name, type="Number", precision=15, scale=2)
    rm = _REF_RE.match(body)
    if rm:
        return ParsedAttr(
            name=name,
            type="Ref",
            reference=f"{rm.group('type')}.{rm.group('name')}",
        )
    raise ValueError(f"Не удалось разобрать тип атрибута: {value!r}")


def parse_named_synonym(value: str) -> tuple[str, str | None]:
    """Parse ``Name: synonym=X`` / ``Name`` → (name, synonym|None)."""
    raw = value.strip()
    if ":" not in raw:
        return raw, None
    name_part, rest = raw.split(":", 1)
    name = name_part.strip()
    rest = rest.strip()
    if rest.lower().startswith("synonym="):
        return name, rest.split("=", 1)[1].strip() or None
    return name, None


def parse_property_assignment(value: str) -> tuple[str, str]:
    """Parse ``Prop=value`` modify-property wire form."""
    raw = value.strip()
    if "=" not in raw:
        raise ValueError(f"modify-property ожидает Prop=value, получено: {value!r}")
    prop, val = raw.split("=", 1)
    prop = prop.strip()
    val = val.strip()
    if not prop:
        raise ValueError(f"modify-property: пустое имя свойства в {value!r}")
    return prop, val


def coerce_list_str(value: Any) -> list[str]:
    """Coerce CLI/MCP ``Prop=value`` payload into ``list[str]`` for DTO list fields.

    Accepted forms (documented for ``registerRecords`` / #167):

    - already a ``list`` → each item ``str.strip()``, empty dropped
    - JSON array string: ``'["AccumulationRegister.X","InformationRegister.Y"]'``
    - comma-separated: ``AccumulationRegister.X,InformationRegister.Y``
    - single scalar string: one-element list

    Scalar CommonModule flags stay on the bool ``Prop=value`` path and must not
    call this helper.
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    if not isinstance(value, str):
        text = str(value).strip()
        return [text] if text else []
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"список свойств: ожидался JSON array, получено {value!r}"
            ) from exc
        if not isinstance(parsed, list):
            raise ValueError(
                f"список свойств: JSON должен быть array, получено {type(parsed).__name__}"
            )
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]
