"""Build a human-readable agent.transcript.md from OpenCode --format json JSONL."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, TextIO

# Keep transcript readable; full payload stays in agent.jsonl.
_TOOL_OUTPUT_MAX = 4000


def _tool_brief(part: dict[str, Any]) -> str:
    name = part.get("tool") or "?"
    st = part.get("state") or {}
    status = st.get("status") or "?"
    inp = st.get("input") or {}
    bits: list[str] = []
    for key in (
        "query",
        "id",
        "qualified_name",
        "command",
        "path",
        "filePath",
        "name",
        "vote",
    ):
        if key in inp:
            bits.append(f"{key}={str(inp[key])[:100]}")
    if not bits:
        for k, v in list(inp.items())[:3]:
            bits.append(f"{k}={str(v)[:80]}")
    detail = ", ".join(bits)
    return f"**tool** `{name}` [{status}]" + (f" — {detail}" if detail else "")


def _clip(text: str, limit: int = _TOOL_OUTPUT_MAX) -> str:
    text = text.replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit].rstrip() + f"\n… [{omitted} chars omitted]"


def _format_tool_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _tool_result_lines(part: dict[str, Any]) -> list[str]:
    """Render tool result (output and/or error) as indented markdown."""
    st = part.get("state") or {}
    rows: list[str] = []
    err = st.get("error")
    if err:
        rows.append("")
        rows.append("  ```")
        rows.append(_clip(f"ERROR: {_format_tool_payload(err)}"))
        rows.append("  ```")
        rows.append("")
    out = st.get("output")
    if out is None or out == "":
        return rows
    body = _clip(_format_tool_payload(out))
    rows.append("")
    rows.append("  ```")
    for line in body.splitlines() or [""]:
        rows.append(f"  {line}")
    rows.append("  ```")
    rows.append("")
    return rows


def event_lines(ev: dict[str, Any]) -> list[str]:
    """Turn one OpenCode JSON event into markdown lines (may be empty)."""
    t = ev.get("type")
    part = ev.get("part") or {}
    out: list[str] = []
    if t == "text" or part.get("type") == "text":
        text = (part.get("text") or "").strip()
        if text:
            out.append("")
            out.append("### model")
            out.append("")
            out.append(text)
            out.append("")
        return out
    if t == "tool_use" or part.get("type") == "tool":
        out.append("")
        out.append(f"- {_tool_brief(part)}")
        out.extend(_tool_result_lines(part))
        return out
    if t == "error" or part.get("type") == "error":
        err = ev.get("error") if isinstance(ev.get("error"), dict) else None
        data = (err or {}).get("data") if err else None
        msg = (
            part.get("message")
            or part.get("text")
            or (data or {}).get("message")
            or (err or {}).get("name")
            or (str(err) if err else None)
            or str(part)[:400]
        )
        ref = (data or {}).get("ref") if data else None
        out.append("")
        out.append(f"> **error:** {msg}" + (f" (`{ref}`)" if ref else ""))
        out.append("")
        return out
    return out


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def render_transcript(
    jsonl_path: Path,
    *,
    include_tools: bool = True,
) -> str:
    lines = [
        f"# Agent transcript",
        "",
        f"Source: `{jsonl_path}`",
        "",
    ]
    for ev in iter_jsonl(jsonl_path):
        for row in event_lines(ev):
            if not include_tools and row.startswith("- **tool**"):
                continue
            lines.append(row)
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_transcript(
    jsonl_path: Path,
    out_path: Path | None = None,
    *,
    include_tools: bool = True,
) -> Path:
    out = out_path or jsonl_path.with_name("agent.transcript.md")
    out.write_text(
        render_transcript(jsonl_path, include_tools=include_tools),
        encoding="utf-8",
    )
    return out


def watch_transcript(
    jsonl_path: Path,
    out_path: Path | None = None,
    *,
    include_tools: bool = True,
    interval_s: float = 2.0,
    stop_when_idle_s: float | None = None,
) -> None:
    """Rewrite transcript while jsonl grows. Stops when jsonl mtime idle (optional)."""
    out = out_path or jsonl_path.with_name("agent.transcript.md")
    last_size = -1
    idle_since: float | None = None
    while True:
        size = jsonl_path.stat().st_size if jsonl_path.is_file() else 0
        if size != last_size:
            write_transcript(jsonl_path, out, include_tools=include_tools)
            last_size = size
            idle_since = None
        else:
            if stop_when_idle_s is not None:
                now = time.time()
                if idle_since is None:
                    idle_since = now
                elif now - idle_since >= stop_when_idle_s:
                    break
        time.sleep(interval_s)


def tee_jsonl_to_transcript(
    stdin: TextIO,
    jsonl_path: Path,
    transcript_path: Path,
    *,
    include_tools: bool = True,
) -> None:
    """Read OpenCode JSON lines from stdin; append jsonl + refresh transcript."""
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    buf: list[str] = []
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for line in stdin:
            jf.write(line)
            jf.flush()
            buf.append(line)
            s = line.strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                continue
            rows = event_lines(ev)
            if not include_tools:
                rows = [r for r in rows if not r.startswith("- **tool**")]
            if rows:
                with transcript_path.open("a", encoding="utf-8") as tf:
                    if transcript_path.stat().st_size == 0:
                        tf.write(
                            f"# Agent transcript\n\nSource: `{jsonl_path}`\n"
                        )
                    tf.write("\n".join(rows) + "\n")
                    tf.flush()
