"""Pinned xml-gen upstream revision and env names (ADR-007, ADR-018 / #60)."""

from __future__ import annotations

# SteelMorgan/1c-agent-based-dev-framework tools/xml-gen.
# Pin covers Meta DSL 23 (meta compile/edit/remove) + subsystem compile/edit.
XMLGEN_REPO = "https://github.com/SteelMorgan/1c-agent-based-dev-framework.git"
XMLGEN_COMMIT = "19f67bfed6d15f051f9568678bab1701b7735f95"
XMLGEN_SPARSE_PATH = "tools/xml-gen"
XMLGEN_JAR_ENV = "ONEC_XMLGEN_JAR"
MIN_JAVA_MAJOR = 17
