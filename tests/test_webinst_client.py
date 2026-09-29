"""Unit tests for adapters.webinst argv helpers (#94)."""

from __future__ import annotations

from pathlib import Path

from adapters.webinst.client import (
    WebinstRunResult,
    build_url,
    delete,
    file_conn_str,
    publish,
    server_flag,
    vrd_matches_ib,
)


def test_server_flag_default() -> None:
    assert server_flag("apache24") == "-apache24"
    assert server_flag("") == "-apache24"
    assert server_flag("apache22") == "-apache22"


def test_file_conn_str(tmp_path: Path) -> None:
    db = tmp_path / "ib"
    db.mkdir()
    assert file_conn_str(db) == f'File="{db.resolve()}";'


def test_build_url() -> None:
    assert build_url(port=8315, wsdir="demo") == "http://127.0.0.1:8315/demo"
    assert build_url(port=80, wsdir="/x/") == "http://127.0.0.1:80/x"


def test_publish_argv(tmp_path: Path) -> None:
    webinst = tmp_path / "webinst"
    webinst.write_text("", encoding="utf-8")
    www = tmp_path / "www"
    db = tmp_path / "ib"
    db.mkdir()
    conf = tmp_path / "httpd.conf"
    conf.write_text("", encoding="utf-8")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> WebinstRunResult:
        captured.append(argv)
        return WebinstRunResult(0, "", "", argv)

    result = publish(
        webinst,
        server="apache24",
        wsdir="shop",
        www_dir=www,
        db_path=db,
        conf_path=conf,
        run=run,
    )
    assert result.returncode == 0
    assert captured[0][0] == str(webinst)
    assert "-apache24" in captured[0]
    assert "-wsdir" in captured[0]
    assert "shop" in captured[0]
    assert "-confPath" in captured[0]
    assert str(conf.resolve()) in captured[0]
    assert www.is_dir()


def test_delete_argv(tmp_path: Path) -> None:
    webinst = tmp_path / "webinst"
    conf = tmp_path / "httpd.conf"
    conf.write_text("", encoding="utf-8")
    captured: list[list[str]] = []

    def run(argv: list[str]) -> WebinstRunResult:
        captured.append(argv)
        return WebinstRunResult(0, "", "", argv)

    delete(
        webinst,
        server="apache24",
        wsdir="shop",
        conf_path=conf,
        run=run,
    )
    assert "-delete" in captured[0]
    assert "-wsdir" in captured[0]


def test_vrd_matches_ib(tmp_path: Path) -> None:
    www = tmp_path / "www"
    www.mkdir()
    db = tmp_path / "ib"
    db.mkdir()
    assert vrd_matches_ib(www, db) is False
    (www / "default.vrd").write_text(
        f'<?xml version="1.0"?><point ib="File=&quot;{db.resolve()}&quot;;" base="/x"/>',
        encoding="utf-8",
    )
    assert vrd_matches_ib(www, db) is True


def test_materialize_and_remove_publication(tmp_path: Path) -> None:
    from adapters.webinst.client import (
        apply_httpd_publication,
        materialize_publication,
        remove_httpd_publication,
    )

    www = tmp_path / "www"
    db = tmp_path / "ib"
    db.mkdir()
    conf = tmp_path / "httpd.conf"
    conf.write_text('ServerRoot "/tmp"\n', encoding="utf-8")
    materialize_publication(conf_path=conf, www_dir=www, wsdir="shop", db_path=db)
    text = conf.read_text(encoding="utf-8")
    assert 'Alias "/shop"' in text
    assert "1c-dev publication begin:shop" in text
    assert "SetHandler 1c-application" in text
    assert vrd_matches_ib(www, db) is True
    vrd_text = (www / "default.vrd").read_text(encoding="utf-8")
    assert 'publishByDefault="true"' in vrd_text
    assert 'publishExtensionsByDefault="true"' in vrd_text
    apply_httpd_publication(conf, wsdir="shop", www_dir=www)
    assert conf.read_text(encoding="utf-8").count('Alias "/shop"') == 1
    remove_httpd_publication(conf, wsdir="shop", www_dir=www)
    assert 'Alias "/shop"' not in conf.read_text(encoding="utf-8")
    assert not (www / "default.vrd").exists()
