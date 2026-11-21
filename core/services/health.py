"""HTTP health probes for managed services."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class HealthResult:
    url: str
    reachable: bool
    status_code: int | None = None
    error: str | None = None


def check_http(url: str, *, timeout_sec: float = 2.0) -> HealthResult:
    """GET url; reachable if HTTP response received (any 2xx/3xx/4xx)."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return HealthResult(url=url, reachable=True, status_code=int(code))
    except urllib.error.HTTPError as exc:
        # Server answered — treat as reachable for port/process presence.
        return HealthResult(url=url, reachable=True, status_code=int(exc.code))
    except Exception as exc:  # noqa: BLE001 — surface as unreachable
        return HealthResult(url=url, reachable=False, error=str(exc))
