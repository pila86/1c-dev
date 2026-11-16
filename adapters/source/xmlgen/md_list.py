"""Rewrite Designer MDListType properties after xml-gen meta edit.

Upstream xml-gen ``modify-property`` writes ``RegisterRecords`` (and similar)
as a text node. Platform import expects ``MDListType`` with nested
``xr:Item xsi:type="xr:MDObjectRef"`` — see
SteelMorgan/1c-agent-based-dev-framework#27.
"""

from __future__ import annotations

import re
from pathlib import Path

# Local names that must be MDListType of MDObjectRef (Designer XML).
_MD_OBJECT_REF_LIST_PROPS: frozenset[str] = frozenset(
    {
        "RegisterRecords",
        "BasedOn",
        "Owners",
    }
)

# <RegisterRecords>Type.Name</RegisterRecords> or with whitespace; no child tags.
_FLAT_PROP_RE = re.compile(
    r"(<(?P<name>"
    + "|".join(_MD_OBJECT_REF_LIST_PROPS)
    + r")>)(?P<body>[^<]*?)(</(?P=name)>)",
    re.DOTALL,
)


def _split_qnames(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    parts = re.split(r"[\s,;]+", text)
    return [p for p in parts if p and "." in p]


def _render_md_list(name: str, qnames: list[str], indent: str) -> str:
    if not qnames:
        return f"<{name}/>"
    inner_indent = indent + "\t"
    lines = [f"<{name}>"]
    for qn in qnames:
        lines.append(
            f'{inner_indent}<xr:Item xsi:type="xr:MDObjectRef">{qn}</xr:Item>'
        )
    lines.append(f"{indent}</{name}>")
    return "\n".join(lines)


def rewrite_md_list_properties(object_xml: Path) -> bool:
    """
    Fix flat text MDListType properties in place (surgical, keep file namespaces).

    Returns True if the file was modified.
    """
    object_xml = object_xml.resolve()
    if not object_xml.is_file():
        return False

    original = object_xml.read_text(encoding="utf-8-sig")

    def _repl(match: re.Match[str]) -> str:
        name = match.group("name")
        body = match.group("body")
        # Already has nested markup → leave alone (shouldn't match [^<]* anyway).
        qnames = _split_qnames(body)
        if not qnames and not body.strip():
            # empty text content — leave as-is (may already be wrong empty)
            return match.group(0)
        if not qnames:
            # text without Type.Name — don't touch
            return match.group(0)
        # Detect indent from line start before the opening tag.
        start = match.start()
        line_start = original.rfind("\n", 0, start) + 1
        indent = original[line_start:start]
        # Only tabs/spaces are indent; if garbage, fall back.
        if indent.strip():
            indent = "\t\t\t"
        return _render_md_list(name, qnames, indent)

    new_text, n = _FLAT_PROP_RE.subn(_repl, original)
    if n == 0 or new_text == original:
        return False
    object_xml.write_text(new_text, encoding="utf-8")
    return True


def ops_touch_md_list(ops_values: list[str]) -> bool:
    """Whether any modify-property value targets an MDListType property."""
    known_lower = {p.lower() for p in _MD_OBJECT_REF_LIST_PROPS}
    for value in ops_values:
        for part in value.split(";;"):
            piece = part.strip()
            if "=" not in piece:
                continue
            key = piece.split("=", 1)[0].strip()
            if key in _MD_OBJECT_REF_LIST_PROPS or key.lower() in known_lower:
                return True
    return False
