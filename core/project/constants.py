"""Project manifest and home layout constants (ADR-004 / ADR-022)."""

# Project home (schema "2", ADR-022). Единственный поддерживаемый layout.
HOME_DIR_NAME = ".1c-dev"
HOME_MANIFEST_NAME = "project.yaml"
HOME_MANIFEST_REL = f"{HOME_DIR_NAME}/{HOME_MANIFEST_NAME}"
HOME_RUNTIME_DIR_NAME = f"{HOME_DIR_NAME}/runtime"
HOME_PUBLISH_DIR_NAME = f"{HOME_DIR_NAME}/publish"

# Историческое имя корневого манифеста (только для ошибки unsupported layout).
UNSUPPORTED_ROOT_MANIFEST_NAME = "1c.project.yaml"

# Alias для diagnostics ``file=``.
MANIFEST_NAME = HOME_MANIFEST_REL
RUNTIME_DIR_NAME = HOME_RUNTIME_DIR_NAME

# Default ids при init/import (одна configuration + один runtime).
DEFAULT_CONFIG_ID = "main"
DEFAULT_RUNTIME_ID = "main"

# project.list: глубина сканирования вниз от path.
DEFAULT_LIST_DEPTH = 4

# Diagnostic codes for project.clean (ADR-021 / #76)
CODE_MANIFEST_MISSING = "1CP001"
CODE_CONFIRM_REQUIRED = "1CP010"
CODE_CLIENT_RUNNING = "1CP011"
CODE_CLEAN_FAILED = "1CP012"
CODE_SOURCE_CLEARED = "1CP013"
CODE_RUNTIME_CLEARED = "1CP014"
CODE_ALREADY_CLEAN = "1CP015"
# Корневой 1c.project.yaml / schema "1" больше не поддерживаются.
CODE_LEGACY_MANIFEST = "1CP016"

# Resolve --config / --runtime (ADR-023 / ADR-026 / #87)
CODE_CONFIG_UNKNOWN = "1CP020"
CODE_RUNTIME_UNKNOWN = "1CP021"
CODE_CONFIG_AMBIGUOUS = "1CP022"
CODE_RUNTIME_AMBIGUOUS = "1CP023"
CODE_RUNTIME_CONFIG_MISMATCH = "1CP024"
