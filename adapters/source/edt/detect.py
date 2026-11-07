"""EDT project layout detect (ADR-032 / spike #149 / #152)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from adapters.source.edt.constants import (
    CODE_LAYOUT_NOT_EDT,
    CODE_PATH_NOT_EDT_ROOT,
    CONFIGURATION_MDO_REL,
    PROJECT_FILE_NAME,
    V8_CONFIGURATION_NATURE,
)

LayoutKind = Literal["root", "src_like", "other"]

_PROJECT_NAME_RE = re.compile(r"<name>\s*([^<]+?)\s*</name>", re.IGNORECASE)


@dataclass(frozen=True)
class EdtDetectResult:
    """Результат detect для каталога (кандидат на EDT project root)."""

    path: Path
    is_edt: bool
    kind: LayoutKind
    has_configuration_mdo: bool
    has_v8_nature: bool
    project_name: str | None
    code: str | None = None
    message: str | None = None
    suggestion: str | None = None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_v8_configuration_nature(project_file: Path) -> bool:
    """True if ``.project`` declares V8ConfigurationNature."""
    if not project_file.is_file():
        return False
    try:
        text = _read_text(project_file)
    except OSError:
        return False
    if V8_CONFIGURATION_NATURE in text:
        return True
    # Fallback: parse natures (tolerate missing XML declaration quirks).
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    for nature in root.findall("natures/nature"):
        if (nature.text or "").strip() == V8_CONFIGURATION_NATURE:
            return True
    return False


def read_edt_project_name(project_root: Path) -> str | None:
    """Имя EDT-проекта из ``.project`` ``<name>`` (первый тег)."""
    project_file = project_root / PROJECT_FILE_NAME
    if not project_file.is_file():
        return None
    try:
        text = _read_text(project_file)
    except OSError:
        return None
    try:
        root = ET.fromstring(text)
        name_el = root.find("name")
        if name_el is not None and name_el.text and name_el.text.strip():
            return name_el.text.strip()
    except ET.ParseError:
        pass
    match = _PROJECT_NAME_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


def configuration_mdo_path(project_root: Path) -> Path:
    """``src/Configuration/Configuration.mdo`` относительно корня EDT."""
    return project_root / CONFIGURATION_MDO_REL


def is_edt_project_root(path: Path) -> bool:
    """
    Detect EDT project root.

    Критерии (spike #149 / ADR-032): ``.project`` с
    ``V8ConfigurationNature`` и/или ``src/Configuration/Configuration.mdo``.
    """
    root = path.resolve()
    if not root.is_dir():
        return False
    if configuration_mdo_path(root).is_file():
        return True
    return has_v8_configuration_nature(root / PROJECT_FILE_NAME)


def edt_layout_kind(path: Path) -> LayoutKind:
    """Классификация пути: корень EDT / похож на ``src/`` / иное."""
    root = path.resolve()
    if not root.is_dir():
        return "other"
    if is_edt_project_root(root):
        return "root"
    # Указали ``src/`` (или каталог с Configuration.mdo) вместо корня проекта.
    if (root / "Configuration" / "Configuration.mdo").is_file():
        return "src_like"
    if root.name == "src" and is_edt_project_root(root.parent):
        return "src_like"
    return "other"


def detect_edt(path: Path) -> EdtDetectResult:
    """
    Detect EDT layout at ``path``.

    ``is_edt`` True только для корня проекта (не для ``src/``).
    При неуспехе заполняет ``code`` / ``message`` (1CS003 / 1CS004).
    """
    root = path.resolve()
    has_mdo = configuration_mdo_path(root).is_file() if root.is_dir() else False
    has_nature = (
        has_v8_configuration_nature(root / PROJECT_FILE_NAME) if root.is_dir() else False
    )
    kind = edt_layout_kind(root) if root.is_dir() else "other"
    project_name = read_edt_project_name(root) if root.is_dir() else None

    if kind == "root":
        return EdtDetectResult(
            path=root,
            is_edt=True,
            kind=kind,
            has_configuration_mdo=has_mdo,
            has_v8_nature=has_nature,
            project_name=project_name,
        )

    if kind == "src_like":
        parent = root.parent if (root.name == "src" and is_edt_project_root(root.parent)) else None
        if parent is None and (root / "Configuration" / "Configuration.mdo").is_file():
            parent = root.parent
        hint = f" ({parent})" if parent is not None else " (.project + src/…)"
        suggestion = f"Укажите source.path на корень EDT-проекта{hint}"
        return EdtDetectResult(
            path=root,
            is_edt=False,
            kind=kind,
            has_configuration_mdo=has_mdo,
            has_v8_nature=has_nature,
            project_name=project_name,
            code=CODE_PATH_NOT_EDT_ROOT,
            message=(
                f"source.path={root}: это не корень EDT-проекта "
                "(ожидаются .project и/или src/Configuration/Configuration.mdo)"
            ),
            suggestion=suggestion,
        )

    return EdtDetectResult(
        path=root,
        is_edt=False,
        kind=kind,
        has_configuration_mdo=has_mdo,
        has_v8_nature=has_nature,
        project_name=project_name,
        code=CODE_LAYOUT_NOT_EDT,
        message=(
            f"Каталог не является EDT-проектом: {root} "
            f"(нет {PROJECT_FILE_NAME} с {V8_CONFIGURATION_NATURE} "
            f"и нет {CONFIGURATION_MDO_REL})"
        ),
        suggestion=(
            "Укажите source.format: edt и source.path на корень проекта "
            "(.project / DT-INF / src), либо сконвертируйте через source.convert"
        ),
    )


def validate_edt_source_dir(path: Path) -> EdtDetectResult:
    """Validate that ``path`` is an EDT project root (для ``source.format: edt``)."""
    return detect_edt(path)
