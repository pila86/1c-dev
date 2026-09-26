"""Unit tests for docs.search / docs.get (ADR-017 / #51)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from adapters.docs.hbk import find_hbk
from adapters.docs.resolve import resolve_jar
from adapters.docs.run import DocsFacadeError
from cli.main import app
from core.docs import get_docs, search_docs
from core.exit_codes import ENV_UNAVAILABLE, SUCCESS
from core.toolchain.cache import docs_cache_dir

runner = CliRunner()


def _write_project(tmp_path: Path, *, version: str = "8.3.27") -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "src" / "cf").mkdir(parents=True)
    manifest = {
        "project": {"name": "Demo", "type": "configuration"},
        "platform": {"version": version},
        "source": {"format": "xml", "path": "src/cf"},
    }
    (root / "1c.project.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True),
        encoding="utf-8",
    )
    return root


def test_find_hbk_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hbk = tmp_path / "shcntx_ru.hbk"
    hbk.write_bytes(b"hbk")
    monkeypatch.setenv("ONEC_HBK_PATH", str(hbk))
    result = find_hbk(None, env={"ONEC_HBK_PATH": str(hbk)})
    assert result.found is True
    assert result.path == hbk.resolve()
    assert result.source == "env"


def test_find_hbk_platform_layouts(tmp_path: Path) -> None:
    install = tmp_path / "8.3.27.1549"
    install.mkdir()
    assert find_hbk(install).found is False

    hbk = install / "shcntx_ru.hbk"
    hbk.write_bytes(b"x")
    hit = find_hbk(install)
    assert hit.found is True
    assert hit.path == hbk.resolve()

    install2 = tmp_path / "8.3.27.2000"
    (install2 / "bin").mkdir(parents=True)
    hbk2 = install2 / "bin" / "shcntx_ru.hbk"
    hbk2.write_bytes(b"y")
    hit2 = find_hbk(install2)
    assert hit2.found is True
    assert hit2.path == hbk2.resolve()


def test_resolve_jar_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    jar = tmp_path / "docs-facade.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setenv("ONEC_DOCS_FACADE_JAR", str(jar))
    result = resolve_jar(env={"ONEC_DOCS_FACADE_JAR": str(jar)})
    assert result.found is True
    assert result.path == jar.resolve()


def test_docs_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert docs_cache_dir(platform="linux") == tmp_path / "xdg" / "1c-dev" / "docs"


def test_search_docs_no_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = search_docs(tmp_path, "Массив")
    assert result.status == "error"
    assert any(d.get("code") == "1CX001" for d in result.diagnostics)


def test_search_docs_no_hbk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_project(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("ONEC_HBK_PATH", raising=False)

    class FakePlatform:
        path = None

    class FakeDiscovery:
        platform = FakePlatform()

    monkeypatch.setattr(
        "core.docs.run.discover_environment",
        lambda: FakeDiscovery(),
    )
    result = search_docs(root, "Массив")
    assert result.status == "error"
    assert any(d.get("code") == "1CX002" for d in result.diagnostics)


def test_search_docs_lazy_ensure_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_project(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    hbk = tmp_path / "shcntx_ru.hbk"
    hbk.write_bytes(b"hbk")
    monkeypatch.setenv("ONEC_HBK_PATH", str(hbk))

    class FakePlatform:
        path = tmp_path

    class FakeDiscovery:
        platform = FakePlatform()

    monkeypatch.setattr(
        "core.docs.run.discover_environment",
        lambda: FakeDiscovery(),
    )

    ensure_calls: list[dict[str, Any]] = []

    def fake_ensure(**kwargs: Any) -> dict[str, Any]:
        ensure_calls.append(kwargs)
        index_dir: Path = kwargs["index_dir"]
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "meta.json").write_text("{}", encoding="utf-8")
        (index_dir / "index.json").write_text(
            json.dumps({"entries": []}),
            encoding="utf-8",
        )
        return {
            "status": "ok",
            "index": {"version": "8.3.27", "built": True, "path": str(index_dir)},
        }

    def fake_search(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "status": "ok",
            "hits": [
                {
                    "name": "Массив",
                    "kind": "collection",
                    "score": 3.0,
                    "snippet": "Универсальная коллекция",
                }
            ],
        }

    result = search_docs(
        root,
        "Массив",
        env={"ONEC_HBK_PATH": str(hbk), "XDG_CACHE_HOME": str(tmp_path / "xdg")},
        ensure_fn=fake_ensure,
        search_fn=fake_search,
    )
    assert result.status == "ok"
    assert result.platform_version == "8.3.27"
    assert result.index_built is True
    assert len(result.hits) == 1
    assert result.hits[0]["name"] == "Массив"
    assert any(d.get("code") == "1CX010" for d in result.diagnostics)
    assert len(ensure_calls) == 1

    # Second call: meta exists → no "building" info, ensure still invoked (facade checks freshness)
    result2 = search_docs(
        root,
        "Массив",
        env={"ONEC_HBK_PATH": str(hbk), "XDG_CACHE_HOME": str(tmp_path / "xdg")},
        ensure_fn=fake_ensure,
        search_fn=fake_search,
    )
    assert result2.status == "ok"
    assert not any(d.get("code") == "1CX010" for d in result2.diagnostics)
    assert len(ensure_calls) == 2


def test_get_docs_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_project(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    hbk = tmp_path / "shcntx_ru.hbk"
    hbk.write_bytes(b"hbk")

    class FakePlatform:
        path = tmp_path

    class FakeDiscovery:
        platform = FakePlatform()

    monkeypatch.setattr(
        "core.docs.run.discover_environment",
        lambda: FakeDiscovery(),
    )

    def fake_ensure(**kwargs: Any) -> dict[str, Any]:
        index_dir: Path = kwargs["index_dir"]
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "meta.json").write_text("{}", encoding="utf-8")
        return {"status": "ok", "index": {"built": False, "path": str(index_dir)}}

    def fake_get(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise DocsFacadeError("Запись не найдена: НетТакого", code="1CX004")

    result = get_docs(
        root,
        "НетТакого",
        env={"ONEC_HBK_PATH": str(hbk), "XDG_CACHE_HOME": str(tmp_path / "xdg")},
        ensure_fn=fake_ensure,
        get_fn=fake_get,
    )
    assert result.status == "error"
    assert any(d.get("code") == "1CX004" for d in result.diagnostics)


def test_get_docs_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_project(tmp_path)
    hbk = tmp_path / "shcntx_ru.hbk"
    hbk.write_bytes(b"hbk")

    class FakePlatform:
        path = tmp_path

    class FakeDiscovery:
        platform = FakePlatform()

    monkeypatch.setattr(
        "core.docs.run.discover_environment",
        lambda: FakeDiscovery(),
    )

    def fake_ensure(**kwargs: Any) -> dict[str, Any]:
        index_dir: Path = kwargs["index_dir"]
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "meta.json").write_text("{}", encoding="utf-8")
        return {"status": "ok", "index": {"built": False}}

    def fake_get(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "status": "ok",
            "entry": {
                "qualifiedName": "Массив.Добавить",
                "kind": "method",
                "description": "Добавляет элемент",
            },
        }

    result = get_docs(
        root,
        "Массив.Добавить",
        env={"ONEC_HBK_PATH": str(hbk), "XDG_CACHE_HOME": str(tmp_path / "xdg")},
        ensure_fn=fake_ensure,
        get_fn=fake_get,
    )
    assert result.status == "ok"
    assert result.entry is not None
    assert result.entry["qualifiedName"] == "Массив.Добавить"
    payload = result.to_payload()
    assert payload["platformVersion"] == "8.3.27"
    assert "entry" in payload


def test_cli_docs_search_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_project(tmp_path)

    def fake_search(start: Path | None, query: str, **kwargs: Any) -> Any:
        del start, query, kwargs
        from core.docs import DocsResult

        return DocsResult(
            status="ok",
            platform_version="8.3.27",
            hits=[{"name": "Массив", "kind": "collection", "score": 1.0, "snippet": ""}],
        )

    monkeypatch.setattr("cli.docs.search_docs", fake_search)
    result = runner.invoke(
        app,
        ["docs", "search", "Массив", "--path", str(root), "--output", "json"],
    )
    assert result.exit_code == SUCCESS
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["hits"][0]["name"] == "Массив"


def test_cli_docs_missing_hbk_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_project(tmp_path)

    def fake_search(start: Path | None, query: str, **kwargs: Any) -> Any:
        del start, query, kwargs
        from core.diagnostics import error
        from core.docs import DocsResult

        return DocsResult(
            status="error",
            diagnostics=[error("HBK не найден", code="1CX002", source="docs")],
        )

    monkeypatch.setattr("cli.docs.search_docs", fake_search)
    result = runner.invoke(
        app,
        ["docs", "search", "X", "--path", str(root), "--output", "json"],
    )
    assert result.exit_code == ENV_UNAVAILABLE


@pytest.mark.integration
def test_docs_facade_jar_integration(tmp_path: Path) -> None:
    """Smoke: run built docs-facade ensure/search/get when jar + HBK available."""
    import os
    import shutil
    import subprocess

    from adapters.docs.resolve import resolve_java
    from adapters.platform import discover_environment

    jar_candidates = [
        Path("tools/docs-facade/build/libs/docs-facade.jar"),
        Path(os.environ.get("ONEC_DOCS_FACADE_JAR", "")),
    ]
    jar = next((p for p in jar_candidates if p.is_file()), None)
    if jar is None:
        pytest.skip("docs-facade.jar не собран (tools/docs-facade или ONEC_DOCS_FACADE_JAR)")

    java = resolve_java()
    if not java.found or java.path is None:
        pytest.skip("Java 21+ не найдена")

    hbk_env = os.environ.get("ONEC_HBK_PATH", "").strip()
    hbk: Path | None = Path(hbk_env) if hbk_env else None
    if hbk is None or not hbk.is_file():
        discovery = discover_environment()
        from adapters.docs.hbk import find_hbk as _find

        resolved = _find(discovery.platform.path)
        hbk = resolved.path if resolved.found else None
    if hbk is None or not hbk.is_file():
        pytest.skip("HBK (shcntx_ru.hbk) не найден")

    index_dir = tmp_path / "idx"
    env = os.environ.copy()
    common = [
        str(java.path),
        "-jar",
        str(jar),
    ]
    ensure = subprocess.run(
        [
            *common,
            "ensure",
            "--index-dir",
            str(index_dir),
            "--platform-version",
            "8.3.27",
            "--hbk",
            str(hbk),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert ensure.returncode == 0, ensure.stderr or ensure.stdout
    ensure_payload = json.loads(ensure.stdout)
    assert ensure_payload["status"] == "ok"

    search = subprocess.run(
        [
            *common,
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "Массив",
            "--limit",
            "5",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert search.returncode == 0, search.stderr or search.stdout
    search_payload = json.loads(search.stdout)
    assert search_payload["status"] == "ok"
    assert isinstance(search_payload.get("hits"), list)

    get_proc = subprocess.run(
        [
            *common,
            "get",
            "--index-dir",
            str(index_dir),
            "--name",
            "Массив",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert get_proc.returncode == 0, get_proc.stderr or get_proc.stdout
    get_payload = json.loads(get_proc.stdout)
    assert get_payload["status"] == "ok"
    assert get_payload["entry"]["qualifiedName"] == "Массив"

    # cleanup large index from tmp is automatic; avoid copying to user cache
    shutil.rmtree(index_dir, ignore_errors=True)
