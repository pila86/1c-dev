"""xml-gen source write adapter (ADR-007)."""

from __future__ import annotations

from adapters.source.xmlgen.compile import XmlGenError, compile_metadata, ir_to_xmlgen_dsl
from adapters.source.xmlgen.constants import (
    MIN_JAVA_MAJOR,
    XMLGEN_COMMIT,
    XMLGEN_JAR_ENV,
    XMLGEN_REPO,
)
from adapters.source.xmlgen.edit import (
    ALLOWED_OPS,
    CREATE_FOLLOWUP_OPS,
    EditOp,
    EditResult,
    edit_metadata,
    edit_op_from_dict,
)
from adapters.source.xmlgen.remove import remove_metadata
from adapters.source.xmlgen.resolve import (
    ToolResolve,
    default_jar_path,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
    tools_cache_dir,
)

__all__ = [
    "ALLOWED_OPS",
    "CREATE_FOLLOWUP_OPS",
    "MIN_JAVA_MAJOR",
    "XMLGEN_COMMIT",
    "XMLGEN_JAR_ENV",
    "XMLGEN_REPO",
    "EditOp",
    "EditResult",
    "ToolResolve",
    "XmlGenError",
    "compile_metadata",
    "default_jar_path",
    "edit_metadata",
    "edit_op_from_dict",
    "fetch_script_suggestion",
    "ir_to_xmlgen_dsl",
    "remove_metadata",
    "resolve_java",
    "resolve_jar",
    "tools_cache_dir",
]
