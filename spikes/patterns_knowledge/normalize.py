"""Parse markdown / SKILL.md into Card dicts.

Search index uses only the document header (skill description / rule intro).
Card body for patterns.get is a trimmed recipe without MCP/tool routing noise.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from patterns_knowledge.classify import (
    guess_subdomain,
    hint_subdomain,
    should_drop_path,
    slug_id,
)

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_CODE_FENCE = re.compile(r"```(\w+)?\n(.*?)```", re.S)
_SECTION = re.compile(r"(?=^##\s+)", re.M)
_MAX_BODY = 4000
_MAX_INTRO = 600

# Sections that are tool/process routing, not coding recipes.
_DROP_SECTION = re.compile(
    r"(?i)^(mcp\s*routing|preferred\s*path|references|reading\s*utf-?8|"
    r"workflow|границ[аы]|boundaries|инструмент|tool\s*routing|"
    r"how\s*to\s*use\s*this\s*skill|using\s*this\s*skill)$"
)
_NOISE_LINE = re.compile(
    r"(?i)^\s*(-|\*)?\s*(preferred\s*path:|use\s+mcp\s+`?unica|"
    r"do\s+not\s+call\s+internal|runtime\s+идёт\s+через|"
    r"use\s+`?unica\.(view|run|apply|check|docs|search))"
)


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, m.group(2)


def _is_skill_path(rel: str) -> bool:
    n = rel.replace("\\", "/").lower()
    return n.endswith("/skill.md") or n.endswith("skill.md")


def _title_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("#") and not s.startswith("##"):
            return s.lstrip("#").strip() or fallback
    return fallback


def _extract_code(body: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _CODE_FENCE.finditer(body):
        lang = (m.group(1) or "text").lower()
        text = m.group(2).strip()
        if not text:
            continue
        # Prefer BSL / 1C snippets; still keep a few others.
        out.append({"lang": lang, "caption": "", "text": text[:4000]})
        if len(out) >= 5:
            break
    return out


def _intro_paragraphs(body: str, *, max_chars: int = _MAX_INTRO) -> str:
    """Prose after H1 until first ## / --- / fence — for rules without description."""
    lines: list[str] = []
    past_title = False
    for line in body.splitlines():
        s = line.strip()
        if not past_title:
            if s.startswith("#") and not s.startswith("##"):
                past_title = True
            continue
        if not s:
            if lines:
                break
            continue
        if s.startswith("##") or s == "---" or s.startswith("```"):
            break
        if s.startswith("|") or s.startswith("<!--"):
            continue
        lines.append(s)
        if sum(len(x) for x in lines) >= max_chars:
            break
    return " ".join(lines)[:max_chars]


def _summary_from_meta_or_body(meta: dict[str, Any], body: str) -> str:
    for key in ("summary", "description"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:500]
    return _intro_paragraphs(body)[:400]


def _section_title(block: str) -> str:
    first = block.splitlines()[0].strip() if block else ""
    if first.startswith("##"):
        return first.lstrip("#").strip()
    return ""


def _trim_body(body: str) -> str:
    """Keep coding content; drop MCP routing / tool workflow sections."""
    parts = _SECTION.split(body.strip())
    if not parts:
        return ""
    kept: list[str] = []
    # Preamble (before first ##): keep intro, drop noise lines.
    preamble = parts[0]
    pre_lines = []
    for line in preamble.splitlines():
        if _NOISE_LINE.search(line):
            continue
        pre_lines.append(line)
    pre = "\n".join(pre_lines).strip()
    if pre:
        kept.append(pre)
    for block in parts[1:]:
        title = _section_title(block)
        if title and _DROP_SECTION.match(title):
            continue
        # Drop blocks that are almost only tool routing.
        content_lines = [
            ln for ln in block.splitlines()[1:] if ln.strip() and not _NOISE_LINE.search(ln)
        ]
        if not content_lines:
            continue
        kept.append(block.strip())
    text = "\n\n".join(kept).strip()
    return text[:_MAX_BODY]


def embed_text(card: dict[str, Any]) -> str:
    """Lean search text: header only (no full body / code)."""
    parts = [
        card.get("title") or "",
        card.get("summary") or "",
        card.get("subdomain") or "",
        " ".join(card.get("when_to_use") or []),
        " ".join(card.get("anti_patterns") or []),
    ]
    return "\n".join(p for p in parts if p)


def file_to_card(
    *,
    repo_id: str,
    rel: str,
    text: str,
    license_id: str,
    trust: float,
    repo_url: str | None,
    commit: str | None,
    hints: dict[str, str] | None,
    stars: int = 0,
    forks: int = 0,
) -> dict[str, Any] | None:
    rel_n = rel.replace("\\", "/")
    if should_drop_path(rel_n):
        return None
    meta, body = _parse_front_matter(text)
    body = body.strip()
    if len(body) < 40 and not meta:
        return None

    name = meta.get("name")
    h1 = _title_from_body(body, "")
    title = str(
        meta.get("title")
        or h1
        or (name if isinstance(name, str) and name.strip() else None)
        or Path(rel_n).stem
    )
    summary = _summary_from_meta_or_body(meta, body)
    subdomain = (
        str(meta.get("subdomain") or "")
        or hint_subdomain(rel_n, hints)
        or guess_subdomain(rel_n, title, summary or body)
    )
    when = meta.get("when_to_use") or []
    anti = meta.get("anti_patterns") or []
    if isinstance(when, str):
        when = [when]
    if isinstance(anti, str):
        anti = [anti]
    # Skills often encode "when" only in description — use as when_to_use hint.
    if not when and summary and _is_skill_path(rel_n):
        when = [summary[:240]]

    body_trim = _trim_body(body)
    if len(body_trim) < 40:
        # Reference / short rule: keep intro + truncated raw body without drop.
        body_trim = (summary + "\n\n" + body)[:_MAX_BODY] if summary else body[:_MAX_BODY]
    code = _extract_code(body_trim)
    card_id = slug_id(repo_id, rel_n)
    payload = {
        "id": card_id,
        "purpose": "coding",
        "subdomain": subdomain,
        "title": title,
        "summary": summary,
        "when_to_use": list(when),
        "anti_patterns": list(anti),
        "body_markdown": body_trim,
        "code": code,
        "source": {
            "repo_id": repo_id,
            "repo_url": repo_url or "",
            "path": rel_n,
            "commit": commit or "",
            "license": license_id,
            "trust": trust,
        },
        "quality": {
            "stars_repo": stars,
            "forks_repo": forks,
            "feedback_score": 0,
            "feedback_n": 0,
        },
        "content_hash": "",
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    digest = hashlib.sha256(
        (payload["title"] + "\0" + payload["summary"] + "\0" + payload["body_markdown"]).encode(
            "utf-8"
        )
    ).hexdigest()
    payload["content_hash"] = f"sha256:{digest}"
    payload["_embed_text"] = embed_text(payload)
    return payload
