"""HTTP Debug Protocol adapter for ``dbgs`` (ADR-031 / #138).

XML/HTTP client, ping/events, session — без module UUID index (#139) и без core/CLI.
"""

from __future__ import annotations

from adapters.debug_http import xml_build, xml_parse
from adapters.debug_http.client import DebugHttpClient, HttpResponse, TransportFn
from adapters.debug_http.constants import (
    CODE_DBGS_MISSING,
    CODE_DBGS_UNREACHABLE,
    CODE_MODULE_UNRESOLVED,
    CODE_NO_SESSION,
    CODE_NO_TARGETS,
    CODE_NOT_STOPPED,
    CODE_WAIT_TIMEOUT,
    DEFAULT_ALIAS,
    DEFAULT_AUTO_ATTACH_TYPES,
    DEFAULT_PING_INTERVAL_SEC,
    DEFAULT_WAIT_TIMEOUT_SEC,
    MODULE_PROPERTY_IDS,
    PROPERTY_ID_APPLICATION_MODULE,
    PROPERTY_ID_COMMON_MODULE,
    SOURCE_DEBUG,
)
from adapters.debug_http.errors import DebugHttpError
from adapters.debug_http.models import (
    AttachResult,
    BreakpointSpec,
    DebugEvent,
    DebugTarget,
    EvalResult,
    ModuleRef,
    StackFrame,
    StopEvent,
    VariableValue,
)
from adapters.debug_http.resolve import (
    ObjectIdResolver,
    StubObjectIdResolver,
    property_id_for_module_type,
)
from adapters.debug_http.session import DebugSession

__all__ = [
    "CODE_DBGS_MISSING",
    "CODE_DBGS_UNREACHABLE",
    "CODE_MODULE_UNRESOLVED",
    "CODE_NO_SESSION",
    "CODE_NO_TARGETS",
    "CODE_NOT_STOPPED",
    "CODE_WAIT_TIMEOUT",
    "DEFAULT_ALIAS",
    "DEFAULT_AUTO_ATTACH_TYPES",
    "DEFAULT_PING_INTERVAL_SEC",
    "DEFAULT_WAIT_TIMEOUT_SEC",
    "MODULE_PROPERTY_IDS",
    "PROPERTY_ID_APPLICATION_MODULE",
    "PROPERTY_ID_COMMON_MODULE",
    "SOURCE_DEBUG",
    "AttachResult",
    "BreakpointSpec",
    "DebugEvent",
    "DebugHttpClient",
    "DebugHttpError",
    "DebugSession",
    "DebugTarget",
    "EvalResult",
    "HttpResponse",
    "ModuleRef",
    "ObjectIdResolver",
    "StackFrame",
    "StopEvent",
    "StubObjectIdResolver",
    "TransportFn",
    "VariableValue",
    "property_id_for_module_type",
    "xml_build",
    "xml_parse",
]
