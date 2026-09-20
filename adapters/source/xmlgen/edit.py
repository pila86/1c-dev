"""Run xml-gen meta edit (ADR-007 / #22)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adapters.source.xmlgen.compile import XmlGenError
from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java

_WARN_RE = re.compile(r"^\[WARN\]\s*(.+)$")
_SAVED_RE = re.compile(r"^\[INFO\]\s*Saved:\s*(.+)$")
_SUMMARY_COUNT_RE = re.compile(
    r"^\s*(Added|Removed|Modified|Warnings):\s*(\d+)\s*$",
    re.IGNORECASE,
)

ALLOWED_OPS: frozenset[str] = frozenset(
    {
        "add-attribute",
        "modify-attribute",
        "remove-attribute",
        "add-ts",
        "modify-ts",
        "remove-ts",
        "add-ts-attribute",
        "remove-ts-attribute",
    }
)


@dataclass(frozen=True)
class EditOp:
    """Single xml-gen meta edit operation."""

    op: str
    value: str


@dataclass
class EditResult:
    """Aggregated result of sequential meta edit calls."""

    changed_paths: list[str] = field(default_factory=list)
    added: int = 0
    modified: int = 0
    removed: int = 0
    warnings: list[str] = field(default_factory=list)


def edit_metadata(
    object_xml: Path,
    operations: list[EditOp],
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> EditResult:
    """
    Invoke `xml-gen meta edit <object.xml> --op … --value …` sequentially.

    Does not use ``--batch`` (MlText synonym bug in pinned xml-gen).
    """
    if not operations:
        raise XmlGenError("Пустой список операций meta edit", code="1CM002")

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

    object_xml = object_xml.resolve()
    if not object_xml.is_file():
        raise XmlGenError(
            f"Файл объекта не найден: {object_xml}",
            code="1CM008",
        )

    aggregate = EditResult()
    changed: list[str] = []

    for op in operations:
        if op.op not in ALLOWED_OPS:
            raise XmlGenError(
                f"Неподдерживаемая операция meta edit: {op.op!r}",
                code="1CM002",
            )
        partial = _run_one_edit(
            object_xml,
            op,
            java_path=java_r.path,
            jar_path=jar_r.path,
        )
        aggregate.added += partial.added
        aggregate.modified += partial.modified
        aggregate.removed += partial.removed
        aggregate.warnings.extend(partial.warnings)
        for path in partial.changed_paths:
            if path not in changed:
                changed.append(path)

    aggregate.changed_paths = changed
    return aggregate


def _run_one_edit(
    object_xml: Path,
    op: EditOp,
    *,
    java_path: Path,
    jar_path: Path,
) -> EditResult:
    cmd = [
        str(java_path),
        "-jar",
        str(jar_path),
        "meta",
        "edit",
        str(object_xml),
        "--op",
        op.op,
        "--value",
        op.value,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()
        lower = detail.lower()
        if "not found" in lower or "object file not found" in lower:
            raise XmlGenError(
                detail[:500] if detail else f"Объект не найден: {object_xml}",
                code="1CM008",
            )
        msg = "xml-gen meta edit завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        raise XmlGenError(msg, code="1CM007")

    return _parse_edit_output(stdout, object_xml=object_xml)


def _parse_edit_output(stdout: str, *, object_xml: Path) -> EditResult:
    warnings: list[str] = []
    saved: list[str] = []
    added = modified = removed = 0
    in_summary = False

    for raw_line in stdout.splitlines():
        line = raw_line.rstrip()
        if "=== meta-edit summary ===" in line:
            in_summary = True
            continue
        warn_m = _WARN_RE.match(line)
        if warn_m:
            warnings.append(warn_m.group(1).strip())
            continue
        saved_m = _SAVED_RE.match(line)
        if saved_m:
            saved.append(saved_m.group(1).strip())
            continue
        if in_summary:
            count_m = _SUMMARY_COUNT_RE.match(line)
            if count_m:
                key = count_m.group(1).lower()
                val = int(count_m.group(2))
                if key == "added":
                    added = val
                elif key == "modified":
                    modified = val
                elif key == "removed":
                    removed = val

    changed_paths = list(saved)
    if (added or modified or removed) and not changed_paths:
        changed_paths = [object_xml.name]

    return EditResult(
        changed_paths=changed_paths,
        added=added,
        modified=modified,
        removed=removed,
        warnings=warnings,
    )


def edit_op_from_dict(item: dict[str, Any]) -> EditOp:
    """Build EditOp from JSON operation object."""
    op = str(item.get("op") or "").strip()
    value = str(item.get("value") if item.get("value") is not None else "")
    if not op:
        raise ValueError("В operation отсутствует op")
    return EditOp(op=op, value=value)
