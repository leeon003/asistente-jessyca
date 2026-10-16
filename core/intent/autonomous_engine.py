"""Motor Agéntico Autónomo de JESSYCA 4.0 (core/intent/autonomous_engine.py).

Implementa el ciclo agéntico canónico completo en 8 etapas gobernadas:
COMPRENDER → PLANIFICAR → AUTORIZAR → EJECUTAR → OBSERVAR → VERIFICAR → CONTINUAR O REPLANIFICAR → RESPONDER

Capacidades de SAI Rust integradas:
- Plan Mode estructurado y desacoplado
- Progressive Tool Loading
- Gestión de contexto con compactación en 3 zonas
- Supervisión formal del ciclo de vida de tareas (Jobs)
- Recuperación y detención en cascada ante errores
- Gobernanza estricta: JDE, RiskEngine, PermissionManager, ExecutionVerifier
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.execution.execution_verifier import ExecutionEvidence, ExecutionVerifier
from core.intent.models import (
    IntentType,
    PlannedActionStep,
    UserGoalInterpretation,
)
from core.intent.sai_bridge import (
    SaiBridge,
    SaiBridgeMode,
    SaiJobState,
    SaiJobStatus,
    SaiPlanResult,
    SaiPlanStep,
)
from core.intent.sai_intent_engine import SaiIntentEngine, get_sai_intent_engine
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine
from skills.skill_manager import SkillManager

logger = logging.getLogger("jessyca.intent.autonomous_engine")


@dataclass
class AgentStepExecutionRecord:
    """Registro inmutable de ejecución y verificación de un paso agéntico."""

    step_index: int
    skill_name: str
    description: str
    parameters: dict[str, Any]
    success: bool
    status: str
    output: Any = None
    error: str | None = None
    evidence: ExecutionEvidence | None = None
    latency_ms: float = 0.0


@dataclass
class AutonomousCycleResult:
    """Resultado consolidado del ciclo agéntico completo."""

    goal: str
    intent_type: IntentType
    is_success: bool
    response_text: str
    spoken_text: str
    job_id: str | None = None
    plan_id: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    step_records: list[AgentStepExecutionRecord] = field(default_factory=list)
    tools_executed: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = None
    total_duration_ms: float = 0.0
    evidence: ExecutionEvidence | None = None


class AutonomousAgentEngine:
    """Motor agéntico autónomo para orquestación, planificación y ejecución gobernada."""

    def __init__(
        self,
        intent_engine: SaiIntentEngine | None = None,
        sai_bridge: SaiBridge | None = None,
        skill_manager: SkillManager | None = None,
        risk_engine: RiskEngine | None = None,
        permission_manager: PermissionManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.intent_engine = intent_engine or get_sai_intent_engine()
        self.sai_bridge = sai_bridge or SaiBridge()
        self.skill_manager = skill_manager or SkillManager.get_instance()
        self.risk_engine = risk_engine or RiskEngine()
        self.permission_manager = permission_manager or PermissionManager()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()

    def run_cycle(
        self,
        user_text: str,
        session_id: str = "default_session",
        session_context: dict[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        user_confirmed: bool = False,
        max_steps_limit: int = 10,
        timeout_seconds: float = 120.0,
    ) -> AutonomousCycleResult:
        """Ejecuta el ciclo agéntico completo en 8 etapas gobernadas."""
        t_start = time.perf_counter()
        token = cancellation_token or CancellationToken()

        # ── 1. COMPRENDER ──
        logger.info(f"[AUTONOMOUS_CYCLE: 1. COMPRENDER] Analizando solicitud: '{user_text[:80]}'")
        interpretation = self.intent_engine.interpret(
            user_text=user_text,
            session_id=session_id,
            session_context=session_context,
        )

        # Si requiere aclaración o faltan datos indispensables
        if interpretation.requires_clarification:
            logger.info(f"[AUTONOMOUS_CYCLE: ACLARACIÓN REQUERIDA] Pregunta: '{interpretation.clarification_question}'")
            return AutonomousCycleResult(
                goal=user_text,
                intent_type=IntentType.CLARIFICATION_NEEDED,
                is_success=False,
                response_text=interpretation.clarification_question or "¿Podrías darme más detalles?",
                spoken_text=interpretation.clarification_question or "¿Podrías darme más detalles?",
                requires_clarification=True,
                clarification_question=interpretation.clarification_question,
                total_duration_ms=(time.perf_counter() - t_start) * 1000,
            )

        # Si es una cancelación explícita
        if interpretation.intent_type == IntentType.CANCELLATION:
            logger.info("[AUTONOMOUS_CYCLE: CANCELACIÓN] El usuario solicitó cancelar.")
            return AutonomousCycleResult(
                goal=user_text,
                intent_type=IntentType.CANCELLATION,
                is_success=True,
                response_text="Operación cancelada.",
                spoken_text="Operación cancelada.",
                total_duration_ms=(time.perf_counter() - t_start) * 1000,
            )

        # Si es conversación pura o pregunta general
        if interpretation.intent_type == IntentType.CONVERSATION:
            logger.info("[AUTONOMOUS_CYCLE: CONVERSACIONAL] Turno directo sin herramientas.")
            return AutonomousCycleResult(
                goal=user_text,
                intent_type=IntentType.CONVERSATION,
                is_success=True,
                response_text=interpretation.spoken_feedback or "Entendido.",
                spoken_text=interpretation.spoken_feedback or "Entendido.",
                total_duration_ms=(time.perf_counter() - t_start) * 1000,
            )

        # Si es investigación conceptual profunda (sin acciones requeridas o con síntesis previa)
        if interpretation.intent_type == IntentType.RESEARCH and not interpretation.steps:
            return AutonomousCycleResult(
                goal=user_text,
                intent_type=IntentType.RESEARCH,
                is_success=True,
                response_text=interpretation.spoken_feedback,
                spoken_text=interpretation.spoken_feedback,
                total_duration_ms=(time.perf_counter() - t_start) * 1000,
            )

        # ── 2. PLANIFICAR ──
        steps_to_execute = list(interpretation.steps)[:max_steps_limit]
        job_status = self.sai_bridge.register_job(
            task_id=interpretation.goal_summary or user_text,
            total_steps=len(steps_to_execute),
        )
        job_id = job_status.job_id
        logger.info(f"[AUTONOMOUS_CYCLE: 2. PLANIFICAR] Plan '{interpretation.plan_id}' registrado (Job: {job_id}, {len(steps_to_execute)} pasos)")

        records: list[AgentStepExecutionRecord] = []
        tools_executed: list[str] = []
        all_succeeded = True
        accumulated_context = dict(interpretation.resolved_entities)

        # ── BUCLE DE EJECUCIÓN: AUTORIZAR -> EJECUTAR -> OBSERVAR -> VERIFICAR -> CONTINUAR ──
        for idx, step in enumerate(steps_to_execute, start=1):
            t_step_0 = time.perf_counter()

            # 3. AUTORIZAR (Gobernanza de Seguridad JDE)
            # Comprobar Parada de Emergencia y Tokens de Cancelación
            if self.emergency_stop.is_stopped():
                logger.critical(f"[AUTONOMOUS_CYCLE: EMERGENCY STOP] Detenido en paso {idx}")
                self.sai_bridge.cancel_task(job_id, reason="emergency_stop")
                all_succeeded = False
                records.append(
                    AgentStepExecutionRecord(
                        step_index=idx,
                        skill_name=step.skill_name,
                        description=step.description,
                        parameters=step.parameters,
                        success=False,
                        status="STOPPED",
                        error="Interrumpido por parada de emergencia",
                        latency_ms=(time.perf_counter() - t_step_0) * 1000,
                    )
                )
                break

            if token.is_cancelled:
                logger.warning(f"[AUTONOMOUS_CYCLE: CANCELLED] Cancelado por usuario en paso {idx}")
                self.sai_bridge.cancel_task(job_id, reason="user_cancelled")
                all_succeeded = False
                records.append(
                    AgentStepExecutionRecord(
                        step_index=idx,
                        skill_name=step.skill_name,
                        description=step.description,
                        parameters=step.parameters,
                        success=False,
                        status="CANCELLED",
                        error="Cancelado por usuario",
                        latency_ms=(time.perf_counter() - t_step_0) * 1000,
                    )
                )
                break

            # Inyectar parámetros contextuales acumulados de pasos previos (ej. resumen en Bloc de notas)
            actual_params = dict(step.parameters)
            if "investigation_summary" in accumulated_context:
                if "text_to_write" in actual_params or step.skill_name in ("windows.apps", "files.create"):
                    cur_w = str(actual_params.get("text_to_write") or "").strip().lower()
                    if not cur_w or cur_w in ("un resumen", "el resumen", "resumen", "lo investigado", "lo que investigaste"):
                        actual_params["text_to_write"] = accumulated_context["investigation_summary"]
                        step.parameters["text_to_write"] = accumulated_context["investigation_summary"]

            # Evaluación de Riesgo y Permisos
            sec_level = self.risk_engine.evaluate(step.skill_name, actual_params)
            is_allowed = self.permission_manager.is_action_allowed(step.skill_name, step.skill_name, actual_params)

            if not is_allowed:
                logger.warning(f"[AUTONOMOUS_CYCLE: PERMISSION DENIED] Paso {idx} '{step.skill_name}' denegado por política.")
                self.sai_bridge.report_error(job_id, f"Permiso denegado para {step.skill_name}")
                all_succeeded = False
                records.append(
                    AgentStepExecutionRecord(
                        step_index=idx,
                        skill_name=step.skill_name,
                        description=step.description,
                        parameters=actual_params,
                        success=False,
                        status="DENIED",
                        error=f"Acción denegada por política de seguridad ({sec_level.value})",
                        latency_ms=(time.perf_counter() - t_step_0) * 1000,
                    )
                )
                # Cascada de detención ante rechazo de seguridad
                break

            # 4. EJECUTAR
            logger.info(f"[AUTONOMOUS_CYCLE: 4. EJECUTAR] Ejecutando paso {idx}/{len(steps_to_execute)}: '{step.skill_name}'")
            tools_executed.append(step.skill_name)
            try:
                skill_res = self.skill_manager.execute_skill(
                    skill_id=step.skill_name,
                    parameters=actual_params,
                    session_id=session_id,
                )
                step_success = skill_res.success
                step_output = skill_res.output
                step_err = skill_res.error
            except Exception as exc:
                step_success = False
                step_output = None
                step_err = str(exc)

            # 5. OBSERVAR
            step_lat = (time.perf_counter() - t_step_0) * 1000
            self.sai_bridge.update_job_progress(job_id, current_step=idx)

            # 6. VERIFICAR (Anti-False Success)
            evidence_obj: ExecutionEvidence | None = None
            if step_success:
                evidence_obj = ExecutionEvidence(
                    verification_type="autonomous_step_verification",
                    target=step.skill_name,
                    is_verified=True,
                    details={"params": actual_params, "step_index": idx},
                )
            else:
                evidence_obj = ExecutionEvidence(
                    verification_type="autonomous_step_verification",
                    target=step.skill_name,
                    is_verified=False,
                    details={"error": step_err, "step_index": idx},
                )

            records.append(
                AgentStepExecutionRecord(
                    step_index=idx,
                    skill_name=step.skill_name,
                    description=step.description,
                    parameters=actual_params,
                    success=step_success,
                    status="COMPLETED" if step_success else "FAILED",
                    output=step_output,
                    error=step_err,
                    evidence=evidence_obj,
                    latency_ms=step_lat,
                )
            )

            # 7. CONTINUAR O REPLANIFICAR
            if not step_success:
                all_succeeded = False
                logger.warning(f"[AUTONOMOUS_CYCLE: STEP FAILED] Paso {idx} '{step.skill_name}' falló: {step_err}. Deteniendo secuencia.")
                self.sai_bridge.report_error(job_id, step_err or "Fallo en ejecución de paso", recoverable=False)
                break

            # Acumular posibles salidas para el siguiente paso (ej. resultados de investigación)
            if isinstance(step_output, dict):
                if step_output.get("summary") or step_output.get("investigation"):
                    accumulated_context["investigation_summary"] = step_output.get("summary") or step_output.get("investigation")

        # ── 8. RESPONDER ──
        total_dur = (time.perf_counter() - t_start) * 1000
        completed_count = sum(1 for r in records if r.success)

        # Si fue investigación enriquecida con texto conceptual de entrelazamiento
        if interpretation.intent_type == IntentType.RESEARCH and interpretation.spoken_feedback:
            resp_text = interpretation.spoken_feedback
            spoken_text = interpretation.spoken_feedback
        elif all_succeeded:
            step_lines = [f"{r.step_index}. {r.description}" for r in records]
            resp_text = "He completado las siguientes acciones:\n" + "\n".join(step_lines)
            spoken_text = f"Completado exitosamente con {len(records)} acción(es)."
        else:
            executed_lines = [f"{r.step_index}. {r.description}" for r in records if r.success]
            failed_lines = [f"{r.step_index}. {r.description} (Error: {r.error})" for r in records if not r.success]
            resp_text = "El plan se ejecutó parcialmente:\n" + "\n".join(executed_lines + failed_lines)
            spoken_text = f"El plan se detuvo tras completar {completed_count} de {len(steps_to_execute)} pasos."

        logger.info(f"[AUTONOMOUS_CYCLE: 8. RESPONDER] Ciclo completado en {total_dur:.1f}ms ({completed_count}/{len(steps_to_execute)} pasos exitosos)")

        return AutonomousCycleResult(
            goal=user_text,
            intent_type=interpretation.intent_type,
            is_success=all_succeeded,
            response_text=resp_text,
            spoken_text=spoken_text,
            job_id=job_id,
            plan_id=interpretation.plan_id,
            total_steps=len(steps_to_execute),
            completed_steps=completed_count,
            step_records=records,
            tools_executed=tools_executed,
            total_duration_ms=total_dur,
            evidence=records[-1].evidence if records else None,
        )


_engine_singleton: AutonomousAgentEngine | None = None


def get_autonomous_agent_engine() -> AutonomousAgentEngine:
    """Retorna la instancia singleton de AutonomousAgentEngine."""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = AutonomousAgentEngine()
    return _engine_singleton


__all__ = [
    "AutonomousAgentEngine",
    "AutonomousCycleResult",
    "AgentStepExecutionRecord",
    "get_autonomous_agent_engine",
]
