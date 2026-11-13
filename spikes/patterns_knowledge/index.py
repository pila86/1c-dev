"""Build retrieval index and search cards."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from patterns_knowledge.feedback import scores_map
from patterns_knowledge.normalize import embed_text
from patterns_knowledge.paths import CARDS_DIR, INDEX_DIR, ensure_data_dirs

_TOKEN = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9_]{2,}")


def _load_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if not CARDS_DIR.is_dir():
        return cards
    for p in sorted(CARDS_DIR.glob("*.json")):
        card = json.loads(p.read_text(encoding="utf-8"))
        if card.get("purpose") != "coding":
            continue
        if "_embed_text" not in card:
            card["_embed_text"] = embed_text(card)
        cards.append(card)
    return cards


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _tfidf_matrix(docs: list[list[str]]) -> tuple[list[dict[str, float]], dict[str, float]]:
    df: Counter[str] = Counter()
    for tok in docs:
        df.update(set(tok))
    n = len(docs) or 1
    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vecs: list[dict[str, float]] = []
    for tok in docs:
        tf = Counter(tok)
        length = float(sum(tf.values()) or 1)
        vec = {t: (cnt / length) * idf[t] for t, cnt in tf.items()}
        vecs.append(vec)
    return vecs, idf


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    num = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return num / (na * nb)


def _embed_http(texts: list[str]) -> list[list[float]] | None:
    base = os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("EMBEDDING_MODEL") or "nomic-embed-text"
    key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY") or "ollama"
    if not base:
        return None
    url = base.rstrip("/") + "/embeddings"
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    items = data.get("data") or []
    items = sorted(items, key=lambda x: x.get("index", 0))
    return [list(map(float, it.get("embedding") or [])) for it in items]


def _l2_normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def reindex(*, full: bool = False) -> dict[str, Any]:
    ensure_data_dirs()
    cards = _load_cards()
    texts = [c.get("_embed_text") or embed_text(c) for c in cards]
    backend = "tfidf"
    vectors: list[Any] = []
    emb = _embed_http(texts) if texts else None
    if emb and len(emb) == len(cards) and all(emb):
        backend = "http_embeddings"
        vectors = [_l2_normalize(v) for v in emb]
    else:
        docs = [_tokenize(t) for t in texts]
        vectors, _idf = _tfidf_matrix(docs)

    payload = {
        "backend": backend,
        "model": os.environ.get("EMBEDDING_MODEL") if backend == "http_embeddings" else "tfidf",
        "ids": [c["id"] for c in cards],
        "subdomains": [c.get("subdomain") for c in cards],
        "vectors": vectors,
        "full_rebuild": full,
    }
    out = INDEX_DIR / "index.json"
    # tfidf vectors are dicts — ok in json; dense lists too
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    meta = {
        "backend": backend,
        "n_cards": len(cards),
        "path": str(out),
    }
    (INDEX_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _load_index() -> dict[str, Any] | None:
    p = INDEX_DIR / "index.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def get_card(card_id: str) -> dict[str, Any] | None:
    path = CARDS_DIR / f"{card_id}.json"
    if not path.is_file():
        # fuzzy: unique prefix
        matches = list(CARDS_DIR.glob(f"{card_id}*.json"))
        if len(matches) == 1:
            path = matches[0]
        else:
            return None
    card = json.loads(path.read_text(encoding="utf-8"))
    card.pop("_embed_text", None)
    fb = scores_map().get(card["id"])
    if fb:
        card.setdefault("quality", {})
        card["quality"]["feedback_score"] = fb[0]
        card["quality"]["feedback_n"] = fb[1]
    return card


def search(
    query: str,
    *,
    task: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    cards = {c["id"]: c for c in _load_cards()}
    idx = _load_index()
    if not idx or not cards:
        return []

    ids: list[str] = idx["ids"]
    vectors = idx["vectors"]
    backend = idx.get("backend")
    fbmap = scores_map()

    scored: list[tuple[float, str]] = []
    if backend == "http_embeddings":
        qv = _embed_http([query])
        if not qv or not qv[0]:
            backend = "tfidf"
        else:
            qn = _l2_normalize(qv[0])
            for i, cid in enumerate(ids):
                card = cards.get(cid)
                if not card:
                    continue
                if task and card.get("subdomain") != task and task not in (
                    card.get("subdomain") or ""
                ):
                    # soft filter: still allow but penalize
                    pass
                sim = _dot(qn, vectors[i]) if i < len(vectors) else 0.0
                scored.append((sim, cid))

    if backend != "http_embeddings" or not scored:
        scored = []
        qtok = _tokenize(query)
        q_vec = {t: float(c) for t, c in Counter(qtok).items()}
        for i, cid in enumerate(ids):
            card = cards.get(cid)
            if not card:
                continue
            doc_tf = Counter(_tokenize(card.get("_embed_text") or embed_text(card)))
            doc_vec = {t: float(c) for t, c in doc_tf.items()}
            sim = _cosine(doc_vec, q_vec)
            scored.append((sim, cid))

    # re-rank
    ranked: list[tuple[float, str]] = []
    for sim, cid in scored:
        card = cards[cid]
        src = card.get("source") or {}
        trust = float(src.get("trust") or 0.5)
        stars = float((card.get("quality") or {}).get("stars_repo") or 0)
        fb_score, fb_n = fbmap.get(cid, (0, 0))
        fb_term = (fb_score / max(fb_n, 1)) * 0.05 if fb_n else 0.0
        task_boost = 0.2 if task and card.get("subdomain") == task else 0.0
        path = (src.get("path") or "").lower()
        skill_boost = 0.25 if path.endswith("skill.md") else 0.0
        # keyword boost on title/summary/path
        blob = (
            (card.get("title") or "")
            + " "
            + (card.get("summary") or "")
            + " "
            + path
        ).lower()
        kw = 0.0
        for w in _tokenize(query):
            if w in blob:
                kw += 0.03
        final = (
            0.55 * sim
            + 0.2 * trust
            + fb_term
            + 0.02 * math.log1p(stars)
            + task_boost
            + skill_boost
            + min(kw, 0.3)
        )
        ranked.append((final, cid))

    ranked.sort(key=lambda x: x[0], reverse=True)
    hits: list[dict[str, Any]] = []
    for score, cid in ranked[: max(1, limit)]:
        card = cards[cid]
        src = card.get("source") or {}
        hits.append(
            {
                "id": cid,
                "title": card.get("title"),
                "summary": card.get("summary"),
                "subdomain": card.get("subdomain"),
                "score": round(float(score), 4),
                "source": {
                    "repo_url": src.get("repo_url"),
                    "path": src.get("path"),
                    "license": src.get("license"),
                    "commit": src.get("commit"),
                },
            }
        )
    return hits
