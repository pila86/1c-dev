"""Run xml-gen subsystem compile / edit (ADR-018 / #62)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from adapters.source.xmlgen.compile import XmlGenError
from adapters.source.xmlgen.edit import EditOp, EditResult
from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java

SUBSYSTEM_ALLOWED_OPS: frozenset[str] = frozenset(
    {
        "add-content",
        "remove-content",
        "add-child",
        "remove-child",
        "set-property",
    }
)


def ir_to_subsystem_dsl(ir: dict[str, Any]) -> dict[str, Any]:
    """Map Subsystem IR dict to xml-gen ``subsystem compile`` JSON DSL."""
    name = str(ir.get("name") or "").strip()
    if not name:
        raise XmlGenError("Subsystem IR без name", code="1CM004")
    dsl: dict[str, Any] = {"name": name}
    synonym = ir.get("synonym")
    if synonym:
        dsl["synonym"] = str(synonym)
    include = ir.get("includeInCommandInterface")
    if include is not None:
        dsl["includeInCommandInterface"] = bool(include)
    content = ir.get("content")
    if isinstance(content, list):
        dsl["content"] = [str(item) for item in content]
    children = ir.get("children")
    if isinstance(children, list):
        dsl["children"] = [str(item) for item in children]
    return dsl


def compile_subsystem(
    source_dir: Path,
    dsl: dict[str, Any],
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> list[str]:
    """
    Invoke ``xml-gen subsystem compile <json> <sourceDir>/Subsystems``.

    Output dir must be ``Subsystems/`` so xml-gen registers the object in
    ``Configuration.xml`` and ``meta remove`` can find it.
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
    subsystems_dir = source_dir / "Subsystems"
    subsystems_dir.mkdir(parents=True, exist_ok=True)
    before = _snapshot(source_dir)

    with tempfile.TemporaryDirectory(prefix="1c-dev-subsystem-") as tmp:
        json_path = Path(tmp) / "subsystem.json"
        json_path.write_text(
            json.dumps(dsl, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cmd = [
            str(java_r.path),
            "-jar",
            str(jar_r.path),
            "subsystem",
            "compile",
            str(json_path),
            str(subsystems_dir),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            msg = "xml-gen subsystem compile завершился с ошибкой"
            if detail:
                msg = f"{msg}: {detail[:500]}"
            raise XmlGenError(msg, code="1CM007")

    after = _snapshot(source_dir)
    created = sorted(after - before)
    name = str(dsl.get("name", ""))
    if name:
        object_xml = subsystems_dir / f"{name}.xml"
        if object_xml.is_file():
            rel = object_xml.relative_to(source_dir).as_posix()
            if rel not in created:
                created.append(rel)
    return created


def edit_subsystem(
    object_xml: Path,
    operations: list[EditOp],
    *,
    jar: ToolResolve | None = None,
    java: ToolResolve | None = None,
) -> EditResult:
    """Invoke ``xml-gen subsystem edit <Subsystem.xml> --op … --value …`` sequentially."""
    if not operations:
        raise XmlGenError("Пустой список операций subsystem edit", code="1CM002")

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
        if op.op not in SUBSYSTEM_ALLOWED_OPS:
            raise XmlGenError(
                f"Неподдерживаемая операция subsystem edit: {op.op!r}. "
                f"Допустимо: {', '.join(sorted(SUBSYSTEM_ALLOWED_OPS))}",
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

    if not changed:
        changed = [object_xml.name]
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
        "subsystem",
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
        if "not found" in lower or "does not exist" in lower:
            raise XmlGenError(
                detail[:500] if detail else f"Объект не найден: {object_xml}",
                code="1CM008",
            )
        msg = "xml-gen subsystem edit завершился с ошибкой"
        if detail:
            msg = f"{msg}: {detail[:500]}"
        raise XmlGenError(msg, code="1CM007")

    # subsystem edit prints "Subsystem updated: <op>" — treat as one modify.
    return EditResult(
        changed_paths=[object_xml.name],
        modified=1 if "updated" in stdout.lower() else 0,
    )


def _snapshot(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    out: set[str] = set()
    for path in root.rglob("*"):
        if path.is_file():
            out.add(path.relative_to(root).as_posix())
    return out
