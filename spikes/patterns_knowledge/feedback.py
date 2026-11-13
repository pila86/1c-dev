"""Local ±1 feedback store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from patterns_knowledge.paths import FEEDBACK_DB, ensure_data_dirs


def _conn() -> sqlite3.Connection:
    ensure_data_dirs()
    c = sqlite3.connect(FEEDBACK_DB)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            card_id TEXT PRIMARY KEY,
            score INTEGER NOT NULL DEFAULT 0,
            n INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    c.commit()
    return c


def vote(card_id: str, delta: int) -> dict[str, int | str]:
    if delta not in (-1, 1):
        raise ValueError("vote must be +1 or -1")
    with _conn() as c:
        row = c.execute(
            "SELECT score, n FROM feedback WHERE card_id = ?", (card_id,)
        ).fetchone()
        if row:
            score, n = int(row[0]) + delta, int(row[1]) + 1
            c.execute(
                "UPDATE feedback SET score = ?, n = ? WHERE card_id = ?",
                (score, n, card_id),
            )
        else:
            score, n = delta, 1
            c.execute(
                "INSERT INTO feedback(card_id, score, n) VALUES (?, ?, ?)",
                (card_id, score, n),
            )
        c.commit()
    return {"id": card_id, "feedback_score": score, "feedback_n": n}


def scores_map() -> dict[str, tuple[int, int]]:
    if not Path(FEEDBACK_DB).exists():
        return {}
    with _conn() as c:
        rows = c.execute("SELECT card_id, score, n FROM feedback").fetchall()
    return {str(r[0]): (int(r[1]), int(r[2])) for r in rows}
