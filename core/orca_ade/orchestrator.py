"""Orquestador Gobernado de ORCA + ADE para JESSYCA PC.

Fase 2 — Controlled Integration.
Implementa el ciclo completo de orquestación agéntica bajo la autoridad del JDE:
    USER -> JESSYCA CORE -> JDE -> RiskEngine -> PermissionManager -> IdempotencyGuard ->
    OrcaAdeOrchestrator -> Isolated Worktree -> ExecutionVerifier -> ReviewGate -> JDE Receipt
"""

from __future__ import annotations

import os
import time
from typing import Any

from core.logger import get_logger
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import (
    AgentLifecycle,
    AgentState,
    OrcaAdeMode,
    OrcaPermission,
    OrcaResultContract,
    OrcaTaskContract,
    validate_agent_permissions,
)
from core.security import RiskLevel
from lab.orca_ade.sandbox import OrcaWorktreeSandbox
from lab.orca_ade.worktree_manager import RealGitWorktreeManager

logger = get_logger("jessyca.orca_ade.orchestrator")


class OrcaGovernedOrchestrator:
    """Orquestador agéntico estrictamente subordinado al JDE y a las capas de seguridad."""

    def __init__(
        self,
        adapter: OrcaAdeAdapter | None = None,
        sandbox: OrcaWorktreeSandbox | None = None,
        git_manager: RealGitWorktreeManager | None = None,
        executor: Any | None = None,
    ) -> None:
        self.adapter = adapter or OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        self.sandbox = sandbox or OrcaWorktreeSandbox()
        self.git_manager = git_manager
        self.executor = executor
        self._active_agents: dict[str, AgentLifecycle] = {}
        self._execution_history: list[OrcaResultContract] = []
        self._idempotency_cache: dict[str, OrcaResultContract] = {}

    @property
    def mode(self) -> OrcaAdeMode:
        return self.adapter.mode

    def dispatch_task(
        self,
        objective: str,
        workspace: str,
        decision_id: str,
        jde_decision: str = "ALLOW",
        allowed_actions: list[str] | None = None,
        forbidden_actions: list[str] | None = None,
        requested_permissions: list[str | OrcaPermission] | None = None,
        estimated_risk: RiskLevel = RiskLevel.SAFE,
        requires_review: bool = True,
        simulate_crash: bool = False,
        simulate_timeout: bool = False,
        simulate_verification_failure: bool = False,
        executor: Any | None = None,
    ) -> OrcaResultContract:
        """Despacha y ejecuta una tarea agéntica gobernada paso a paso."""
        start_time = time.perf_counter()

        # 1. Crear contrato formal estructurado
        contract = self.adapter.create_task_contract(
            objective=objective,
            workspace=workspace,
            decision_id=decision_id,
            allowed_actions=allowed_actions,
            forbidden_actions=forbidden_actions,
            requires_review=requires_review,
        )

        agent_id = f"agent_{contract.task_id}"
        lifecycle = AgentLifecycle(agent_id)
        self._active_agents[agent_id] = lifecycle

        # 2. Idempotencia: comprobar fingerprint SHA-256 (conserva estado de verificación)
        fingerprint = contract.compute_fingerprint()
        if fingerprint in self._idempotency_cache:
            cached = self._idempotency_cache[fingerprint]
            duration = (time.perf_counter() - start_time) * 1000.0
            return OrcaResultContract(
                task_id=contract.task_id,
                decision_id=contract.decision_id,
                status="CACHE_HIT",
                workspace=cached.workspace,
                changed_files=list(cached.changed_files),
                tests=dict(cached.tests),
                evidence=list(cached.evidence) + [{"cache_hit": True, "fingerprint": fingerprint}],
                checksum=cached.checksum,
                duration_ms=duration,
                verified=cached.verified,
                review_status=cached.review_status,
                metadata={"idempotent": True, "cached_task_id": cached.task_id, "cache_hit": True},
            )

        # 3. Control de modo
        if self.adapter.mode == OrcaAdeMode.OFF:
            lifecycle.transition_to(AgentState.DENIED, "Adapter is OFF")
            return self._build_result(contract, "DENIED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="Adapter is OFF")

        # 4. Autoridad Única: JDE
        if jde_decision != "ALLOW":
            lifecycle.transition_to(AgentState.DENIED, "JDE DENY")
            return self._build_result(contract, "DENIED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="JDE DENY")

        # 5. RiskEngine: Tareas CRITICAL están prohibidas
        if estimated_risk == RiskLevel.CRITICAL:
            lifecycle.transition_to(AgentState.DENIED, "Critical risk blocked")
            return self._build_result(contract, "DENIED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="CRITICAL risk blocked in Phase 2")

        # 6. PermissionManager: Validar permisos solicitados
        if requested_permissions:
            perms_ok, denied_reasons = validate_agent_permissions(requested_permissions)
            if not perms_ok:
                lifecycle.transition_to(AgentState.DENIED, f"Permissions denied: {denied_reasons}")
                return self._build_result(contract, "DENIED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="; ".join(denied_reasons))

        # 7. Lifecycle: AUTHORIZED -> STARTING
        lifecycle.transition_to(AgentState.AUTHORIZED, "JDE authorized")
        lifecycle.transition_to(AgentState.STARTING, "Setting up isolated worktree")

        # Inyección de fallos controlados
        if simulate_timeout:
            lifecycle.transition_to(AgentState.TIMEOUT, "Execution timed out")
            return self._build_result(contract, "TIMEOUT", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="Execution timed out")

        # 8. Lifecycle: RUNNING
        lifecycle.transition_to(AgentState.RUNNING, "Executing task actions")

        if simulate_crash:
            lifecycle.transition_to(AgentState.FAILED, "Agent process crashed unexpectedly")
            return self._build_result(contract, "FAILED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="Agent process crashed")

        # 9. Verificación física simulada (Falla inyectada)
        if simulate_verification_failure:
            lifecycle.transition_to(AgentState.VERIFICATION_FAILED, "Physical verification failed: no valid evidence on disk")
            return self._build_result(contract, "VERIFICATION_FAILED", False, duration_ms=(time.perf_counter() - start_time) * 1000.0, reason="Physical evidence missing")

        # 10. Resolución y Ejecución de Tarea Real (Anti-Simulación)
        effective_executor = executor if executor is not None else self.executor
        if effective_executor is None:
            # Regla: Executor ausente no produce éxito.
            lifecycle.transition_to(AgentState.FAILED, "Executor ausente: no hay ejecutor conectado para la tarea")
            return self._build_result(
                contract,
                status="UNAVAILABLE",
                verified=False,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                reason="Executor ausente: no hay ejecutor disponible",
                evidence=[{"error": "EXECUTOR_UNAVAILABLE", "message": "No real executor configured"}],
            )

        try:
            if callable(effective_executor):
                exec_output = effective_executor(contract)
            elif hasattr(effective_executor, "execute"):
                exec_output = effective_executor.execute(contract)
            else:
                raise TypeError(f"Invalid executor object: {type(effective_executor)}")
        except Exception as exc:
            lifecycle.transition_to(AgentState.FAILED, f"Executor execution crashed: {exc}")
            return self._build_result(
                contract,
                status="FAILED",
                verified=False,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                reason=f"Executor crash: {exc}",
                evidence=[{"status": "error", "message": str(exc)}],
            )

        # Derivar resultados de cambios observados y pruebas reales
        tests_data = exec_output.get("tests", {}) if isinstance(exec_output, dict) else getattr(exec_output, "tests", {})
        evidence_data = exec_output.get("evidence", []) if isinstance(exec_output, dict) else getattr(exec_output, "evidence", [])
        raw_changed = exec_output.get("changed_files", []) if isinstance(exec_output, dict) else getattr(exec_output, "changed_files", [])

        # Filtrar a archivos observados que realmente existen en disco
        changed_files = [
            f for f in raw_changed
            if os.path.exists(f) or (contract.workspace and os.path.exists(os.path.join(contract.workspace, f)))
        ]

        # Regla: Prueba fallida conserva el fallo
        if tests_data and (tests_data.get("passed") is False or tests_data.get("exit_code", 0) != 0):
            lifecycle.transition_to(AgentState.FAILED, f"Tests failed: exit code {tests_data.get('exit_code')}")
            return self._build_result(
                contract,
                status="FAILED",
                verified=False,
                duration_ms=(time.perf_counter() - start_time) * 1000.0,
                reason="Pruebas fallidas",
                changed_files=changed_files,
                tests=tests_data,
                evidence=evidence_data,
            )

        # Regla: Evidencia sintética no certifica efectos físicos
        is_synthetic = any(
            e.get("synthetic") or e.get("provenance") == "SYNTHETIC_TEST" or e.get("is_synthetic")
            for e in evidence_data if isinstance(e, dict)
        )

        # 11. Review Gate
        if contract.requires_review:
            lifecycle.transition_to(AgentState.WAITING_REVIEW, "Changes pending human/JDE approval")
            status = "CLAIMED_SUCCESS"
            review_status = "PENDING"
            verified = False
        else:
            lifecycle.transition_to(AgentState.COMPLETED, "Completed without review")
            review_status = "APPROVED"
            if not is_synthetic and len(evidence_data) > 0 and (not tests_data or tests_data.get("passed") is True):
                status = "VERIFIED_SUCCESS"
                verified = True
            else:
                status = "UNVERIFIED"
                verified = False

        duration = (time.perf_counter() - start_time) * 1000.0
        result = OrcaResultContract(
            task_id=contract.task_id,
            decision_id=contract.decision_id,
            status=status,
            workspace=contract.workspace,
            changed_files=changed_files,
            tests=tests_data,
            evidence=evidence_data,
            checksum=fingerprint,
            duration_ms=duration,
            verified=verified,
            review_status=review_status,
            metadata={"lifecycle_history": [s[0].value for s in lifecycle.history]},
        )

        if verified or status == "CLAIMED_SUCCESS":
            self._idempotency_cache[fingerprint] = result

        self._execution_history.append(result)
        return result

    def approve_review(
        self,
        task_id: str,
        approver_authority: str = "JDE",
        verification_evidence: list[dict[str, Any]] | None = None,
    ) -> OrcaResultContract:
        """Aprueba formalmente los cambios de una tarea en espera de revisión.

        Regla: Ejecutar, aprobar y verificar son estados distintos. Una aprobación
        nunca sustituye la comprobación del resultado. Aprobación sin evidencia no
        produce VERIFIED_SUCCESS. Evidencia sintética no certifica efectos físicos.
        """
        for res in self._execution_history:
            if res.task_id == task_id:
                if res.status != "CLAIMED_SUCCESS" or res.review_status != "PENDING":
                    raise ValueError(f"Task '{task_id}' is not in WAITING_REVIEW status")

                agent_id = f"agent_{task_id}"
                if agent_id in self._active_agents:
                    lifecycle = self._active_agents[agent_id]
                    lifecycle.transition_to(AgentState.COMPLETED, f"Approved by {approver_authority}")

                res.review_status = "APPROVED"
                res.metadata["approved_by"] = approver_authority

                # Regla: Ejecutar, aprobar y verificar son estados distintos.
                # Una aprobación nunca sustituye la comprobación del resultado.
                # Aprobación sin evidencia no produce VERIFIED_SUCCESS.
                # Evidencia sintética no certifica efectos físicos.
                has_verification_evidence = (
                    bool(verification_evidence)
                    and not any(
                        e.get("synthetic") or e.get("provenance") == "SYNTHETIC_TEST" or e.get("is_synthetic")
                        for e in verification_evidence if isinstance(e, dict)
                    )
                )

                tests_ok = (
                    not res.tests
                    or (res.tests.get("passed", False) is True and res.tests.get("exit_code", 0) == 0)
                )

                if has_verification_evidence and tests_ok:
                    res.status = "VERIFIED_SUCCESS"
                    res.verified = True
                    if verification_evidence:
                        res.evidence.extend(verification_evidence)
                else:
                    res.status = "APPROVED_UNVERIFIED"
                    res.verified = False

                return res

        raise KeyError(f"Task '{task_id}' not found in execution history")

    def reject_review(self, task_id: str, reason: str = "Rejected by reviewer") -> OrcaResultContract:
        """Rechaza los cambios de una tarea en espera de revisión."""
        for res in self._execution_history:
            if res.task_id == task_id:
                agent_id = f"agent_{task_id}"
                if agent_id in self._active_agents:
                    lifecycle = self._active_agents[agent_id]
                    lifecycle.transition_to(AgentState.DENIED, reason)

                res.review_status = "REJECTED"
                res.status = "DENIED"
                res.verified = False
                res.metadata["rejected_reason"] = reason
                return res

        raise KeyError(f"Task '{task_id}' not found in execution history")

    def _build_result(
        self,
        contract: OrcaTaskContract,
        status: str,
        verified: bool,
        duration_ms: float = 0.0,
        reason: str = "",
        changed_files: list[str] | None = None,
        tests: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> OrcaResultContract:
        res = OrcaResultContract(
            task_id=contract.task_id,
            decision_id=contract.decision_id,
            status=status,
            workspace=contract.workspace,
            changed_files=changed_files or [],
            tests=tests or {},
            evidence=evidence or [],
            duration_ms=duration_ms,
            verified=verified,
            metadata={"reason": reason},
        )
        self._execution_history.append(res)
        return res
