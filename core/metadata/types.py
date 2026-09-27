"""Metadata write-coverage catalog and Designer folder map (ADR-018 / #60).

Single source of truth for Meta DSL 23 + Subsystem. Create/update/delete
allowlists and doctor ``supportedTypes`` alias this catalog; per-type IR
parity lands in waves #61–#69.
"""

from __future__ import annotations

from typing import Literal

# xml-gen Meta DSL types (meta compile / edit / remove) — exactly 23.
META_DSL_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        "Catalog",
        "Document",
        "Enum",
        "Constant",
        "InformationRegister",
        "AccumulationRegister",
        "AccountingRegister",
        "CalculationRegister",
        "ChartOfAccounts",
        "ChartOfCharacteristicTypes",
        "ChartOfCalculationTypes",
        "BusinessProcess",
        "Task",
        "ExchangePlan",
        "DocumentJournal",
        "Report",
        "DataProcessor",
        "CommonModule",
        "ScheduledJob",
        "EventSubscription",
        "HTTPService",
        "WebService",
        "DefinedType",
    }
)

# ADR-018 write coverage: Meta DSL 23 + Subsystem (subsystem compile/edit).
WRITE_OBJECT_TYPES: frozenset[str] = META_DSL_OBJECT_TYPES | frozenset({"Subsystem"})

# Unified write allowlists (doctor + QName / create / update / delete gates).
CREATE_OBJECT_TYPES: frozenset[str] = WRITE_OBJECT_TYPES
UPDATE_OBJECT_TYPES: frozenset[str] = WRITE_OBJECT_TYPES
M2_OBJECT_TYPES: frozenset[str] = WRITE_OBJECT_TYPES

ObjectType = Literal[
    "Catalog",
    "Document",
    "Enum",
    "Constant",
    "InformationRegister",
    "AccumulationRegister",
    "AccountingRegister",
    "CalculationRegister",
    "ChartOfAccounts",
    "ChartOfCharacteristicTypes",
    "ChartOfCalculationTypes",
    "BusinessProcess",
    "Task",
    "ExchangePlan",
    "DocumentJournal",
    "Report",
    "DataProcessor",
    "CommonModule",
    "ScheduledJob",
    "EventSubscription",
    "HTTPService",
    "WebService",
    "DefinedType",
    "Subsystem",
]

# Designer dump folder names (xml-gen MetadataTypeRegistry + Subsystems).
TYPE_DIRS: dict[str, str] = {
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
