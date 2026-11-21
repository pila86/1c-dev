"""Unit tests for publish path helpers (bind / URL host)."""

from __future__ import annotations

from core.publish.paths import (
    DEFAULT_HTTP_ADDRESS,
    DEFAULT_URL_HOST,
    DEFAULT_WEBINST_ADDRESS,
    url_host_for_bind,
)


def test_default_bind_addresses_are_wildcard() -> None:
    assert DEFAULT_WEBINST_ADDRESS == "0.0.0.0"
    assert DEFAULT_HTTP_ADDRESS == "0.0.0.0"


def test_url_host_for_bind_wildcard() -> None:
    assert url_host_for_bind("0.0.0.0") == DEFAULT_URL_HOST
    assert url_host_for_bind("::") == DEFAULT_URL_HOST
    assert url_host_for_bind(" 0.0.0.0 ") == DEFAULT_URL_HOST


def test_url_host_for_bind_concrete() -> None:
    assert url_host_for_bind("192.168.1.10") == "192.168.1.10"
    assert url_host_for_bind("127.0.0.1") == "127.0.0.1"
    assert url_host_for_bind("") == DEFAULT_URL_HOST
