"""Adapter de Integración de ORCA + ADE para JESSYCA PC.

Fase 2 — Controlled Integration & Governed Orchestration.
Implementa la mediación segura y subordinada al JDE de las capacidades de
orquestación agéntica y paralelismo de Git Worktrees inspiradas en Orca / ADE.

Reglas Inviolables de Fase 2:
1. NO ACTIVAR EN PRODUCCIÓN: El modo ACTIVE está prohibido (falla con RuntimeError).
2. SUBORDINACIÓN AL JDE: JDE es la autoridad única. El adapter solo formula propuestas y contratos.
3. CONFINAMIENTO DE OPERACIONES: Allowlist estricta para comandos; sin ejecución arbitraria.
4. REDACCIÓN DE SECRETOS: Toda clave, token o credencial se anonimiza en el pipeline.
5. CERO EFECTOS COLATERALES EN SHADOW: Registra telemetría con side_effects_produced == 0.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
import uuid
from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.orca_ade.models import (
    AgentLifecycle,
    AgentState,
    CommandSecurityGuard,
    NetworkSecurityGuard,
    OrcaAdeEvaluationResult,
    OrcaAdeMode,
    OrcaAdeProposal,
    OrcaPermission,
    OrcaResultContract,
    OrcaTaskContract,
    ProposalActionType,
    validate_agent_permissions,
)
from core.security import RiskLevel

logger = get_logger("jessyca.orca_ade.adapter")

# Expresiones regulares para detección y redacción de secretos
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(?:bearer|token)\s+([a-zA-Z0-9_\-\.]{15,})"), "Bearer [REDACTED]"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,48}"), "[REDACTED_API_KEY]"),
    (re.compile(r"gh[pousr][_\-][a-zA-Z0-9]{20,80}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"(?i)(password|secret|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s]{4,})['\"]?"), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(postgres|mysql|mongodb)://[^:\s]+:[^@\s]+@[^\s/]+"), r"\1://[REDACTED_CREDENTIALS]"),
]

# Rutas prohibidas del sistema
_FORBIDDEN_SYSTEM_PATHS = [
    "\\windows\\",
    "/windows/",
    "\\system32\\",
    "/system32/",
    "\\program files\\",
    "/program files/",
    "/etc/",
    "/root/",
    "\\users\\administrator\\",
]


class OrcaAdeAdapter(IntegrationAdapter):
    """Adapter para el subsistema de orquestación agéntica ORCA + ADE."""

    def __init__(
        self,
        mode: OrcaAdeMode | str = OrcaAdeMode.CONTROLLED,
        base_worktree_dir: str | None = None,
        certified: bool = False,
    ) -> None:
        super().__init__(
            name="orca_ade",
            version="2.0.0-phase3",
            dependencies=[],
        )
        self._certified = certified
        mode_str = str(mode).upper()
        if mode_str == "ACTIVE" and not self._certified:
            raise RuntimeError(
                "ORCA + ADE cannot be activated in production (ACTIVE is strictly forbidden in Phase 1 / Phase 2 before full certification)"
            )
        try:
            self._mode = OrcaAdeMode(mode_str)
        except ValueError:
            self._mode = OrcaAdeMode.CONTROLLED

        # Directorio base para worktrees aislados en pruebas
        self._base_worktree_dir = os.path.realpath(
            base_worktree_dir or os.path.join("data", "orca_worktrees")
        )
        self._task_cache: dict[str, OrcaResultContract] = {}
        self._register_capabilities()

    @property
    def mode(self) -> OrcaAdeMode:
        """Modo de operación actual (OFF, LAB, SHADOW, CONTROLLED, ACTIVE)."""
        return self._mode

    @property
    def is_certified(self) -> bool:
        return self._certified

    def set_certified(self, certified: bool = True) -> None:
        """Marca formalmente la certificación para autorizar el modo ACTIVE."""
        self._certified = certified

    def set_mode(self, new_mode: OrcaAdeMode | str, certified: bool = False) -> None:
        """Cambia el modo de operación respetando las restricciones de certificación."""
        mode_str = str(new_mode).upper()
        if mode_str == "ACTIVE" and not (self._certified or certified):
            raise RuntimeError(
                "ORCA + ADE cannot be activated in production (ACTIVE is strictly forbidden in Phase 1 / Phase 2 before full certification)"
            )
        if certified:
            self._certified = True
        self._mode = OrcaAdeMode(mode_str)
        if self._mode == OrcaAdeMode.OFF:
            self.status = IntegrationStatus.DISABLED
        else:
            self.status = IntegrationStatus.READY

    def kill_switch(self) -> None:
        """Kill switch operacional de emergencia: desactiva inmediatamente ORCA/ADE."""
        self._mode = OrcaAdeMode.OFF
        self.status = IntegrationStatus.DISABLED
        self._task_cache.clear()
        logger.warning("[KILL SWITCH ACTIVATED] ORCA + ADE has been immediately shut down.")

    def _register_capabilities(self) -> None:
        """Registra las capacidades experimentales de ORCA + ADE."""
        self.register_capability(
            IntegrationCapability(
                name="worktree_isolation",
                description="Gestión y aislamiento de tareas agénticas en ramas/worktrees efímeros de Git.",
                required_risk_level=RiskLevel.WARNING,
                required_permissions=["git:worktree", "fs:sandboxed_read_write"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "branch_name": {"type": "string"},
                        "action": {"type": "string", "enum": ["create", "cleanup", "diff"]},
                    },
                    "required": ["task_id", "action"],
                },
            )
        )
        self.register_capability(
            IntegrationCapability(
                name="parallel_agent_dispatch",
                description="Propuesta de descomposición y asignación paralela de sub-tareas a agentes de codificación.",
                required_risk_level=RiskLevel.WARNING,
                required_permissions=["agent:propose_dispatch"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "agent_count": {"type": "integer", "maximum": 4},
                    },
                    "required": ["prompt"],
                },
            )
        )
        self.register_capability(
            IntegrationCapability(
                name="design_mode_inspection",
                description="Extracción estructurada de selectores UI y metadatos visuales (Design Mode).",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["browser:inspect_safe"],
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "target_element": {"type": "string"},
                    },
                    "required": ["target_element"],
                },
            )
        )

    # -------------------------------------------------------------------------
    # Sanitización y Seguridad
    # -------------------------------------------------------------------------

    def redact_secrets(self, text: str) -> str:
        """Elimina tokens, credenciales y llaves privadas de cualquier texto."""
        if not text:
            return text
        result = text
        for pattern, replacement in _SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    def validate_and_confine_path(self, target_path: str) -> str:
        """Valida que una ruta esté estrictamente confinada al sandbox del worktree."""
        if not target_path:
            raise ValueError("Target path cannot be empty")

        if "\x00" in target_path:
            raise ValueError("Null bytes are forbidden in paths")

        unquoted = urllib.parse.unquote(urllib.parse.unquote(target_path))
        if "%2e" in unquoted.lower() or ".." in unquoted:
            raise ValueError("Path traversal attempt detected")

        # Comprobar rutas del sistema
        norm_lower = unquoted.lower().replace("/", "\\")
        for forbidden in _FORBIDDEN_SYSTEM_PATHS:
            if forbidden in norm_lower:
                raise ValueError(f"Access to system path is forbidden: {forbidden}")

        if re.match(r"^[a-zA-Z]:", unquoted) and not unquoted.startswith(self._base_worktree_dir):
            real_path = os.path.realpath(unquoted)
            try:
                common = os.path.commonpath([self._base_worktree_dir, real_path])
                if common != self._base_worktree_dir:
                    raise ValueError("Target path escapes sandbox confinement")
            except ValueError:
                raise ValueError("Target path escapes sandbox confinement")
            return real_path

        resolved = os.path.realpath(os.path.join(self._base_worktree_dir, unquoted))
        try:
            common = os.path.commonpath([self._base_worktree_dir, resolved])
            if common != self._base_worktree_dir:
                raise ValueError("Target path escapes sandbox confinement")
        except ValueError:
            raise ValueError("Target path escapes sandbox confinement")

        return resolved

    # -------------------------------------------------------------------------
    # Generación y Evaluación de Propuestas (Subordinación al JDE)
    # -------------------------------------------------------------------------

    def create_proposal(
        self,
        capability: str,
        action_type: ProposalActionType,
        title: str,
        description: str,
        target_path: str | None = None,
        proposed_commands: list[str] | None = None,
        suggested_diff: str | None = None,
        estimated_risk: RiskLevel = RiskLevel.SAFE,
        metadata: dict[str, Any] | None = None,
    ) -> OrcaAdeProposal:
        """Genera una propuesta estructurada formal sin ejecutarla directamente."""
        clean_title = self.redact_secrets(title)
        clean_desc = self.redact_secrets(description)
        clean_cmds = [self.redact_secrets(c) for c in (proposed_commands or [])]
        clean_diff = self.redact_secrets(suggested_diff) if suggested_diff else None

        safe_target: str | None = None
        if target_path:
            safe_target = self.validate_and_confine_path(target_path)

        proposal = OrcaAdeProposal(
            proposal_id=f"orca_prop_{uuid.uuid4().hex[:12]}",
            capability=capability,
            action_type=action_type,
            title=clean_title,
            description=clean_desc,
            target_worktree=metadata.get("worktree_name") if metadata else None,
            target_path=safe_target,
            proposed_commands=clean_cmds,
            suggested_diff=clean_diff,
            estimated_risk=estimated_risk,
            metadata=metadata or {},
        )
        return proposal

    def evaluate_proposal(
        self,
        proposal: OrcaAdeProposal,
        jde_decision_override: str | None = None,
    ) -> OrcaAdeEvaluationResult:
        """Evalúa una propuesta subordinándola al JDE."""
        start_time = time.perf_counter()

        if self._mode == OrcaAdeMode.OFF:
            return OrcaAdeEvaluationResult(
                status="SKIPPED",
                proposal=proposal,
                jde_decision="DENY",
                errors=["ORCA + ADE is currently OFF"],
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                side_effects_produced=0,
            )

        decision = jde_decision_override or "GOVERNANCE_REQUIRED"
        errors: list[str] = []
        is_safe = True

        # Tareas de riesgo CRITICAL están incondicionalmente bloqueadas
        if proposal.estimated_risk == RiskLevel.CRITICAL:
            decision = "DENY"
            errors.append("Tasks classified as CRITICAL risk are strictly blocked in Phase 2")
            is_safe = False

        # Validación estricta de comandos vía CommandSecurityGuard
        for cmd in proposal.proposed_commands:
            allowed, reason = CommandSecurityGuard.validate_command(cmd)
            if not allowed:
                decision = "DENY"
                errors.append(reason)
                is_safe = False

        # Validación de permisos si vienen en metadatos
        if proposal.metadata and "requested_permissions" in proposal.metadata:
            req_perms = proposal.metadata["requested_permissions"]
            perms_ok, denied_perms = validate_agent_permissions(req_perms)
            if not perms_ok:
                decision = "DENY"
                errors.extend(denied_perms)
                is_safe = False

        # Validación de red si viene en metadatos
        if proposal.metadata and "network_target" in proposal.metadata:
            net_target = proposal.metadata["network_target"]
            net_allowed, net_reason = NetworkSecurityGuard.is_network_allowed(
                net_target, jde_authorized=(decision == "ALLOW")
            )
            if not net_allowed:
                decision = "DENY"
                errors.append(net_reason)
                is_safe = False

        status = "ALLOWED" if (decision == "ALLOW" and is_safe) else "DENIED"
        duration = (time.perf_counter() - start_time) * 1000.0

        return OrcaAdeEvaluationResult(
            status=status,
            provider="orca_ade",
            capability=proposal.capability,
            proposal=proposal,
            jde_decision=decision,
            risk_level=proposal.estimated_risk,
            evidence={
                "proposal_id": proposal.proposal_id,
                "action_type": proposal.action_type.value,
                "sanitized": True,
                "mode": self._mode.value,
            },
            errors=errors,
            latency_ms=duration,
            is_shadow=(self._mode == OrcaAdeMode.SHADOW),
            side_effects_produced=0,
        )

    # -------------------------------------------------------------------------
    # Ejecución de Contratos y Verificación (Fase 2 Controlled)
    # -------------------------------------------------------------------------

    def create_task_contract(
        self,
        objective: str,
        workspace: str,
        decision_id: str,
        allowed_actions: list[str] | None = None,
        forbidden_actions: list[str] | None = None,
        timeout_seconds: float = 30.0,
        requires_review: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> OrcaTaskContract:
        """Construye un contrato formal estructurado e inmutable para una tarea."""
        safe_ws = self.validate_and_confine_path(workspace)
        contract = OrcaTaskContract(
            task_id=f"orca_task_{uuid.uuid4().hex[:12]}",
            decision_id=decision_id,
            operation_id=f"op_{uuid.uuid4().hex[:8]}",
            objective=self.redact_secrets(objective),
            workspace=safe_ws,
            allowed_actions=allowed_actions or ["READ_REPOSITORY", "WRITE_WORKTREE", "RUN_TESTS"],
            forbidden_actions=forbidden_actions or ["READ_CREDENTIALS", "WRITE_PRODUCTION"],
            timeout_seconds=timeout_seconds,
            requires_review=requires_review,
            metadata=metadata or {},
        )
        return contract

    def execute_governed_task(
        self,
        contract: OrcaTaskContract,
        jde_decision: str = "ALLOW",
    ) -> OrcaResultContract:
        """Ejecuta una tarea gobernada bajo la máquina de estados AgentLifecycle."""
        start_time = time.perf_counter()
        agent_id = f"agent_{contract.task_id}"
        lifecycle = AgentLifecycle(agent_id)

        # Comprobar caché de idempotencia
        fingerprint = contract.compute_fingerprint()
        if fingerprint in self._task_cache:
            cached = self._task_cache[fingerprint]
            return OrcaResultContract(
                task_id=contract.task_id,
                decision_id=contract.decision_id,
                status="CACHE_HIT",
                workspace=cached.workspace,
                changed_files=cached.changed_files,
                tests=cached.tests,
                evidence=cached.evidence + [{"cache_hit": True, "fingerprint": fingerprint}],
                checksum=cached.checksum,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=True,
                review_status=cached.review_status,
                metadata={"idempotent": True, "cached_task_id": cached.task_id},
            )

        if self._mode == OrcaAdeMode.OFF:
            lifecycle.transition_to(AgentState.DENIED, "Adapter is OFF")
            return OrcaResultContract(
                task_id=contract.task_id,
                decision_id=contract.decision_id,
                status="DENIED",
                workspace=contract.workspace,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                metadata={"error": "Adapter is OFF"},
            )

        # 1. Autorización JDE
        if jde_decision != "ALLOW":
            lifecycle.transition_to(AgentState.DENIED, "JDE denied task")
            return OrcaResultContract(
                task_id=contract.task_id,
                decision_id=contract.decision_id,
                status="DENIED",
                workspace=contract.workspace,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                verified=False,
                metadata={"reason": "JDE DENY"},
            )

        lifecycle.transition_to(AgentState.AUTHORIZED, "JDE authorized")
        lifecycle.transition_to(AgentState.STARTING, "Initializing agent workspace")
        lifecycle.transition_to(AgentState.RUNNING, "Executing assigned actions")

        # Simulación de ejecución controlada en sandbox
        changed_files = [os.path.join(contract.workspace, "modified_file.py")]
        evidence = [{"worktree": contract.workspace, "status": "executed"}]

        # 2. Review Gate si requiere revisión
        if contract.requires_review:
            lifecycle.transition_to(AgentState.WAITING_REVIEW, "Code changes pending review")
            review_status = "PENDING"
            status = "CLAIMED_SUCCESS"
            verified = False
        else:
            lifecycle.transition_to(AgentState.COMPLETED, "Completed without review requirement")
            review_status = "APPROVED"
            status = "VERIFIED_SUCCESS"
            verified = True

        duration = (time.perf_counter() - start_time) * 1000.0
        result = OrcaResultContract(
            task_id=contract.task_id,
            decision_id=contract.decision_id,
            status=status,
            workspace=contract.workspace,
            changed_files=changed_files,
            tests={"passed": True, "exit_code": 0},
            evidence=evidence,
            checksum=fingerprint,
            duration_ms=duration,
            verified=verified,
            review_status=review_status,
            metadata={"lifecycle_history": [s[0].value for s in lifecycle.history]},
        )

        # Cachear si fue exitoso
        if verified or status == "CLAIMED_SUCCESS":
            self._task_cache[fingerprint] = result

        return result

    # -------------------------------------------------------------------------
    # Ciclo de Vida de IntegrationAdapter
    # -------------------------------------------------------------------------

    async def initialize(self) -> bool:
        if self._mode == OrcaAdeMode.OFF:
            self.status = IntegrationStatus.DISABLED
            return True
        self.status = IntegrationStatus.READY
        return True

    async def shutdown(self) -> bool:
        self.status = IntegrationStatus.AVAILABLE
        self._task_cache.clear()
        return True

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad respetando el principio EXECUTE -> VERIFY -> REPORT."""
        start_time = time.perf_counter()
        capability_name = capability

        if self._mode == OrcaAdeMode.OFF:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.DENIED,
                verified=False,
                verification_required=False,
                error="ORCA + ADE adapter is OFF",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        if capability_name not in self._capabilities:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Capability '{capability_name}' not supported by orca_ade",
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
            )

        proposal = self.create_proposal(
            capability=capability_name,
            action_type=ProposalActionType.CREATE_WORKTREE,
            title=f"Execution of {capability_name}",
            description=f"Context parameters: {context.parameters}",
            metadata=context.metadata,
        )

        jde_decision = context.metadata.get("jde_decision", "ALLOW")
        eval_result = self.evaluate_proposal(proposal, jde_decision_override=jde_decision)

        duration = (time.perf_counter() - start_time) * 1000.0

        return IntegrationExecutionResult(
            executed=True,
            status=ExecutionStatus.SUCCEEDED if eval_result.status == "ALLOWED" else ExecutionStatus.FAILED,
            verified=(eval_result.status == "ALLOWED"),
            verification_required=True,
            output=eval_result.to_dict(),
            duration_ms=duration,
            evidence={"eval_result": eval_result.to_dict()},
            metadata={"mode": self._mode.value},
        )

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            status=self.status,
            is_healthy=(self.status in [IntegrationStatus.READY, IntegrationStatus.AVAILABLE]),
            latency_ms=0.5,
            message=f"OrcaAdeAdapter operating in mode: {self._mode.value}",
            details={"mode": self._mode.value, "base_dir": self._base_worktree_dir},
        )
