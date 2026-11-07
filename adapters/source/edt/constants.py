"""EDT Source Adapter constants (ADR-032 / #152)."""

from __future__ import annotations

# Eclipse nature из .project (spike #149 / 1C:EDT).
V8_CONFIGURATION_NATURE = "com._1c.g5.v8.dt.core.V8ConfigurationNature"

CONFIGURATION_MDO_REL = "src/Configuration/Configuration.mdo"
PROJECT_FILE_NAME = ".project"

# Diagnostics 1CS… (ADR-032 §7); exit PROJECT_ERROR (2).
CODE_LAYOUT_NOT_EDT = "1CS003"
CODE_PATH_NOT_EDT_ROOT = "1CS004"

SOURCE_FORMAT_EDT = "edt"
SOURCE_FORMAT_XML = "xml"
