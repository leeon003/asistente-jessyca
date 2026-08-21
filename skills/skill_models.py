"""Modelos de datos inmutables y estados del Skill Framework Foundation (skill_models.py - Fases 28.0 y 28.1).

Define las estructuras formales para la definición, manifiesto, contexto, ejecución,
ciclo de vida y resultados de habilidades (Skills) en JESSYCA 3.0.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. SKILL != AUTHORIZATION: Un manifiesto no otorga permisos por sí mismo; declara necesidades.
2. FLUJO OBLIGATORIO: Intent -> Skill Discovery -> Manifest Validation -> Selection -> SecurityPipeline -> Execution.
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

    UNVALIDATED = "UNVALIDATED"
    REGISTERED = "REGISTERED"
    VALID = "VALID"
    INVALID = "INVALID"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
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
    BROWSER_NAVIGATION = "browser_navigation"
    WEB_SEARCH = "web_search"
    CONTENT_READ = "content_read"
    DESKTOP = "desktop"
    DESKTOP_INTERACTION = "desktop_interaction"
    FILESYSTEM = "filesystem"
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    SYSTEM = "system"
    SYSTEM_DIAGNOSTICS = "system_diagnostics"
    SYSTEM_INFO = "system_info"
    APPLICATION = "application"
    APPLICATION_CONTROL = "application_control"
    VISION = "vision"
    VISION_ANALYSIS = "vision_analysis"
    NETWORK = "network"
    MEMORY = "memory"
    PROCESS = "process"


# Catálogo extendido de capacidades reconocidas por el sistema
ALLOWED_SKILL_CAPABILITIES: set[str] = {
    cap.value for cap in SkillCapability
}.union({
    "browser.search",
    "browser.youtube",
    "files.organize",
    "documents.summarize",
    "windows.apps",
    "system.diagnostics",
    "filesystem.read",
    "filesystem.write",
    "process.execute",
    "registry.read",
    "registry.write",
})


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
class SkillManifest:
    """Manifiesto formal, declarativo e inmutable de una Skill (Fase 28.1)."""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Jessyca Core"
    capabilities: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    required_agents: tuple[str, ...] = ()
    required_models: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    risk_level: SecurityLevel = SecurityLevel.SAFE
    dependencies: dict[str, str] = field(default_factory=dict)  # skill_id -> min_version
    configuration: dict[str, Any] = field(default_factory=dict)
    entrypoint: str = "main.py"
    min_system_version: str = "3.0.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "capabilities": list(self.capabilities),
            "required_tools": list(self.required_tools),
            "required_agents": list(self.required_agents),
            "required_models": list(self.required_models),
            "permissions": list(self.permissions),
            "risk_level": str(self.risk_level),
            "dependencies": dict(self.dependencies),
            "configuration": dict(self.configuration),
            "entrypoint": self.entrypoint,
            "min_system_version": self.min_system_version,
            "created_at": self.created_at.isoformat(),
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
    manifest: SkillManifest | None = None
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
            "manifest": self.manifest.to_dict() if self.manifest else None,
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
