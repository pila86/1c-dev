"""EDT CLI / md-sparrow JDK hints shared by doctor and integration skips (#151)."""

from __future__ import annotations

EDTCLI_ENV = "ONEC_EDTCLI"
MD_SPARROW_MIN_JAVA_MAJOR = 25

EDTCLI_MISSING_HINT = (
    "Установите 1C:EDT CLI (≥2025.1), добавьте 1cedtcli в PATH "
    f"или задайте {EDTCLI_ENV} (типичный root: /opt/1C/1CE/components)."
)

MD_SPARROW_JDK_HINT = (
    "Для md-sparrow (EDT write) нужен JDK 25+ (Temurin); "
    "задайте JAVA_HOME или добавьте java в PATH."
)

# Skip messages — те же discovery roots / env, что и doctor suggestion.
EDTCLI_SKIP_MESSAGE = (
    "1cedtcli не найден — EDT integration пропущен "
    f"({EDTCLI_ENV} / PATH / /opt/1C/1CE/components)"
)

MD_SPARROW_JDK_SKIP_MESSAGE = (
    "JDK 25+ (Temurin) не найден — md-sparrow / EDT write пропущен "
    "(JAVA_HOME / java в PATH)"
)
