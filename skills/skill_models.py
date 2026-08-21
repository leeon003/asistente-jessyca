"""Modelos de datos inmutables y estados del Skill Framework Foundation (skill_models.py - Fase 28.0).

Define las estructuras formales para la definición, contexto, ejecución, ciclo de vida
y resultados de habilidades (Skills) en JESSYCA 3.0.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. SKILL != AUTHORIZATION: Una Skill no tiene autoridad de seguridad ni bypass.
2. FLUJO OBLIGATORIO: Intent -> Skill Discovery -> Validation -> Selection -> SecurityPipeline -> Execution.
3. Prevalencia de Parada de Emergencia: EmergencyStopManager detiene inmediatamente cualquier Skill.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.cancellation import CancellationToken
from core.security_architecture import SecurityLevel

SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")
SKILL_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


class SkillStatus(StrEnum):
    """Estados formales del ciclo de vida y ejecución de una Skill."""

    DISCOVERED = "DISCOVERED"
    VALIDATING = "VALIDATING"
    LOADED = "LOADED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNLOADED = "UNLOADED"


class SkillCapability(StrEnum):
    """Catálogo de capacidades estándar que una Skill puede emplear."""

    BROWSER = "browser"
    DESKTOP = "desktop"
    FILESYSTEM = "filesystem"
    SYSTEM = "system"
    APPLICATION = "application"
    VISION = "vision"
    NETWORK = "network"
    MEMORY = "memory"
    PROCESS = "process"


@dataclass(frozen=True)
class SkillPermission:
    """Declaración inmutable de permiso requerido por una Skill."""

    permission_name: str
    target_tool: str
    risk_level: SecurityLevel = SecurityLevel.SAFE
    justification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission_name": self.permission_name,
            "target_tool": self.target_tool,
            "risk_level": str(self.risk_level),
            "justification": self.justification,
        }


@dataclass(frozen=True)
class SkillDefinition:
    """Definición declarativa, tipada e inmutable de una Skill."""

    skill_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    risk_level: SecurityLevel = SecurityLevel.SAFE
    author: str = "Jessyca Core"
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    min_system_version: str = "3.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "required_tools": list(self.required_tools),
            "required_permissions": list(self.required_permissions),
            "risk_level": str(self.risk_level),
            "author": self.author,
            "parameters_schema": dict(self.parameters_schema),
            "tags": list(self.tags),
            "min_system_version": self.min_system_version,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class SkillContext:
    """Contexto de ejecución proporcionado a la Skill."""

    skill_id: str
    intent: str
    parameters: dict[str, Any] = field(default_factory=dict)
    execution_id: str = field(default_factory=lambda: f"skexec-{uuid.uuid4().hex[:8]}")
    session_id: str = "default_session"
    user: str = "user"
    timeout_seconds: float = 60.0
    cancellation_token: CancellationToken | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "intent": self.intent,
            "parameters": dict(self.parameters),
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "user": self.user,
            "timeout_seconds": self.timeout_seconds,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class SkillResult:
    """Resultado final inmutable y explicable de la ejecución de una Skill."""

    skill_id: str
    success: bool
    status: SkillStatus
    output: Any = None
    error: str | None = None
    steps: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    security_decision: str = "ALLOW"
    execution_id: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "success": self.success,
            "status": str(self.status),
            "output": self.output,
            "error": self.error,
            "steps": list(self.steps),
            "warnings": list(self.warnings),
            "security_decision": self.security_decision,
            "execution_id": self.execution_id,
            "duration_ms": round(self.duration_ms, 2),
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp.isoformat(),
        }
