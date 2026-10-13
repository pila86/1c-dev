"""Constants for HTTP Debug Protocol adapter (ADR-031 / #138)."""

from __future__ import annotations

# Namespaces (spike #135 / platform 8.3)
NS_RDBG = "http://v8.1c.ru/8.3/debugger/debugRDBGRequestResponse"
NS_BD = "http://v8.1c.ru/8.3/debugger/debugBaseData"
NS_BP = "http://v8.1c.ru/8.3/debugger/debugBreakpoints"
NS_CALC = "http://v8.1c.ru/8.3/debugger/debugCalculations"
NS_AA = "http://v8.1c.ru/8.3/debugger/debugAutoAttach"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"

DEFAULT_ALIAS = "DefAlias"
DEFAULT_HOST = "localhost"
DEFAULT_PING_INTERVAL_SEC = 0.5
DEFAULT_HTTP_TIMEOUT_SEC = 30.0
DEFAULT_WAIT_TIMEOUT_SEC = 30.0
DEFAULT_ATTACH_RETRIES = 5
DEFAULT_AUTO_ATTACH_TYPES: tuple[str, ...] = (
    "Client",
    "ManagedClient",
    "Server",
    "ServerEmulation",
)

# Module UUID index cache (ADR-031 / #139) under ``.1c-dev/debug/``
DEBUG_STATE_DIR_NAME = "debug"
MODULES_CACHE_FILENAME = "modules-cache.json"
MODULES_CACHE_VERSION = 1

# Canonical propertyID for module kinds (spike #135 / MIT ModulePropertyID)
PROPERTY_ID_COMMON_MODULE = "d5963243-262e-4398-b4d7-fb16d06484f6"
PROPERTY_ID_APPLICATION_MODULE = "d22e852a-cf8a-4f77-8ccb-3548e7792bea"

MODULE_PROPERTY_IDS: dict[str, str] = {
    "CommonModule": PROPERTY_ID_COMMON_MODULE,
    "ManagedApplicationModule": PROPERTY_ID_APPLICATION_MODULE,
    "ApplicationModule": PROPERTY_ID_APPLICATION_MODULE,
}

# Diagnostics (ADR-031) — source="debug" for product; adapter raises with these codes
CODE_DBGS_MISSING = "1CD001"
CODE_DBGS_UNREACHABLE = "1CD002"
CODE_NO_SESSION = "1CD003"
CODE_MODULE_UNRESOLVED = "1CD004"
CODE_WAIT_TIMEOUT = "1CD005"
CODE_NOT_STOPPED = "1CD006"
CODE_NO_TARGETS = "1CD007"

SOURCE_DEBUG = "debug"
