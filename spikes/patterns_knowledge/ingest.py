"""Clone allowlist sources and write Card JSON files."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from patterns_knowledge.normalize import file_to_card
from patterns_knowledge.paths import (
    CARDS_DIR,
    DATA_ROOT,
    LOCK_PATH,
    MIRRORS_DIR,
    NOTICE_PATH,
    PKG_DIR,
    SOURCES_YAML,
    ensure_data_dirs,
)


def _load_sources() -> dict[str, Any]:
    with SOURCES_YAML.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _match_globs(rel: str, include: list[str], exclude: list[str] | None) -> bool:
    from fnmatch import fnmatch

    rel_n = rel.replace("\\", "/")
    if exclude:
        for g in exclude:
            if fnmatch(rel_n, g) or fnmatch(Path(rel_n).name, g):
                return False
    if not include:
        return True
    for g in include:
        if fnmatch(rel_n, g):
            return True
        # fnmatch doesn't treat ** like gitignore; approximate
        g2 = g.replace("**/", "*").replace("**", "*")
        if fnmatch(rel_n, g2):
            return True
        # prefix directory match: skills/foo/**
        if g.endswith("/**"):
            prefix = g[:-3]
            if rel_n == prefix or rel_n.startswith(prefix + "/"):
                return True
    return False


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return r.stdout.strip()


def _ensure_mirror(url: str, mirror: Path, ref: str) -> str:
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            [
                "clone",
                "--filter=blob:none",
                "--single-branch",
                url,
                str(mirror),
            ]
        )
    else:
        _run_git(["fetch", "--tags", "--force", "origin"], cwd=mirror)
    _run_git(["checkout", "--force", ref], cwd=mirror)
    try:
        _run_git(["pull", "--ff-only"], cwd=mirror)
    except subprocess.CalledProcessError:
        pass
    return _run_git(["rev-parse", "HEAD"], cwd=mirror)


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".md", ".mdc"}:
            continue
        if ".git" in p.parts:
            continue
        out.append(p)
    return out


def _write_notice(licenses: set[str]) -> None:
    lines = [
        "NOTICE — patterns_knowledge spike index",
        "",
        "This directory may contain excerpts from third-party repositories.",
        "Each card JSON carries source.license / path / commit.",
        "",
        "Observed licenses in this ingest:",
    ]
    for lic in sorted(licenses):
        lines.append(f"  - {lic}")
    lines.extend(
        [
            "",
            "LGPL-3.0 materials (e.g. IngvarConsulting/unica skills) remain under LGPL-3.0;",
            "do not relicense them as MIT. Full license texts live in the mirrored repos.",
            "",
        ]
    )
    NOTICE_PATH.write_text("\n".join(lines), encoding="utf-8")


def ingest(*, source_id: str | None = None, force: bool = False) -> dict[str, Any]:
    ensure_data_dirs()
    cfg = _load_sources()
    sources = cfg.get("sources") or []
    lock: dict[str, Any] = {}
    if LOCK_PATH.exists() and not force:
        lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))

    if force and CARDS_DIR.exists():
        for old in CARDS_DIR.glob("*.json"):
            old.unlink()

    stats = {"cards": 0, "sources": 0, "skipped_files": 0, "errors": []}
    licenses_seen: set[str] = set()

    for src in sources:
        sid = src["id"]
        if source_id and sid != source_id:
            continue
        stats["sources"] += 1
        include = list(src.get("include") or ["**/*.md"])
        exclude = list(src.get("exclude") or [])
        hints = dict(src.get("subdomain_hints") or {})
        license_id = str(src.get("license") or "UNKNOWN")
        trust = float(src.get("trust") or 0.5)
        licenses_seen.add(license_id)

        commit: str | None = None
        repo_url = src.get("url")
        root: Path

        if "path" in src:
            rel_path = src["path"]
            root = (PKG_DIR / rel_path).resolve()
            if not root.is_dir():
                stats["errors"].append(f"{sid}: missing path {root}")
                continue
            commit = None
        else:
            url = src["url"]
            ref = str(src.get("ref") or "main")
            mirror = MIRRORS_DIR / sid
            try:
                commit = _ensure_mirror(url, mirror, ref)
            except subprocess.CalledProcessError as e:
                stats["errors"].append(f"{sid}: git failed: {e.stderr or e}")
                continue
            root = mirror
            lock[sid] = {"commit": commit, "url": url, "ref": ref}

        for fpath in _iter_files(root):
            rel = str(fpath.relative_to(root)).replace("\\", "/")
            if not _match_globs(rel, include, exclude):
                stats["skipped_files"] += 1
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                stats["errors"].append(f"{sid}:{rel}: {e}")
                continue
            card = file_to_card(
                repo_id=sid,
                rel=rel,
                text=text,
                license_id=license_id,
                trust=trust,
                repo_url=repo_url,
                commit=commit,
                hints=hints,
            )
            if card is None:
                stats["skipped_files"] += 1
                continue
            out = CARDS_DIR / f"{card['id']}.json"
            # strip private embed helper into separate field kept for index
            out.write_text(
                json.dumps(card, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            stats["cards"] += 1

    LOCK_PATH.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notice(licenses_seen)
    unica_lic = MIRRORS_DIR / "unica-coding" / "LICENSE"
    if unica_lic.is_file():
        shutil.copy2(unica_lic, DATA_ROOT / "LICENSE.unica-LGPL-3.0")
    return stats
