"""Data models for HTTP Debug Protocol adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModuleRef:
    """Resolved module identity for breakpoints / stack."""

    object_id: str
    property_id: str
    module_name: str = ""
    module_type: str = ""
    extension_name: str = ""


@dataclass(frozen=True)
class BreakpointSpec:
    """Breakpoints for one module (objectID + propertyID + lines)."""

    object_id: str
    property_id: str
    lines: tuple[int, ...]
    extension_name: str = ""


@dataclass(frozen=True)
class DebugTarget:
    """Debug target from getDbgAllTargetStates / ping targetStarted."""

    target_id: str
    target_type: str = ""
    state: str = ""
    seance_id: str = ""
    info_base_alias: str = ""


@dataclass(frozen=True)
class StackFrame:
    """One call-stack frame; leaf (last) is the stop site."""

    object_id: str
    property_id: str
    line_no: int
    module_name: str = ""
    module_type: str = ""


@dataclass(frozen=True)
class StopEvent:
    """Stop from callStackFormed (ping)."""

    target_id: str
    frames: tuple[StackFrame, ...]
    raw_xml: str = ""

    @property
    def current_frame(self) -> StackFrame | None:
        return self.frames[-1] if self.frames else None

    @property
    def line_no(self) -> int | None:
        frame = self.current_frame
        return frame.line_no if frame else None

    @property
    def object_id(self) -> str | None:
        frame = self.current_frame
        return frame.object_id if frame else None


@dataclass(frozen=True)
class VariableValue:
    """One local / eval property."""

    name: str
    type_name: str = ""
    presentation: str = ""
    value_raw: str = ""


@dataclass(frozen=True)
class EvalResult:
    """Result of evalLocalVariables / evalExpr (sync in POST body on 8.3.25)."""

    state: str
    variables: tuple[VariableValue, ...] = ()
    raw_xml: str = ""

    @property
    def ok(self) -> bool:
        return self.state in ("", "correctly", "ok", "success")


@dataclass(frozen=True)
class AttachResult:
    """Outcome of attachDebugUI."""

    session_id: str
    result: str
    attempts: int = 1


@dataclass
class DebugEvent:
    """Parsed ping event."""

    type: str
    target_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw_xml: str = ""
