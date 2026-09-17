"""Run xml-gen meta compile (ADR-007)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from adapters.source.xmlgen.resolve import ToolResolve, resolve_jar, resolve_java


class XmlGenError(Exception):
    """xml-gen subprocess or environment failure."""

    def __init__(self, message: str, *, code: str = "1CM007") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def ir_to_xmlgen_dsl(ir: dict[str, Any]) -> dict[str, Any]:
    """Map our IR dict to xml-gen meta compile JSON DSL."""
    attrs_out: list[dict[str, Any] | str] = []
    for attr in ir.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        name = str(attr["name"])
        atype = str(attr.get("type", "String"))
        synonym = attr.get("synonym")
        if atype == "String":
            length = int(attr.get("length") or 10)
            type_spec = f"String({length})"
        elif atype == "Number":
            precision = int(attr.get("precision") or 15)
            scale = int(attr.get("scale") or 2)
            type_spec = f"Number({precision},{scale})"
        else:
            type_spec = atype
        entry: dict[str, Any] = {"name": name, "type": type_spec}
        if synonym:
            entry["synonym"] = str(synonym)
        attrs_out.append(entry)

    dsl: dict[str, Any] = {
        "type": ir["type"],
        "name": ir["name"],
    }
    if ir.get("synonym"):
        dsl["synonym"] = ir["synonym"]
    if attrs_out:
        dsl["attributes"] = attrs_out
    return dsl


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
    # Always report main catalog file if present
    name = str(dsl.get("name", ""))
    if name:
        catalog = source_dir / "Catalogs" / f"{name}.xml"
        if catalog.is_file():
            rel = catalog.relative_to(source_dir).as_posix()
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
