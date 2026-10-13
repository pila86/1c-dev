"""HTTP client for ``dbgs`` ``POST /e1crdbg/rdbg?cmd=…``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from adapters.debug_http.constants import (
    CODE_DBGS_UNREACHABLE,
    DEFAULT_HTTP_TIMEOUT_SEC,
    SOURCE_DEBUG,
)
from adapters.debug_http.errors import DebugHttpError
from core.diagnostics import error as diag_error


@dataclass(frozen=True)
class HttpResponse:
    """Raw HTTP response from dbgs."""

    status: int
    body: str


TransportFn = Callable[[str, bytes, dict[str, str], float], HttpResponse]


def default_transport(
    url: str,
    data: bytes,
    headers: dict[str, str],
    timeout: float,
) -> HttpResponse:
    """``urllib`` POST transport (injectable for unit tests)."""
    req = Request(url, data=data, method="POST", headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 — local dbgs URL
            return HttpResponse(
                status=int(resp.status),
                body=resp.read().decode("utf-8", errors="replace"),
            )
    except HTTPError as exc:
        data_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return HttpResponse(status=int(exc.code), body=data_body)
    except URLError as exc:
        raise DebugHttpError(
            f"dbgs не отвечает: {exc.reason}",
            code=CODE_DBGS_UNREACHABLE,
            diagnostics=[
                diag_error(
                    f"dbgs не отвечает: {exc.reason}",
                    code=CODE_DBGS_UNREACHABLE,
                    source=SOURCE_DEBUG,
                    suggestion="проверьте debug.server / host:port",
                )
            ],
        ) from exc
    except TimeoutError as exc:
        raise DebugHttpError(
            "таймаут HTTP-запроса к dbgs",
            code=CODE_DBGS_UNREACHABLE,
        ) from exc


class DebugHttpClient:
    """Thin client: ``POST {base}/e1crdbg/rdbg?cmd=…`` with ``User-Agent: 1CV8``."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_HTTP_TIMEOUT_SEC,
        transport: TransportFn | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or default_transport

    def post(self, cmd: str, body: str = "", *, dbgui: str | None = None) -> HttpResponse:
        """POST a debug command; ``pingDebugUIParams`` uses empty body + ``dbgui``."""
        query = f"cmd={cmd}"
        if dbgui:
            query += f"&dbgui={dbgui}"
        url = f"{self.base_url}/e1crdbg/rdbg?{query}"
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "application/xml",
            "User-Agent": "1CV8",
        }
        data = body.encode("utf-8") if body else b""
        return self._transport(url, data, headers, self.timeout)

    def test(self) -> HttpResponse:
        """POST ``/e1crdbg/rdbgTest?cmd=test`` (liveness)."""
        url = f"{self.base_url}/e1crdbg/rdbgTest?cmd=test"
        headers = {
            "Content-Type": "application/xml; charset=utf-8",
            "Accept": "application/xml",
            "User-Agent": "1CV8",
        }
        resp = self._transport(url, b"", headers, min(self.timeout, 10.0))
        if resp.status >= 500:
            raise DebugHttpError(
                f"dbgs test HTTP {resp.status}",
                code=CODE_DBGS_UNREACHABLE,
            )
        return resp
