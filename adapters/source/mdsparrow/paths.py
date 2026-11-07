"""EDT object / Configuration.mdo paths (ADR-032 write D / #154).

Folder map mirrors ``core.metadata.types.TYPE_DIRS`` without importing
``core.metadata`` (avoids circular import via package ``__init__``).
"""

from __future__ import annotations

from pathlib import Path

from adapters.source.edt.constants import CONFIGURATION_MDO_REL

# Keep in sync with core.metadata.types.TYPE_DIRS.
_TYPE_DIRS: dict[str, str] = {
    "Catalog": "Catalogs",
    "Document": "Documents",
    "Enum": "Enums",
    "Constant": "Constants",
    "InformationRegister": "InformationRegisters",
    "AccumulationRegister": "AccumulationRegisters",
    "AccountingRegister": "AccountingRegisters",
    "CalculationRegister": "CalculationRegisters",
    "ChartOfAccounts": "ChartsOfAccounts",
    "ChartOfCharacteristicTypes": "ChartsOfCharacteristicTypes",
    "ChartOfCalculationTypes": "ChartsOfCalculationTypes",
    "BusinessProcess": "BusinessProcesses",
    "Task": "Tasks",
    "ExchangePlan": "ExchangePlans",
    "DocumentJournal": "DocumentJournals",
    "Report": "Reports",
    "DataProcessor": "DataProcessors",
    "CommonModule": "CommonModules",
    "ScheduledJob": "ScheduledJobs",
    "EventSubscription": "EventSubscriptions",
    "HTTPService": "HTTPServices",
    "WebService": "WebServices",
    "DefinedType": "DefinedTypes",
    "Subsystem": "Subsystems",
}

# Default Designer dump schema for md-sparrow get/set on EDT fixtures (8.3.24 → V2_17).
DEFAULT_SCHEMA_VERSION = "V2_17"


def configuration_mdo_path(edt_root: Path) -> Path:
    """Absolute path to Configuration.mdo under EDT project root."""
    return (edt_root / CONFIGURATION_MDO_REL).resolve()


def object_mdo_path(edt_root: Path, obj_type: str, name: str) -> Path:
    """Expected ``src/<TypeDir>/<Name>/<Name>.mdo`` under EDT project root."""
    folder = _TYPE_DIRS.get(obj_type)
    if folder is None:
        raise KeyError(obj_type)
    return (edt_root / "src" / folder / name / f"{name}.mdo").resolve()


def object_mdo_rel(obj_type: str, name: str) -> str:
    """POSIX relative path from EDT root to object .mdo."""
    folder = _TYPE_DIRS[obj_type]
    return f"src/{folder}/{name}/{name}.mdo"
