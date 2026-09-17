"""Pinned xml-gen upstream revision and env names (ADR-007)."""

from __future__ import annotations

# Bake-off / ADR-007 pin of SteelMorgan/1c-agent-based-dev-framework
XMLGEN_REPO = "https://github.com/SteelMorgan/1c-agent-based-dev-framework.git"
XMLGEN_COMMIT = "19f67bfed6d15f051f9568678bab1701b7735f95"
XMLGEN_SPARSE_PATH = "tools/xml-gen"
XMLGEN_JAR_ENV = "ONEC_XMLGEN_JAR"
MIN_JAVA_MAJOR = 17
