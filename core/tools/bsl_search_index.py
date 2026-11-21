"""Download HF corpus and bulk-load into Elasticsearch for bsl-search (Этап 3)."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from core.diagnostics import Diagnostic, error, info, warning
from core.tools.catalog import ToolRecipe
from core.tools.install import expand_template, resolve_env_vars
from core.tools.paths import data_share_dir

ProgressCb = Callable[[str], None] | None

HF_REPO_DEFAULT = "pupkaZALUPKA/1c-bsl-dataset"
HF_FILE_DEFAULT = "units_curated.jsonl"
MAX_BODY_LEN_DEFAULT = 30_000


def tool_data_dir(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    return data_share_dir(env=env, platform=platform) / tool_id


def normalize_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n").strip()


def build_search_text(row: dict[str, Any], body: str) -> str:
    fields = (
        ("Имя", row.get("name")),
        ("Параметры", row.get("params")),
        ("Тип модуля", row.get("module_type")),
        ("Директива", row.get("directive")),
        ("Вид", row.get("kind")),
        ("Документация", row.get("doc")),
        ("Код", body),
    )
    return "\n".join(f"{label}: {value}" for label, value in fields if value)


def normalize_row(
    row: dict[str, Any],
    *,
    max_body_len: int = MAX_BODY_LEN_DEFAULT,
) -> dict[str, Any] | None:
    """Normalize HF unit row; return None if rejected."""
    if not isinstance(row.get("body"), str) or not isinstance(row.get("name"), str):
        return None
    body = normalize_body(row["body"])
    if not body or len(body) > max_body_len:
        return None
    result = dict(row)
    result["body"] = body
    result["body_len"] = len(body)
    result["exact_hash"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    result["id"] = hashlib.sha256(
        f"{row.get('repo', '')}\n{row.get('file', '')}\n{row['name']}\n{body}".encode()
    ).hexdigest()
    result["search_text"] = build_search_text(row, body)
    result.setdefault("source_type", "code")
    result.setdefault("authority", "implementation")
    return result


def _index_cfg(recipe: ToolRecipe) -> dict[str, Any]:
    raw = recipe.raw.get("index")
    return raw if isinstance(raw, dict) else {}


def corpus_jsonl_path(
    tool_id: str,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> Path:
    return tool_data_dir(tool_id, env=env, platform=platform) / "units_curated.normalized.jsonl"


def download_huggingface_corpus(
    recipe: ToolRecipe,
    *,
    env: dict[str, str] | None = None,
    platform: str | None = None,
    progress: ProgressCb = None,
    force: bool = False,
) -> tuple[bool, Path | None, list[Diagnostic]]:
    """Download HF file and write normalized JSONL under data share."""
    cfg = _index_cfg(recipe)
    if str(cfg.get("provider") or "") != "huggingface":
        return True, None, []

    out = corpus_jsonl_path(recipe.id, env=env, platform=platform)
    if out.is_file() and out.stat().st_size > 0 and not force:
        return True, out, [
            info(
                f"корпус уже скачан: {out}",
                code="1CX000",
                source="tools",
            )
        ]

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return False, None, [
            error(
                "пакет huggingface_hub не установлен",
                code="1CX007",
                source="tools",
                suggestion="poetry install / pip install huggingface_hub",
            )
        ]

    repo_id = str(cfg.get("repo_id") or HF_REPO_DEFAULT)
    filename = str(cfg.get("filename") or HF_FILE_DEFAULT)
    token = None
    environ = env if env is not None else os.environ
    if environ.get("HF_TOKEN"):
        token = environ["HF_TOKEN"]

    cache_dir = tool_data_dir(recipe.id, env=env, platform=platform) / "hf-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"Скачиваю {repo_id}/{filename} с HuggingFace…")
    try:
        raw_path = Path(
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                repo_type=str(cfg.get("repo_type") or "dataset"),
                token=token,
                local_dir=str(cache_dir),
            )
        )
    except Exception as exc:  # noqa: BLE001 — surface as diagnostic
        return False, None, [
            error(
                f"HuggingFace download failed: {exc}",
                code="1CX006",
                source="tools",
                suggestion="Проверьте сеть; при rate limit задайте HF_TOKEN",
            )
        ]

    if progress:
        progress(f"Нормализую корпус → {out}…")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    written = 0
    seen: set[str] = set()
    try:
        with raw_path.open(encoding="utf-8") as source, tmp.open(
            "w", encoding="utf-8"
        ) as target:
            for line in source:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                normalized = normalize_row(row)
                if normalized is None:
                    continue
                digest = str(normalized["exact_hash"])
                if digest in seen:
                    continue
                seen.add(digest)
                target.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                written += 1
                if progress and written % 50_000 == 0:
                    progress(f"нормализовано {written} методов…")
        os.replace(tmp, out)
    except OSError as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False, None, [
            error(f"не удалось записать корпус: {exc}", code="1CX006", source="tools"),
        ]

    return True, out, [
        info(
            f"корпус готов: {written} методов → {out}",
            code="1CX000",
            source="tools",
        )
    ]


def _es_mapping() -> dict[str, Any]:
    # dense_vector reserved for later embed; BM25 works without populating it.
    return {
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "repo": {"type": "keyword"},
                "file": {"type": "keyword"},
                "module_type": {"type": "keyword"},
                "directive": {"type": "keyword"},
                "kind": {"type": "keyword"},
                "name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                    "analyzer": "russian",
                },
                "params": {"type": "text", "analyzer": "russian"},
                "export": {"type": "boolean"},
                "doc": {"type": "text", "analyzer": "russian"},
                "body": {"type": "text"},
                "search_text": {"type": "text", "analyzer": "russian"},
                "body_len": {"type": "integer"},
                "exact_hash": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "authority": {"type": "keyword"},
                "is_bsp": {"type": "boolean"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": 1536,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        }
    }


def _es_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: Any = None,
    timeout: int = 60,
) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    api_key = os.environ.get("ELASTICSEARCH_API_KEY")
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        return json.loads(body) if body else None


def es_doc_count(base_url: str, index: str) -> int | None:
    try:
        result = _es_request(base_url, f"/{index}/_count")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    count = result.get("count")
    return int(count) if isinstance(count, int) else None


def _batches(rows: Iterable[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def bulk_load_corpus(
    jsonl_path: Path,
    *,
    base_url: str,
    index: str,
    batch_size: int = 500,
    progress: ProgressCb = None,
    force: bool = False,
) -> tuple[bool, int, list[Diagnostic]]:
    """Create index if missing and bulk-load JSONL. Skip if non-empty unless force."""
    try:
        _es_request(base_url, "/")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return False, 0, [
            error(
                f"Elasticsearch недоступен ({base_url}): {exc}",
                code="1CX005",
                source="tools",
                suggestion="1c-dev services up bsl-search",
            )
        ]

    existing = es_doc_count(base_url, index)
    if existing is not None and existing > 0 and not force:
        return True, existing, [
            info(
                f"индекс {index} уже содержит {existing} docs — skip bulk",
                code="1CX000",
                source="tools",
                suggestion="BSL_SEARCH_REINDEX=1 для перезагрузки",
            )
        ]

    try:
        _es_request(base_url, f"/{index}")
        index_exists = True
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return False, 0, [
                error(f"ES index check failed: {exc}", code="1CX006", source="tools"),
            ]
        index_exists = False
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, 0, [
            error(f"ES index check failed: {exc}", code="1CX006", source="tools"),
        ]

    if force and index_exists:
        if progress:
            progress(f"Удаляю индекс {index} (reindex)…")
        try:
            _es_request(base_url, f"/{index}", method="DELETE")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return False, 0, [
                error(f"не удалось удалить индекс: {exc}", code="1CX006", source="tools"),
            ]
        index_exists = False

    if not index_exists:
        if progress:
            progress(f"Создаю индекс {index}…")
        try:
            _es_request(base_url, f"/{index}", method="PUT", payload=_es_mapping())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return False, 0, [
                error(f"не удалось создать индекс: {exc}", code="1CX006", source="tools"),
            ]

    if not jsonl_path.is_file():
        return False, 0, [
            error(
                f"корпус не найден: {jsonl_path}",
                code="1CX007",
                source="tools",
                suggestion="1c-dev tools install bsl-search",
            )
        ]

    if progress:
        progress(f"Bulk-load {jsonl_path.name} → {index}…")
    total = 0
    try:
        with jsonl_path.open(encoding="utf-8") as source:
            rows = (json.loads(line) for line in source if line.strip())
            for batch in _batches(rows, batch_size):
                bulk_lines: list[str] = []
                for row in batch:
                    doc_id = str(row.get("id") or "")
                    if not doc_id:
                        continue
                    bulk_lines.append(
                        json.dumps(
                            {"index": {"_index": index, "_id": doc_id}},
                            ensure_ascii=False,
                        )
                    )
                    bulk_lines.append(json.dumps(row, ensure_ascii=False))
                if not bulk_lines:
                    continue
                payload = ("\n".join(bulk_lines) + "\n").encode("utf-8")
                req = urllib.request.Request(
                    base_url.rstrip("/") + "/_bulk",
                    data=payload,
                    headers={"Content-Type": "application/x-ndjson"},
                    method="POST",
                )
                api_key = os.environ.get("ELASTICSEARCH_API_KEY")
                if api_key:
                    req.add_header("Authorization", f"ApiKey {api_key}")
                with urllib.request.urlopen(req, timeout=180) as response:
                    result = json.loads(response.read())
                if result.get("errors"):
                    errors = [
                        item
                        for item in result.get("items", [])
                        if item.get("index", {}).get("status", 500) >= 300
                    ]
                    return False, total, [
                        error(
                            f"bulk indexing failed ({len(errors)} docs)",
                            code="1CX006",
                            source="tools",
                        )
                    ]
                total += len(batch)
                if progress and total % 25_000 == 0:
                    progress(f"загружено {total} docs…")
        _es_request(base_url, f"/{index}/_refresh", method="POST")
    except (
        OSError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ) as exc:
        return False, total, [
            error(f"bulk load failed: {exc}", code="1CX006", source="tools"),
        ]

    return True, total, [
        info(
            f"индекс {index}: загружено {total} docs",
            code="1CX000",
            source="tools",
        )
    ]


def ensure_index_loaded(
    recipe: ToolRecipe,
    tool_dir: Path,
    *,
    progress: ProgressCb = None,
) -> tuple[bool, list[Diagnostic]]:
    """After services up: load corpus into ES if configured."""
    cfg = _index_cfg(recipe)
    if str(cfg.get("load_on") or "") != "services_up":
        return True, []
    if str(cfg.get("provider") or "") != "huggingface":
        return True, []

    env_vars = resolve_env_vars(tool_dir)
    es_url_tmpl = str(cfg.get("es_url") or "http://127.0.0.1:${BSL_SEARCH_ES_PORT:-19200}")
    es_url = expand_template(es_url_tmpl, env_vars)
    index = str(cfg.get("es_index") or env_vars.get("ELASTICSEARCH_INDEX") or "bsl-methods")
    force = str(env_vars.get("BSL_SEARCH_REINDEX") or "").strip() in ("1", "true", "yes")

    jsonl = corpus_jsonl_path(recipe.id)
    if not jsonl.is_file():
        ok, path, diags = download_huggingface_corpus(recipe, progress=progress)
        if not ok or path is None:
            return False, diags
        jsonl = path

    ok, _count, diags = bulk_load_corpus(
        jsonl,
        base_url=es_url,
        index=index,
        progress=progress,
        force=force,
    )
    if ok and force:
        # Clear reindex flag hint — user edits .env manually; just warn once.
        diags.append(
            warning(
                "BSL_SEARCH_REINDEX был включён — сбросьте в 0 после успешной загрузки",
                code="1CX000",
                source="tools",
            )
        )
    return ok, diags
