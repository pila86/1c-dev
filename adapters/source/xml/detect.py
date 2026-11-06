"""Designer XML layout detect (PRD §50 / ADR-032 / #158)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adapters.source.xml.constants import (
    CODE_LAYOUT_NOT_XML,
    CODE_PATH_NOT_XML_ROOT,
    CONFIGURATION_XML_NAME,
)

LayoutKind = Literal["root", "nested", "other"]


@dataclass(frozen=True)
class XmlDetectResult:
    """Результат detect для каталога Designer XML."""

    path: Path
    is_xml: bool
    kind: LayoutKind
    has_configuration_xml: bool
    code: str | None = None
    message: str | None = None
    suggestion: str | None = None


def configuration_xml_path(source_dir: Path) -> Path:
    """``Configuration.xml`` в корне source.path."""
    return source_dir / CONFIGURATION_XML_NAME


def is_xml_source_root(path: Path) -> bool:
    """True if ``path`` is a Designer XML dump root (has ``Configuration.xml``)."""
    root = path.resolve()
    return root.is_dir() and configuration_xml_path(root).is_file()


def xml_layout_kind(path: Path) -> LayoutKind:
    """Классификация: корень XML / вложенный каталог с Configuration.xml выше / иное."""
    root = path.resolve()
    if not root.is_dir():
        return "other"
    if is_xml_source_root(root):
        return "root"
    # Указали подкаталог (Catalogs/…) вместо корня выгрузки.
    parent = root.parent
    if parent.is_dir() and is_xml_source_root(parent):
        return "nested"
    return "other"


def detect_xml(path: Path) -> XmlDetectResult:
    """
    Detect Designer XML layout at ``path``.

    ``is_xml`` True только для каталога с ``Configuration.xml``.
    """
    root = path.resolve()
    has_cfg = configuration_xml_path(root).is_file() if root.is_dir() else False
    kind = xml_layout_kind(root) if root.is_dir() else "other"

    if kind == "root":
        return XmlDetectResult(
            path=root,
            is_xml=True,
            kind=kind,
            has_configuration_xml=has_cfg,
        )

    if kind == "nested":
        parent = root.parent
        return XmlDetectResult(
            path=root,
            is_xml=False,
            kind=kind,
            has_configuration_xml=has_cfg,
            code=CODE_PATH_NOT_XML_ROOT,
            message=(
                f"source.path={root}: это не корень Designer XML "
                f"(ожидается {CONFIGURATION_XML_NAME} в каталоге)"
            ),
            suggestion=f"Укажите source.path на каталог с {CONFIGURATION_XML_NAME} ({parent})",
        )

    return XmlDetectResult(
        path=root,
        is_xml=False,
        kind=kind,
        has_configuration_xml=has_cfg,
        code=CODE_LAYOUT_NOT_XML,
        message=(
            f"Каталог не является выгрузкой Designer XML: {root} "
            f"(нет {CONFIGURATION_XML_NAME})"
        ),
        suggestion=(
            "Укажите source.format: xml и source.path на каталог с Configuration.xml, "
            "либо сконвертируйте через source.convert"
        ),
    )


def validate_xml_source_dir(path: Path) -> XmlDetectResult:
    """Validate that ``path`` is a Designer XML root (для ``source.format: xml``)."""
    return detect_xml(path)
