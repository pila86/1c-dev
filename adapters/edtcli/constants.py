"""EDT CLI / md-sparrow JDK hints shared by doctor and integration skips (#151 / #155)."""

from __future__ import annotations

EDTCLI_ENV = "ONEC_EDTCLI"
MD_SPARROW_MIN_JAVA_MAJOR = 25

# Minimum EDT for M7 ops (spike #149 / ADR-032).
MIN_EDT_MAJOR = 2025
MIN_EDT_MINOR = 1

DEFAULT_EXPORT_TIMEOUT_SEC = 300

# Diagnostics 1CS… (ADR-032 §7) — export / import / convert (#155 / #156).
CODE_EDTCLI_MISSING = "1CS001"
CODE_EDTCLI_VERSION = "1CS002"
CODE_EDTCLI_FAILED = "1CS005"
CODE_EDTCLI_COLLISION = "1CS006"
CODE_EDTCLI_EMPTY_EXPORT = "1CS007"
CODE_CONVERT_DIRTY = "1CS009"

DEFAULT_IMPORT_TIMEOUT_SEC = DEFAULT_EXPORT_TIMEOUT_SEC
DEFAULT_IMPORT_PLATFORM_VERSION = "8.5.1"

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

# Platform / ibcmd skip (build+check integration on EDT).
PLATFORM_SKIP_MESSAGE = (
    "ibcmd / платформа 1С не найдены — EDT build/check integration пропущен"
)
