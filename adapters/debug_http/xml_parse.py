"""XML response parsers for dbgs HTTP Debug Protocol."""

from __future__ import annotations

import base64
import binascii
import re
import xml.etree.ElementTree as ET
from typing import Any

from adapters.debug_http.models import (
    DebugEvent,
    DebugTarget,
    EvalResult,
    StackFrame,
    StopEvent,
    VariableValue,
)

_B64_RE = re.compile(r"^[A-Za-z0-9+/]+=*$")


def local_name(tag: str) -> str:
    """Strip Clark notation namespace from an ElementTree tag."""
    return tag.rsplit("}", 1)[-1]


def find_texts(xml_body: str, name: str) -> list[str]:
    """Collect text of all elements with the given local name."""
    root = _parse_root(xml_body)
    if root is None:
        return []
    out: list[str] = []
    for el in root.iter():
        if local_name(el.tag) == name and el.text and el.text.strip():
            out.append(el.text.strip())
    return out


def extract_result(xml_body: str) -> str:
    """Extract ``<result>`` text from a response (empty if missing)."""
    texts = find_texts(xml_body, "result")
    return texts[0] if texts else ""


def extract_http_exception_descr(xml_body: str) -> str:
    """Extract ``<descr>`` from dbgs HTTP 400 exception body."""
    texts = find_texts(xml_body, "descr")
    if not texts:
        return ""
    # Collapse whitespace / keep first meaningful line
    return " ".join(texts[0].split())


def parse_targets(xml_body: str) -> list[DebugTarget]:
    """Parse ``getDbgAllTargetStates`` / target blocks into ``DebugTarget`` list."""
    root = _parse_root(xml_body)
    if root is None:
        return []
    targets: list[DebugTarget] = []
    for el in root.iter():
        if local_name(el.tag) not in ("id", "targetID", "DebugTargetId"):
            continue
        # Prefer nested <id> under target state blocks
        tid = ""
        if local_name(el.tag) == "id" and el.text and el.text.strip():
            tid = el.text.strip()
        else:
            for child in el.iter():
                if local_name(child.tag) == "id" and child.text and child.text.strip():
                    tid = child.text.strip()
                    break
        if not tid or len(tid) < 8:
            continue
        if any(t.target_id == tid for t in targets):
            continue
        parent_attrs = _sibling_texts(el)
        targets.append(
            DebugTarget(
                target_id=tid,
                target_type=parent_attrs.get("targetType", ""),
                state=parent_attrs.get("state", "") or parent_attrs.get("targetState", ""),
                seance_id=parent_attrs.get("seanceId", "") or parent_attrs.get("seanceID", ""),
                info_base_alias=parent_attrs.get("infoBaseAlias", ""),
            )
        )
    return targets


def parse_ping_events(xml_body: str) -> list[DebugEvent]:
    """Parse ping body into high-level events (targetStarted, callStackFormed, …)."""
    if not xml_body.strip():
        return []
    root = _parse_root(xml_body)
    if root is None:
        return []
    events: list[DebugEvent] = []
    seen: set[str] = set()

    for el in root.iter():
        name = local_name(el.tag)
        if name in ("callStackFormed", "exprEvaluated", "targetStarted", "targetQuit"):
            key = f"{name}:{id(el)}"
            if key in seen:
                continue
            seen.add(key)
            tid = _first_id_under(el)
            events.append(
                DebugEvent(
                    type=name,
                    target_id=tid,
                    payload=_element_payload(el),
                    raw_xml=ET.tostring(el, encoding="unicode"),
                )
            )
        elif name == "cmdID" and el.text:
            cmd = el.text.strip()
            if cmd and cmd not in seen:
                seen.add(cmd)
                events.append(DebugEvent(type=cmd, raw_xml=""))

    # String fallback when namespaces / wrappers obscure elements
    for token in ("targetStarted", "callStackFormed", "targetQuit", "exprEvaluated"):
        if token in xml_body and not any(e.type == token for e in events):
            events.append(DebugEvent(type=token, target_id=_guess_target_id(xml_body)))

    return events


def parse_stop_event(xml_body: str, *, target_id: str = "") -> StopEvent | None:
    """Build ``StopEvent`` from a ping body containing ``callStackFormed``."""
    if "callStackFormed" not in xml_body:
        return None
    lines = find_texts(xml_body, "lineNo")
    object_ids = find_texts(xml_body, "objectID")
    property_ids = find_texts(xml_body, "propertyID")
    n = max(len(lines), len(object_ids), len(property_ids))
    if n == 0:
        return None
    frames: list[StackFrame] = []
    for i in range(n):
        try:
            line_no = int(lines[i]) if i < len(lines) else 0
        except ValueError:
            line_no = 0
        frames.append(
            StackFrame(
                object_id=object_ids[i] if i < len(object_ids) else "",
                property_id=property_ids[i] if i < len(property_ids) else "",
                line_no=line_no,
            )
        )
    tid = target_id or _guess_target_id(xml_body)
    return StopEvent(target_id=tid, frames=tuple(frames), raw_xml=xml_body)


def decode_presentation(raw: str) -> str:
    """Decode platform ``presentation``/``pres`` (often base64 UTF-8 with NBSP)."""
    text = (raw or "").strip()
    # Platform often sends even short values as base64 (`NDI=` → `42`).
    if len(text) < 4 or not _B64_RE.fullmatch(text) or len(text) % 4 != 0:
        return text
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return text
    for encoding in ("utf-8", "utf-16-le"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if not decoded:
            continue
        # NBSP (\xa0) is common in 1C number presentations; not str.isprintable().
        if all(ch.isprintable() or ch in "\r\n\t\xa0" for ch in decoded):
            return decoded.replace("\u00a0", " ").strip()
    return text


def parse_eval_result(xml_body: str) -> EvalResult:
    """Parse sync evalLocalVariables / evalExpr response."""
    states = find_texts(xml_body, "evalResultState")
    state = states[0] if states else extract_result(xml_body)
    names = find_texts(xml_body, "propName")
    types = find_texts(xml_body, "typeName")
    presentations = find_texts(xml_body, "presentation")
    # ``pres`` is often base64 presentation in platform responses
    if not presentations:
        presentations = find_texts(xml_body, "pres")
    n = max(len(names), len(types), len(presentations))
    variables: list[VariableValue] = []
    for i in range(n):
        raw_pres = presentations[i] if i < len(presentations) else ""
        presentation = decode_presentation(raw_pres)
        variables.append(
            VariableValue(
                name=names[i] if i < len(names) else "",
                type_name=types[i] if i < len(types) else "",
                presentation=presentation,
                value_raw=presentation,
            )
        )
    return EvalResult(state=state, variables=tuple(variables), raw_xml=xml_body)


def _parse_root(xml_body: str) -> ET.Element | None:
    if not xml_body.strip():
        return None
    try:
        return ET.fromstring(xml_body)
    except ET.ParseError:
        return None


def _first_id_under(el: ET.Element) -> str:
    for child in el.iter():
        if local_name(child.tag) == "id" and child.text and child.text.strip():
            text = child.text.strip()
            if len(text) >= 8:
                return text
    return ""


def _guess_target_id(xml_body: str) -> str:
    ids = find_texts(xml_body, "id")
    for cand in ids:
        if len(cand) >= 32:
            return cand
    return ids[0] if ids else ""


def _sibling_texts(el: ET.Element) -> dict[str, str]:
    """Collect local-name → text for the element's parent children (best-effort)."""
    out: dict[str, str] = {}
    # ElementTree has no parent pointer; scan the element itself and descendants
    for child in el.iter():
        name = local_name(child.tag)
        if child.text and child.text.strip() and name not in out:
            out[name] = child.text.strip()
    return out


def _element_payload(el: ET.Element) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for child in el.iter():
        name = local_name(child.tag)
        if child.text and child.text.strip():
            payload.setdefault(name, child.text.strip())
    return payload
