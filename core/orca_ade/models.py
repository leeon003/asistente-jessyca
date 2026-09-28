"""Modelos de datos y contratos estructurados para la Integración de ORCA + ADE.

Fase 2 — Controlled Integration & Governed Orchestration.
Principios:
1. MODO: OFF, LAB, SHADOW y CONTROLLED son válidos. ACTIVE permanece estrictamente prohibido.
2. SUBORDINACIÓN: Orca/ADE no es autoridad; formula tareas y propuestas bajo autorización JDE.
3. CONTRATOS ESTRICTOS: TaskContract, ResultContract, AgentLifecycle y PermissionManager.
4. VERIFICACIÓN FÍSICA: Diferenciación taxativa entre CLAIMED_SUCCESS y VERIFIED_SUCCESS.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.security import RiskLevel


class OrcaAdeMode(StrEnum):
    """Modos de operación permitidos para el adapter de ORCA + ADE."""

    OFF = "OFF"                  # Completamente deshabilitado
    LAB = "LAB"                  # Modo laboratorio aislado para pruebas y desarrollo
    SHADOW = "SHADOW"            # Modo sombra: genera propuestas y telemetría sin efectos colaterales
    CONTROLLED = "CONTROLLED"    # Modo controlado para capacidades certificadas bajo JDE
    ACTIVE = "ACTIVE"            # Modo productivo (PROHIBIDO EN FASE 2)


class ProposalActionType(StrEnum):
    """Tipos de acción sugeridas por una propuesta de ORCA + ADE."""

    CREATE_WORKTREE = "CREATE_WORKTREE"          # Crear rama/worktree aislado para una tarea
    REMOVE_WORKTREE = "REMOVE_WORKTREE"          # Limpiar rama/worktree temporal
    PROPOSE_DIFF = "PROPOSE_DIFF"                # Proponer modificación de código / diff
    INSPECT_UI = "INSPECT_UI"                    # Inspeccionar elementos UI (Design Mode)
    RUN_TESTS = "RUN_TESTS"                      # Ejecutar suite de pruebas en el worktree
    COORDINATE_SUBTASKS = "COORDINATE_SUBTASKS"  # Descomponer tarea en sub-agentes


class AgentState(StrEnum):
    """Estados formales del ciclo de vida de un agente ORCA/ADE."""

    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_REVIEW = "WAITING_REVIEW"
    COMPLETED = "COMPLETED"

    # Estados de fallo / terminación
    DENIED = "DENIED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    ISOLATION_ERROR = "ISOLATION_ERROR"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


# Matriz de transiciones legales permitidas para el ciclo de vida del agente
VALID_AGENT_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.CREATED: {
        AgentState.AUTHORIZED,
        AgentState.DENIED,
        AgentState.CANCELLED,
    },
    AgentState.AUTHORIZED: {
        AgentState.STARTING,
        AgentState.CANCELLED,
        AgentState.FAILED,
    },
    AgentState.STARTING: {
        AgentState.RUNNING,
        AgentState.FAILED,
        AgentState.ISOLATION_ERROR,
        AgentState.TIMEOUT,
        AgentState.CANCELLED,
    },
    AgentState.RUNNING: {
        AgentState.WAITING_REVIEW,
        AgentState.COMPLETED,
        AgentState.FAILED,
        AgentState.TIMEOUT,
        AgentState.ISOLATION_ERROR,
        AgentState.VERIFICATION_FAILED,
        AgentState.CANCELLED,
    },
    AgentState.WAITING_REVIEW: {
        AgentState.COMPLETED,
        AgentState.FAILED,
        AgentState.DENIED,
        AgentState.CANCELLED,
    },
    # Estados terminales no permiten más transiciones
    AgentState.COMPLETED: set(),
    AgentState.DENIED: set(),
    AgentState.FAILED: set(),
    AgentState.TIMEOUT: set(),
    AgentState.CANCELLED: set(),
    AgentState.ISOLATION_ERROR: set(),
    AgentState.VERIFICATION_FAILED: set(),
}


class AgentLifecycle:
    """Máquina de estados estricta que gobierna el ciclo de vida del agente."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._current_state: AgentState = AgentState.CREATED
        self._history: list[tuple[AgentState, float, str]] = [(AgentState.CREATED, time.time(), "Agent instantiated")]

    @property
    def current_state(self) -> AgentState:
        return self._current_state

    @property
    def history(self) -> list[tuple[AgentState, float, str]]:
        return list(self._history)

    def transition_to(self, target_state: AgentState | str, reason: str = "") -> AgentState:
        """Transiciona hacia un nuevo estado validando que la transición sea estrictamente legal."""
        if isinstance(target_state, str):
            target_state = AgentState(target_state)

        allowed = VALID_AGENT_TRANSITIONS.get(self._current_state, set())
        if target_state not in allowed:
            raise ValueError(
                f"Illegal state transition for agent '{self.agent_id}': "
                f"{self._current_state.value} -> {target_state.value}. "
                f"Allowed target states: {[s.value for s in allowed]}"
            )

        self._current_state = target_state
        self._history.append((target_state, time.time(), reason))
        return self._current_state


class OrcaPermission(StrEnum):
    """Permisos granulares para agentes bajo gobernanza JDE."""

    # Permitidos bajo sandbox
    READ_REPOSITORY = "READ_REPOSITORY"
    WRITE_WORKTREE = "WRITE_WORKTREE"
    CREATE_BRANCH = "CREATE_BRANCH"
    RUN_TESTS = "RUN_TESTS"
    READ_TEST_OUTPUT = "READ_TEST_OUTPUT"

    # Estrictamente denegados en Fase 2
    READ_CREDENTIALS = "READ_CREDENTIALS"
    READ_ENV_SECRETS = "READ_ENV_SECRETS"
    WRITE_PRODUCTION = "WRITE_PRODUCTION"
    DELETE_SYSTEM_FILES = "DELETE_SYSTEM_FILES"
    MODIFY_JESSYCA_CONFIG = "MODIFY_JESSYCA_CONFIG"
    CHANGE_SECURITY_POLICY = "CHANGE_SECURITY_POLICY"
    CHANGE_JDE = "CHANGE_JDE"
    CHANGE_PERMISSION_MANAGER = "CHANGE_PERMISSION_MANAGER"


_ALLOWED_PERMISSIONS: frozenset[OrcaPermission] = frozenset({
    OrcaPermission.READ_REPOSITORY,
    OrcaPermission.WRITE_WORKTREE,
    OrcaPermission.CREATE_BRANCH,
    OrcaPermission.RUN_TESTS,
    OrcaPermission.READ_TEST_OUTPUT,
})

_FORBIDDEN_PERMISSIONS: frozenset[OrcaPermission] = frozenset({
    OrcaPermission.READ_CREDENTIALS,
    OrcaPermission.READ_ENV_SECRETS,
    OrcaPermission.WRITE_PRODUCTION,
    OrcaPermission.DELETE_SYSTEM_FILES,
    OrcaPermission.MODIFY_JESSYCA_CONFIG,
    OrcaPermission.CHANGE_SECURITY_POLICY,
    OrcaPermission.CHANGE_JDE,
    OrcaPermission.CHANGE_PERMISSION_MANAGER,
})


def validate_agent_permissions(requested_permissions: list[str | OrcaPermission]) -> tuple[bool, list[str]]:
    """Valida un conjunto de permisos solicitados contra la política estricta de Fase 2."""
    denied: list[str] = []
    for p in requested_permissions:
        p_str = p.value if isinstance(p, OrcaPermission) else str(p)
        try:
            enum_val = OrcaPermission(p_str)
            if enum_val in _FORBIDDEN_PERMISSIONS:
                denied.append(f"Permission explicitly forbidden in Phase 2: {p_str}")
            elif enum_val not in _ALLOWED_PERMISSIONS:
                denied.append(f"Permission uncertified: {p_str}")
        except ValueError:
            denied.append(f"Unknown or unmanaged permission: {p_str}")

    return len(denied) == 0, denied


@dataclass(frozen=True)
class OrcaTaskContract:
    """Contrato estructurado formal para tareas asignadas a agentes ORCA/ADE."""

    task_id: str
    decision_id: str
    operation_id: str
    objective: str
    workspace: str
    allowed_actions: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    requires_review: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def compute_fingerprint(self) -> str:
        """Calcula el fingerprint criptográfico canónico SHA-256 de la tarea."""
        payload = {
            "objective": self.objective.strip(),
            "workspace": self.workspace.strip(),
            "allowed_actions": sorted(self.allowed_actions),
            "forbidden_actions": sorted(self.forbidden_actions),
            "timeout_seconds": self.timeout_seconds,
            "requires_review": self.requires_review,
        }
        raw_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw_bytes).hexdigest()

    def compute_seal(self) -> str:
        """Calcula el sello criptográfico inmutable contra manipulación post-decisión."""
        seal_payload = (
            f"{self.task_id}:{self.decision_id}:{self.workspace}:"
            f"{','.join(sorted(self.allowed_actions))}:{','.join(sorted(self.forbidden_actions))}"
        )
        return hashlib.sha256(seal_payload.encode("utf-8")).hexdigest()

    def verify_seal(self, expected_seal: str) -> bool:
        """Verifica si el contrato ha sufrido alteraciones o manipulación de parámetros."""
        return self.compute_seal() == expected_seal

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision_id": self.decision_id,
            "operation_id": self.operation_id,
            "objective": self.objective,
            "workspace": self.workspace,
            "allowed_actions": self.allowed_actions,
            "forbidden_actions": self.forbidden_actions,
            "timeout_seconds": self.timeout_seconds,
            "requires_review": self.requires_review,
            "fingerprint": self.compute_fingerprint(),
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class OrcaResultContract:
    """Contrato estructurado formal para el resultado de ejecución de un agente."""

    task_id: str
    decision_id: str
    status: str                         # "VERIFIED_SUCCESS", "CLAIMED_SUCCESS", "VERIFICATION_FAILED", "DENIED", "FAILED"
    workspace: str
    changed_files: list[str] = field(default_factory=list)
    tests: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    checksum: str | None = None
    duration_ms: float = 0.0
    verified: bool = False
    review_status: str = "PENDING"      # "PENDING", "APPROVED", "REJECTED"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "decision_id": self.decision_id,
            "status": self.status,
            "workspace": self.workspace,
            "changed_files": self.changed_files,
            "tests": self.tests,
            "evidence": self.evidence,
            "checksum": self.checksum,
            "duration_ms": self.duration_ms,
            "verified": self.verified,
            "review_status": self.review_status,
            "metadata": self.metadata,
        }


# -----------------------------------------------------------------------------
# Allowlist de Comandos Seguros y Política de Red
# -----------------------------------------------------------------------------

_SAFE_COMMAND_PREFIXES = (
    "git status",
    "git diff",
    "git branch",
    "git log",
    "git worktree",
    "pytest",
    "python -m py_compile",
    "python -m unittest",
)

_DANGEROUS_COMMAND_SUBSTRINGS = (
    "&&",
    ";",
    "|",
    "`",
    "$(",
    ">",
    "<",
    "\n",
    "\r",
    "powershell",
    "cmd",
    "curl",
    "wget",
    "invoke-expression",
    "rm -rf",
    "format",
    "del",
    "reg",
    "net ",
    "drop table",
    "shutdown",
    "bash",
    "sh ",
    "sudo",
    "chmod",
)


class CommandSecurityGuard:
    """Verifica comandos contra la allowlist estricta de Fase 3 y bloquea inyecciones."""

    @staticmethod
    def validate_command(command: str) -> tuple[bool, str]:
        """Comprueba si un comando está estrictamente autorizado.

        Returns:
            Tuple (allowed: bool, reason: str).
        """
        if not command or not command.strip():
            return False, "Command cannot be empty"

        norm_cmd = command.strip().lower()

        # Detección de inyecciones de comandos y tokens prohibidos
        for forbidden in _DANGEROUS_COMMAND_SUBSTRINGS:
            if forbidden in norm_cmd:
                return False, f"Command contains forbidden token or injection separator: {forbidden}"

        # Comprobación de prefijo en allowlist
        for safe_prefix in _SAFE_COMMAND_PREFIXES:
            if norm_cmd.startswith(safe_prefix):
                return True, "Authorized by allowlist"

        return False, f"Command '{command}' is not in authorized allowlist"


class NetworkSecurityGuard:
    """Política de red de Fase 3: Bloqueo total por defecto (NETWORK = DENY)."""

    _FORBIDDEN_PROTOCOLS = ("http", "https", "socket", "dns", "curl", "wget", "requests")

    @classmethod
    def is_network_allowed(
        cls,
        target: str,
        jde_authorized: bool = False,
        decision_id: str | None = None,
        time_scoped: bool = False,
    ) -> tuple[bool, str]:
        """Evalúa el acceso a red exigiendo autorización ligada a decisión (decision-bound)."""
        if not jde_authorized:
            return False, "Network access is DENIED by default (strictly prohibited without JDE authorization)"

        target_lower = target.lower()

        # Comprobar protocolos / bibliotecas no autorizadas hacia hosts externos
        for proto in cls._FORBIDDEN_PROTOCOLS:
            if target_lower.startswith(f"{proto}://") and "localhost" not in target_lower and "127.0.0.1" not in target_lower:
                return False, f"Protocol or target '{proto}' to external host strictly prohibited"

        # Solo loopback autorizado y acotado en el tiempo
        if "localhost" in target_lower or "127.0.0.1" in target_lower:
            bound_info = f" bound to decision '{decision_id}'" if decision_id else ""
            return True, f"Loopback authorized{bound_info}"

        if not decision_id:
            return False, "External network access strictly prohibited: missing JDE decision binding"

        return False, f"External network target '{target}' strictly prohibited without explicit capability exception"


# -----------------------------------------------------------------------------
# Propuestas y Resultados de Evaluación (Compatibilidad Fase 1)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class OrcaAdeProposal:
    """Propuesta estructurada emitida por ORCA/ADE hacia el JDE."""

    proposal_id: str
    capability: str
    action_type: ProposalActionType
    title: str
    description: str
    target_worktree: str | None = None
    target_path: str | None = None
    proposed_commands: list[str] = field(default_factory=list)
    suggested_diff: str | None = None
    estimated_risk: RiskLevel = RiskLevel.SAFE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "capability": self.capability,
            "action_type": self.action_type.value,
            "title": self.title,
            "description": self.description,
            "target_worktree": self.target_worktree,
            "target_path": self.target_path,
            "proposed_commands": self.proposed_commands,
            "suggested_diff": self.suggested_diff,
            "estimated_risk": self.estimated_risk.value,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class OrcaAdeEvaluationResult:
    """Resultado formal de la evaluación de una propuesta de ORCA + ADE."""

    status: str                         # "ALLOWED", "DENIED", "SKIPPED", "ERROR"
    provider: str = "orca_ade"
    capability: str = "agentic_worktree_orchestration"
    proposal: OrcaAdeProposal | None = None
    jde_decision: str | None = None      # "ALLOW", "DENY", "GOVERNANCE_REQUIRED"
    risk_level: RiskLevel = RiskLevel.SAFE
    evidence: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    is_shadow: bool = False
    side_effects_produced: int = 0      # DEBE SER 0 EN FASE 1 y controlado en Fase 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "capability": self.capability,
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "jde_decision": self.jde_decision,
            "risk_level": self.risk_level.value,
            "evidence": self.evidence,
            "errors": self.errors,
            "latency_ms": self.latency_ms,
            "is_shadow": self.is_shadow,
            "side_effects_produced": self.side_effects_produced,
        }
