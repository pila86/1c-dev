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
# Fast ping while arming BP around client spawn (DAP uses ~25ms).
ARM_PING_INTERVAL_SEC = 0.025
# ``pingDebugUIParams`` is a server-side long-poll: idle ping answers 204 after ~5 s.
# Client timeout must exceed that, otherwise events are lost (spike #135 §5a).
PING_LONG_POLL_SEC = 5.0
PING_HTTP_TIMEOUT_SEC = 12.0
# eval result delivered via ping instead of the POST body: how long to wait for it
EVAL_ASYNC_WAIT_SEC = 8.0
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

# Canonical propertyID for module kinds (spike #135 / go1cover ModulePropertyID;
# CommonModule=SimpleModule, ApplicationModule=ManagedApplicationModule).
PROPERTY_ID_COMMON_MODULE = "d5963243-262e-4398-b4d7-fb16d06484f6"
PROPERTY_ID_APPLICATION_MODULE = "d22e852a-cf8a-4f77-8ccb-3548e7792bea"
PROPERTY_ID_OBJECT_MODULE = "a637f77f-3840-441d-a1c3-699c8c5cb7e0"
PROPERTY_ID_MANAGER_MODULE = "d1b64a2c-8078-4982-8190-8f81aefda192"
PROPERTY_ID_FORM_MODULE = "32e087ab-1491-49b6-aba7-43571b41ac2b"
PROPERTY_ID_RECORD_SET_MODULE = "9f36fd70-4bf4-47f6-b235-935f73aab43f"

MODULE_PROPERTY_IDS: dict[str, str] = {
    "CommonModule": PROPERTY_ID_COMMON_MODULE,
    "ManagedApplicationModule": PROPERTY_ID_APPLICATION_MODULE,
    "ApplicationModule": PROPERTY_ID_APPLICATION_MODULE,
    "ObjectModule": PROPERTY_ID_OBJECT_MODULE,
    "ManagerModule": PROPERTY_ID_MANAGER_MODULE,
    "FormModule": PROPERTY_ID_FORM_MODULE,
    "RecordSetModule": PROPERTY_ID_RECORD_SET_MODULE,
}

# Diagnostics (ADR-031) — source="debug" for product; adapter raises with these codes
CODE_DBGS_MISSING = "1CD001"
CODE_DBGS_UNREACHABLE = "1CD002"
CODE_NO_SESSION = "1CD003"
CODE_MODULE_UNRESOLVED = "1CD004"
CODE_WAIT_TIMEOUT = "1CD005"
CODE_NOT_STOPPED = "1CD006"
CODE_NO_TARGETS = "1CD007"
CODE_CLIENT_EXITED = "1CD016"

SOURCE_DEBUG = "debug"
