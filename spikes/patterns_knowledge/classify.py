"""Heuristic purpose/subdomain classification."""

from __future__ import annotations

import re
from pathlib import Path

CODING_SUBDOMAIN_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("transactions_locks", re.compile(r"transaction|txn-|транзак|блокир|object-locks", re.I)),
    ("document_posting", re.compile(r"document-posting|posting|проведен|обработк.?проведен", re.I)),
    ("accumulation_register", re.compile(r"register-design|регистр.?накоплени|остатк.?товар", re.I)),
    ("strings_nstr", re.compile(r"string|nstr|локализ|localization", re.I)),
    ("queries", re.compile(r"query-optim|query-pattern|запрос.?в.?цикл|anti.?pattern", re.I)),
    ("forms_client_server", re.compile(r"form-pattern|form_module|form-event|форм.?модул", re.I)),
    ("bsp_ssl", re.compile(r"bsp-pattern|bsl-ssl|1c-ssl|1c-bsp|/bsp/", re.I)),
    ("code_style", re.compile(r"coding-standard|code-review|module-placement|refactor", re.I)),
]

DROP_PATH = re.compile(
    r"(^|/)(meta-add|meta-edit|meta-info|cf-|cfe-|form-compile|form-edit|role-edit|"
    r"subsystem-edit|interface-edit|epf-|erf-|xdto|code-patch|code-search|"
    r"code-diagnostics|db-|autonomous-server|source-access|platform-help|"
    r"log-analysis|release-support|test-authoring|unica-dev|"
    r"sdd-workflow|model-selection|agent-|git-safety|mcp-tool|skill-design|"
    r"file-edit|text-formatting|edt-|designer-batch|v8unpack|1c-db-|1c-web-|"
    r"1c-meta-|1c-cf-|arch/rules|\.agents/)",
    re.I,
)


def should_drop_path(rel: str) -> bool:
    return bool(DROP_PATH.search(rel.replace("\\", "/")))


def hint_subdomain(rel: str, hints: dict[str, str] | None) -> str | None:
    if not hints:
        return None
    norm = rel.replace("\\", "/")
    for pattern, subdomain in hints.items():
        # simple ** / * glob → regex
        rx = (
            "^"
            + re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            + "$"
        )
        if re.match(rx, norm) or re.search(
            re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", ".*"),
            norm,
        ):
            return subdomain
        # also substring match for **/foo/**
        bare = pattern.strip("*").strip("/")
        if bare and bare in norm:
            return subdomain
    return None


def guess_subdomain(rel: str, title: str, body: str) -> str:
    blob = f"{rel}\n{title}\n{body[:2000]}"
    for subdomain, rx in CODING_SUBDOMAIN_KEYWORDS:
        if rx.search(blob):
            return subdomain
    return "other_coding"


def slug_id(repo_id: str, rel: str) -> str:
    stem = Path(rel).stem.lower()
    stem = re.sub(r"[^a-z0-9а-яё]+", "-", stem, flags=re.I).strip("-")
    parent = Path(rel).parent.name.lower()
    parent = re.sub(r"[^a-z0-9а-яё]+", "-", parent, flags=re.I).strip("-")
    if parent and parent not in {"rules", "skills", "seed", "."}:
        slug = f"{parent}--{stem}" if stem != parent else stem
    else:
        slug = stem
    return f"{repo_id}--{slug}"
