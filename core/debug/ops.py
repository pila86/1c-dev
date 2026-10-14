"""Debug API orchestration facade (ADR-031 / #140).

Implementation lives in ``core.debug.{common,breakpoints,lifecycle,control,inspection}``.
This module re-exports the public API; ``core.runtime`` and tests resolve names
here at call time, so monkeypatching ``core.debug.ops.<name>`` keeps working.
"""

from __future__ import annotations

from core.debug.breakpoints import (
    BreakpointCliSpec,
    parse_breakpoint_specs,
    run_breakpoint_clear,
    run_breakpoint_set,
)
from core.debug.control import (
    run_continue,
    run_pause,
    run_step_in,
    run_step_out,
    run_step_over,
    run_wait,
)
from core.debug.inspection import run_evaluate, run_stack, run_variables
from core.debug.lifecycle import (
    await_debug_targets_armed,
    ensure_debug_for_runtime,
    has_debug_state,
    prepare_debug_for_spawn,
    run_attach,
    run_detach,
    run_force_detach,
    run_ping_start,
    run_ping_status,
    run_ping_stop,
    run_reload_metadata,
    run_server_start,
    run_server_status,
    run_server_stop,
    run_status,
    run_targets,
    sync_debug_targets_after_runtime,
    teardown_debug,
)

__all__ = [
    "BreakpointCliSpec",
    "await_debug_targets_armed",
    "ensure_debug_for_runtime",
    "has_debug_state",
    "parse_breakpoint_specs",
    "prepare_debug_for_spawn",
    "run_attach",
    "run_breakpoint_clear",
    "run_breakpoint_set",
    "run_continue",
    "run_detach",
    "run_evaluate",
    "run_force_detach",
    "run_pause",
    "run_ping_start",
    "run_ping_status",
    "run_ping_stop",
    "run_reload_metadata",
    "run_server_start",
    "run_server_status",
    "run_server_stop",
    "run_stack",
    "run_status",
    "run_step_in",
    "run_step_out",
    "run_step_over",
    "run_targets",
    "run_variables",
    "run_wait",
    "sync_debug_targets_after_runtime",
    "teardown_debug",
]
