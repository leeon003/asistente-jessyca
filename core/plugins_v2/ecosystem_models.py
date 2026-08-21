"""Modelos de datos inmutables para el Ecosistema de Plugins 2.0 (ecosystem_models.py - Fase 28).

Define la estructura formal del Plugin Manifest 2.0, declaraciones de herramientas,
estados de ciclo de vida y resultados de validación en 5 etapas.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. UNTRUSTED CODE: Todo plugin es código no confiable.
2. MANIFEST != PERMISSION: El manifiesto no otorga permisos; pasa por validación de seguridad de 5 etapas.
3. AISLAMIENTO: Ningún plugin puede modificar SecurityPipeline, RiskEngine, PermissionManager,
   ConfirmationManager ni EmergencyStopManager.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.security_architecture import SecurityLevel

SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
PLUGIN_NAME_REGEX = re.compile(r"^[a-z0-9\-_]{3,64}$")


class PluginStatus(StrEnum):
    """Estados del ciclo de vida de un plugin en el ecosistema 2.0."""

    UNVALIDATED = "UNVALIDATED"
    VALIDATED = "VALIDATED"
    LOADED = "LOADED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PluginToolDeclaration:
    """Declaración inmutable de una herramienta expuesta por un plugin."""

    name: str
    description: str = ""
    operation: str = "execute"
    required_capability: str = ""
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    declared_risk_level: SecurityLevel = SecurityLevel.SAFE

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "operation": self.operation,
            "required_capability": self.required_capability,
            "parameters_schema": dict(self.parameters_schema),
            "declared_risk_level": str(self.declared_risk_level),
        }


@dataclass(frozen=True)
class PluginManifest2:
    """Manifiesto formal e inmutable de un plugin en el Ecosistema 2.0."""

    name: str
    version: str
    capabilities: tuple[str, ...]
    tools: tuple[PluginToolDeclaration, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    dependencies: dict[str, str] = field(default_factory=dict)  # plugin_name -> min_version
    config_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: SecurityLevel = SecurityLevel.SAFE
    description: str = ""
    author: str = ""
    entrypoint: str = "main.py"
    min_system_version: str = "3.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "tools": [t.to_dict() for t in self.tools],
            "permissions": list(self.permissions),
            "dependencies": dict(self.dependencies),
            "config_schema": dict(self.config_schema),
            "risk_level": str(self.risk_level),
            "description": self.description,
            "author": self.author,
            "entrypoint": self.entrypoint,
            "min_system_version": self.min_system_version,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ValidationStageResult:
    """Resultado inmutable de una etapa individual de validación."""

    stage_name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginValidationReport:
    """Informe consolidado de las 5 etapas de validación previa a la carga."""

    plugin_name: str
    is_valid: bool
    stages: tuple[ValidationStageResult, ...]
    overall_error: str | None = None
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "is_valid": self.is_valid,
            "stages": [{"stage": s.stage_name, "passed": s.passed, "message": s.message} for s in self.stages],
            "overall_error": self.overall_error,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
