"""Resolve repo / data directories for the spike."""

from __future__ import annotations

from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parents[1]
DATA_ROOT = REPO_ROOT / ".patterns-ab"
SOURCES_YAML = PKG_DIR / "sources.yaml"
MIRRORS_DIR = DATA_ROOT / "mirrors"
CARDS_DIR = DATA_ROOT / "cards"
INDEX_DIR = DATA_ROOT / "index"
LOCK_PATH = DATA_ROOT / "sources.lock.json"
FEEDBACK_DB = DATA_ROOT / "feedback.sqlite"
NOTICE_PATH = DATA_ROOT / "NOTICE"


def ensure_data_dirs() -> None:
    for p in (DATA_ROOT, MIRRORS_DIR, CARDS_DIR, INDEX_DIR):
        p.mkdir(parents=True, exist_ok=True)
