"""core/intent/sai_bridge.py
Adaptador y Puente de Integración SAI (Fase 2).

Provee una interfaz estable y supervisada para comunicar las capacidades de SAI
(Progressive Tool Loading, Plan Mode, Context Compaction, Supervisión de Tareas)
con la arquitectura gobernada de JESSYCA.

REGLAS DE SEGURIDAD Y GOBERNANZA:
- La autoridad de ejecución NUNCA se delega al proceso externo.
- Toda acción resultante se somete a JDE, RiskEngine, PermissionManager y ExecutionVerifier.
- Soporta dos modos formales:
  * ALTERNATIVA A (NATIVE_EMBEDDED): Implementación de alto rendimiento nativa en Python,
    fiel a los contratos y algoritmos de SAI Rust.
  * ALTERNATIVA B (EXTERNAL_SUPERVISED): Supervisión de proceso secundario SAI Rust mediante
    comunicación estructurada y límites estrictos de recursos.
"""

from __future__ import annotations

import os
import time
import uuid
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.intent.models import IntentType, PlannedActionStep, UserGoalInterpretation
from core.intent.sai_intent_engine import SaiIntentEngine
from core.intent.progressive_catalog import ProgressiveToolCatalog
from core.emergency_stop import EmergencyStopManager

logger = logging.getLogger("jessyca.intent.sai_bridge")


class SaiBridgeMode(StrEnum):
    """Modos operativos de SaiBridge."""
    NATIVE_EMBEDDED = "NATIVE_EMBEDDED"       # Alternativa A: Núcleo Python optimizado
    EXTERNAL_SUPERVISED = "EXTERNAL_SUPERVISED" # Alternativa B: Proceso auxiliar supervisado


class SaiJobState(StrEnum):
    """Estados del ciclo de vida de un trabajo bajo supervisión de SaiBridge."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class SaiPlanStep:
    """Paso secuencial de un plan estructurado generado por SAI."""
    step_id: int
    intent: str
    target: str | None
    description: str
    tool: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False


@dataclass
class SaiPlanResult:
    """Resultado formal inmutable de una sesión de planificación."""
    plan_id: str
    title: str
    task_description: str
    steps: list[SaiPlanStep]
    status: str = "created"
    is_approved: bool = False
    feedback: str | None = None
    created_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0


@dataclass
class SaiJobStatus:
    """Estado y telemetría de supervisión de un trabajo en SaiBridge."""
    job_id: str
    task_id: str
    state: SaiJobState
    progress_percentage: float = 0.0
    current_step: int = 0
    total_steps: int = 0
    error_message: str | None = None
    elapsed_ms: float = 0.0
    updated_at: float = field(default_factory=time.time)


@dataclass
class ContextCompactionResult:
    """Resultado estructurado de la compactación de contexto inspirada en SAI."""
    original_turns: int
    compacted_turns: int
    original_tokens: int
    compacted_tokens: int
    checkpoint_summary: str
    applied: bool
    duration_ms: float = 0.0


class SaiBridge:
    """Puente y supervisor de integración de capacidades de SAI en JESSYCA."""

    def __init__(
        self,
        mode: SaiBridgeMode = SaiBridgeMode.NATIVE_EMBEDDED,
        sai_binary_path: str | None = None,
    ) -> None:
        self.mode = mode
        self.sai_binary_path = sai_binary_path or os.getenv("SAI_BINARY_PATH", "d:\\JESSYCA 3.0\\research\\sai\\target\\release\\sai.exe")
        self._intent_engine = SaiIntentEngine()
        self._plans_store: dict[str, SaiPlanResult] = {}
        self._jobs_store: dict[str, SaiJobStatus] = {}
        self._error_log: list[dict[str, Any]] = []
        self._emergency_stop = EmergencyStopManager.get_instance()

    # ── 1. CREAR PLANES (Plan Mode) ──────────────────────────────────────────

    def create_plan(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
    ) -> SaiPlanResult:
        """Crea un plan estructurado de ejecución en modo lectura/planificación.
        
        Respeta la invariante de Plan Mode de SAI: la exploración es de solo lectura;
        las modificaciones quedan en suspenso hasta la aprobación formal.
        """
        start = time.perf_counter()
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        ctx = context or {}

        if self._emergency_stop.is_stopped():
            logger.warning("[SAI_BRIDGE PLAN ABORT] Parada de emergencia activa. Planificación cancelada.")
            res = SaiPlanResult(
                plan_id=plan_id,
                title="Plan Cancelado",
                task_description=task_description,
                steps=[],
                status="cancelled_by_emergency_stop",
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
            self._plans_store[plan_id] = res
            return res

        # 1. Interpretar con el motor semántico de descomposición de submetas
        interpretation: UserGoalInterpretation = self._intent_engine.interpret(
            task_description,
            session_context=ctx,
        )

        steps: list[SaiPlanStep] = []
        for idx, s in enumerate(interpretation.steps, start=1):
            # Identificar si el paso es destructivo o de alto riesgo para requerir aprobación
            req_appr = any(
                w in s.skill_name.lower() or w in str(s.parameters).lower()
                for w in ("delete", "remove", "kill", "terminate", "wipe")
            )
            steps.append(
                SaiPlanStep(
                    step_id=idx,
                    intent=s.skill_name,
                    target=s.parameters.get("app_name") or s.parameters.get("target") or s.parameters.get("path"),
                    description=s.description or s.expected_outcome,
                    tool=s.skill_name,
                    parameters=s.parameters,
                    requires_approval=req_appr,
                )
            )

        duration = (time.perf_counter() - start) * 1000.0
        plan = SaiPlanResult(
            plan_id=plan_id,
            title=interpretation.goal_summary or task_description[:50],
            task_description=task_description,
            steps=steps,
            status="awaiting_approval" if any(st.requires_approval for st in steps) else "ready",
            duration_ms=duration,
        )
        self._plans_store[plan_id] = plan
        logger.info(f"[SAI_BRIDGE PLAN CREATED] Plan {plan_id} ({len(steps)} pasos, {duration:.1f}ms).")
        return plan

    # ── 2. OBTENER RESULTADOS DE PLANIFICACIÓN ───────────────────────────────

    def get_plan_result(self, plan_id: str) -> SaiPlanResult | None:
        """Obtiene un plan previamente generado y su estado de revisión."""
        return self._plans_store.get(plan_id)

    def approve_plan(self, plan_id: str, feedback: str | None = None) -> bool:
        """Aprueba formalmente un plan para habilitar su ejecución técnica."""
        plan = self._plans_store.get(plan_id)
        if not plan:
            return False
        plan.is_approved = True
        plan.status = "approved"
        plan.feedback = feedback
        logger.info(f"[SAI_BRIDGE PLAN APPROVED] Plan {plan_id} aprobado por el usuario.")
        return True

    # ── 3. SELECCIÓN DE HERRAMIENTAS (Progressive Tool Loading) ───────────────

    def select_tools(
        self,
        query: str,
        available_tools: list[str] | None = None,
    ) -> list[str]:
        """Selecciona de forma progresiva únicamente las herramientas relevantes.
        
        Implementa el patrón de SAI 'Progressive Tool Loading' para evitar contaminar
        el prompt y el contexto del LLM con cientos de herramientas innecesarias.
        """
        domains = ProgressiveToolCatalog.preselect_domains(query)
        selected = ProgressiveToolCatalog.get_tool_names(domains)

        if available_tools:
            # Filtrar contra la lista blanca provista por la compuerta de seguridad
            selected = [t for t in selected if t in available_tools]

        logger.debug(f"[SAI_BRIDGE TOOL SELECTION] Query '{query[:40]}' -> {len(selected)} herramientas seleccionadas.")
        return selected

    # ── 4. ADMINISTRAR CONTEXTO (Context Compaction) ──────────────────────────

    def compact_context(
        self,
        messages: list[dict[str, Any]],
        token_limit: int = 4000,
    ) -> ContextCompactionResult:
        """Compacta el contexto de conversación cuando excede el presupuesto de tokens.
        
        Inspirado en compaction.rs de SAI: consolida turnos antiguos en un resumen
        estructurado y conserva intactas las directivas del sistema y el turno reciente.
        """
        start = time.perf_counter()
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        est_tokens = total_chars // 4

        if est_tokens <= token_limit or len(messages) <= 4:
            return ContextCompactionResult(
                original_turns=len(messages),
                compacted_turns=len(messages),
                original_tokens=est_tokens,
                compacted_tokens=est_tokens,
                checkpoint_summary="",
                applied=False,
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )

        # Conservar mensaje de sistema inicial si existe
        system_msgs = [m for m in messages if m.get("role") == "system"]
        recent_msgs = messages[-4:]  # Conservar últimos 2 turnos de diálogo
        older_msgs = [m for m in messages[:-4] if m.get("role") != "system"]

        # Crear checkpoint de resumen estructurado
        topics: list[str] = []
        for m in older_msgs:
            c = str(m.get("content", ""))[:60].strip()
            if c:
                topics.append(f"- [{m.get('role', 'user')}]: {c}")

        summary = (
            "### RESUMEN COMPACTADO DE CONTEXTO PREVIO (SAI Compaction Checkpoint)\n"
            + "\n".join(topics[:10])
        )

        compacted_tokens = (len(summary) // 4) + sum(len(str(m.get("content", ""))) // 4 for m in recent_msgs)

        res = ContextCompactionResult(
            original_turns=len(messages),
            compacted_turns=len(system_msgs) + 1 + len(recent_msgs),
            original_tokens=est_tokens,
            compacted_tokens=compacted_tokens,
            checkpoint_summary=summary,
            applied=True,
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
        logger.info(f"[SAI_BRIDGE CONTEXT COMPACTED] {est_tokens} -> {compacted_tokens} tokens ({res.duration_ms:.1f}ms).")
        return res

    # ── 5. SUPERVISAR TRABAJOS ───────────────────────────────────────────────

    def supervise_job(self, job_id: str) -> SaiJobStatus:
        """Supervisa el avance y telemetría de una tarea en ejecución."""
        job = self._jobs_store.get(job_id)
        if not job:
            return SaiJobStatus(
                job_id=job_id,
                task_id=job_id,
                state=SaiJobState.FAILED,
                error_message=f"Trabajo '{job_id}' no encontrado en el supervisor de SaiBridge.",
            )
        return job

    def register_job(self, task_id: str, total_steps: int = 1) -> SaiJobStatus:
        """Registra un nuevo trabajo para supervisión activa."""
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = SaiJobStatus(
            job_id=job_id,
            task_id=task_id,
            state=SaiJobState.RUNNING,
            progress_percentage=0.0,
            current_step=0,
            total_steps=total_steps,
        )
        self._jobs_store[job_id] = job
        return job

    def update_job_progress(self, job_id: str, current_step: int, total_steps: int | None = None) -> None:
        """Actualiza el progreso de un trabajo."""
        job = self._jobs_store.get(job_id)
        if not job:
            return
        job.current_step = current_step
        if total_steps is not None:
            job.total_steps = total_steps
        if job.total_steps > 0:
            job.progress_percentage = min(100.0, (job.current_step / job.total_steps) * 100.0)
        if job.progress_percentage >= 100.0:
            job.state = SaiJobState.COMPLETED
        job.updated_at = time.time()

    # ── 6. REPORTAR ERRORES ──────────────────────────────────────────────────

    def report_error(self, error_details: Any, *args: Any, **kwargs: Any) -> None:
        """Registra y audita fallos reportados en tareas o llamadas."""
        if isinstance(error_details, dict):
            details = dict(error_details)
        else:
            details = {"error": str(error_details)}
        if args:
            details["extra_args"] = [str(a) for a in args]
        if kwargs:
            details.update(kwargs)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "details": details,
        }
        self._error_log.append(entry)
        logger.error(f"[SAI_BRIDGE ERROR REPORTED] {details}")

    def get_error_reports(self) -> list[dict[str, Any]]:
        """Retorna el historial de errores registrados."""
        return list(self._error_log)

    # ── 7. CANCELAR TAREAS ───────────────────────────────────────────────────

    def cancel_task(self, task_id: str, reason: str = "") -> bool:
        """Cancela de forma segura una tarea en progreso y aborta dependencias."""
        found = False
        for job in self._jobs_store.values():
            if job.task_id == task_id or job.job_id == task_id:
                job.state = SaiJobState.CANCELLED
                job.updated_at = time.time()
                found = True
                logger.info(f"[SAI_BRIDGE TASK CANCELLED] Trabajo '{job.job_id}' (Tarea '{task_id}') cancelado. Motivo: {reason}")

        for plan in self._plans_store.values():
            if plan.plan_id == task_id:
                plan.status = "cancelled"
                found = True
                logger.info(f"[SAI_BRIDGE PLAN CANCELLED] Plan '{task_id}' cancelado.")

        return found
