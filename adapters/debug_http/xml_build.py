"""XML request builders for dbgs HTTP Debug Protocol (spike #135 / ADR-031).

Ideas inspired by MIT liga-1c-command/1c-debug-mcp; implementation is original.
"""

from __future__ import annotations

from collections.abc import Sequence

from adapters.debug_http.constants import (
    NS_AA,
    NS_BD,
    NS_BP,
    NS_CALC,
    NS_RDBG,
    NS_XSI,
)
from adapters.debug_http.models import BreakpointSpec

XML_HDR = '<?xml version="1.0" encoding="UTF-8"?>'


def esc(value: str) -> str:
    """Escape XML special characters."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def request_xml(alias: str, dbg_id: str, body: str = "") -> str:
    """Wrap body in a standard ``<request>`` envelope."""
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"{body}</request>"
    )


def build_attach(alias: str, dbg_id: str, password: str = "") -> str:
    """Build ``attachDebugUI`` body."""
    cred = f"<credentials>{esc(password)}</credentials>" if password else ""
    body = f"<options><foregroundAbility>true</foregroundAbility></options>{cred}"
    return request_xml(alias, dbg_id, body)


def build_detach(alias: str, dbg_id: str) -> str:
    """Build ``detachDebugUI`` body."""
    return request_xml(alias, dbg_id)


def build_init_settings(alias: str, dbg_id: str, *, break_on_next: bool = False) -> str:
    """Build ``initSettings`` (pause via ``breakOnNextLine``)."""
    v = "true" if break_on_next else "false"
    return request_xml(alias, dbg_id, f"<data><breakOnNextLine>{v}</breakOnNextLine></data>")


def build_auto_attach(alias: str, dbg_id: str, types: Sequence[str]) -> str:
    """Build ``setAutoAttachSettings`` body."""
    targets = "".join(f"<aa:targetType>{esc(t)}</aa:targetType>" for t in types)
    body = (
        f'<autoAttachSettings xsi:type="aa:DebugAutoAttachSettings" '
        f'xmlns:xsi="{NS_XSI}" xmlns:aa="{NS_AA}">'
        f"{targets}<aa:areaName></aa:areaName></autoAttachSettings>"
    )
    return request_xml(alias, dbg_id, body)


def _module_bp_xml(spec: BreakpointSpec) -> str:
    bp_lines = "".join(
        f'<bpInfo xmlns="{NS_BP}">'
        f"<line>{ln}</line>"
        f"<isActive>true</isActive>"
        f"<breakOnCondition>false</breakOnCondition><condition></condition>"
        f"<breakOnParentMethod>false</breakOnParentMethod><parentMethod></parentMethod>"
        f"<breakOnHitCount>false</breakOnHitCount>"
        f"<hitCountVariant>0</hitCountVariant><hitCount>1</hitCount>"
        f"<temp>false</temp></bpInfo>"
        for ln in spec.lines
    )
    ext = esc(spec.extension_name)
    # live-проверка 8.3.25: модуль расширения получает точку только с type=ExtensionModule
    module_type = "ExtensionModule" if spec.extension_name else "ConfigModule"
    module_id = (
        f'<type xmlns="{NS_BD}">{module_type}</type>'
        f'<URL xmlns="{NS_BD}"></URL>'
        f'<extensionName xmlns="{NS_BD}">{ext}</extensionName>'
        f'<objectID xmlns="{NS_BD}">{esc(spec.object_id)}</objectID>'
        f'<propertyID xmlns="{NS_BD}">{esc(spec.property_id)}</propertyID>'
        f'<extId xmlns="{NS_BD}">0</extId>'
    )
    return (
        f'<moduleBPInfo xmlns="{NS_BP}">'
        f'<id xmlns="{NS_BP}">{module_id}</id>{bp_lines}</moduleBPInfo>'
    )


def build_set_breakpoints(
    alias: str,
    dbg_id: str,
    modules: Sequence[BreakpointSpec],
) -> str:
    """Build ``setBreakpoints`` body (empty modules → clear all)."""
    modules_xml = "".join(_module_bp_xml(m) for m in modules)
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<bpWorkspace>{modules_xml}</bpWorkspace></request>"
    )


def build_step(alias: str, dbg_id: str, target_id: str, action: str) -> str:
    """Build ``step`` (Continue / Step / StepIn / StepOut)."""
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"<action>{esc(action)}</action><simple>false</simple></request>"
    )


def build_attach_targets(
    alias: str,
    dbg_id: str,
    target_ids: Sequence[str],
    *,
    attach: bool = True,
) -> str:
    """Build ``attachDetachDbgTargets`` body."""
    ids = "".join(
        f'<id xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(t)}</bd:id></id>' for t in target_ids
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<attach>{'true' if attach else 'false'}</attach>{ids}</request>"
    )


def build_eval_locals(alias: str, dbg_id: str, target_id: str, result_id: str) -> str:
    """Build ``evalLocalVariables`` body."""
    expr = (
        f'<expr xsi:type="calc:CalculationSourceDataStorage">'
        f"<calc:stackLevel>0</calc:stackLevel><calc:srcCalcInfo>"
        f"<calc:expressionResultID>{esc(result_id)}</calc:expressionResultID>"
        f"<calc:interfaces>context</calc:interfaces></calc:srcCalcInfo>"
        f"<calc:presOptions><calc:maxTextSize>307200</calc:maxTextSize>"
        f"<calc:stopOnFirstEOL>false</calc:stopOnFirstEOL></calc:presOptions></expr>"
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" '
        f'xmlns:calc="{NS_CALC}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<calcWaitingTime>5000</calcWaitingTime>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"{expr}</request>"
    )


def build_eval_expr(
    alias: str,
    dbg_id: str,
    target_id: str,
    expression: str,
    result_id: str,
) -> str:
    """Build ``evalExpr`` body."""
    expr = (
        f'<expr xsi:type="calc:CalculationSourceDataStorage">'
        f"<calc:stackLevel>0</calc:stackLevel><calc:srcCalcInfo>"
        f"<calc:expressionResultID>{esc(result_id)}</calc:expressionResultID>"
        f"<calc:calcItem><calc:itemType>expression</calc:itemType>"
        f"<calc:expression>{esc(expression)}</calc:expression>"
        f"<calc:property></calc:property></calc:calcItem>"
        f"<calc:interfaces>context</calc:interfaces></calc:srcCalcInfo>"
        f"<calc:presOptions><calc:maxTextSize>307200</calc:maxTextSize>"
        f"<calc:stopOnFirstEOL>false</calc:stopOnFirstEOL></calc:presOptions></expr>"
    )
    return (
        f'{XML_HDR}<request xmlns="{NS_RDBG}" xmlns:bd="{NS_BD}" '
        f'xmlns:calc="{NS_CALC}" xmlns:xsi="{NS_XSI}">'
        f"<infoBaseAlias>{esc(alias)}</infoBaseAlias>"
        f"<idOfDebuggerUI>{esc(dbg_id)}</idOfDebuggerUI>"
        f"<calcWaitingTime>5000</calcWaitingTime>"
        f'<targetID xsi:type="bd:DebugTargetIdLight"><bd:id>{esc(target_id)}</bd:id></targetID>'
        f"{expr}</request>"
    )
