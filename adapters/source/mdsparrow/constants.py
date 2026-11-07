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
# Upstream: yellow-hammer/md-sparrow#78 — contentRefs no-op on EDT write.
MDSPARROW_CONTENT_REFS_ISSUE = (
    "https://github.com/yellow-hammer/md-sparrow/issues/78"
)
SUBSYSTEM_CONTENT_GAP_SUGGESTION = (
    "Состав подсистемы на EDT пока не пишется "
    f"({MDSPARROW_CONTENT_REFS_ISSUE}). "
    "Обход: 1c-dev source convert --to xml → metadata create/update "
    "с content / add-content → при необходимости "
    "1c-dev source convert --to edt; "
    "альтернатива: вручную добавить <content>Catalog.X</content> в .mdo."
)
# Wall-clock budget for apply-mutation JVM (analog edtcli timeout+60).
DEFAULT_MUTATION_TIMEOUT_SEC = 300
# Probe 2026-11-07 / md-sparrow 0.6.7 EDT: cf-md-object-set accepts
# registerRecords as JSON array but does not persist into .mdo (silent no-op).
# String payload fails Gson (Expected BEGIN_ARRAY). See #167.
REGISTER_RECORDS_GAP_SUGGESTION = (
    "EDT/md-sparrow пока не пишет registerRecords в .mdo. "
    "Обход: править registerRecords вручную в .mdo документа "
    "или 1c-dev source.convert --to=xml, задать движения в Designer XML, "
    "затем convert --to=edt."
)
