"""Pinned md-sparrow revision and env names (ADR-032 / #153)."""

from __future__ import annotations

from adapters.edtcli.constants import MD_SPARROW_MIN_JAVA_MAJOR

# yellow-hammer/md-sparrow — bake-off / fixture edt_spike: 0.6.7
MDSPARROW_REPO = "https://github.com/yellow-hammer/md-sparrow"
MDSPARROW_PIN = "0.6.7"
MDSPARROW_ASSET = "md-sparrow-0.6.7-all.jar"
MDSPARROW_URL = (
    f"{MDSPARROW_REPO}/releases/download/v{MDSPARROW_PIN}/{MDSPARROW_ASSET}"
)
MDSPARROW_JAR_ENV = "ONEC_MDSPARROW_JAR"
MIN_JAVA_MAJOR = MD_SPARROW_MIN_JAVA_MAJOR
# ADR-032: md-sparrow / JDK недоступен → ENV_UNAVAILABLE (3)
ENV_UNAVAILABLE_CODE = "1CS008"
# Process failure apply-mutation (wiring #153; metadata.* maps in #154)
MUTATION_FAILED_CODE = "1CS011"
# Known bake-off / spike gaps (ADR-032 §3 / #154) — warning or hard refuse
GAP_CODE = "1CS010"
