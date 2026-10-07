"""Estado Persistente y Auditoría de Ejecución para ARE (Action Reasoning Engine).

Registra de forma determinista y persistente la evolución temporal de la ejecución
de planes complejos, presupuestos, estados por paso, evidencias físicas de verificación,
denegaciones de seguridad previas y solicitudes de aclaración.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.are.execution_state")


@dataclass
class AREStepExecutionRecord:
    """Registro auditable de la ejecución individual de un paso del grafo."""

    step_id: str
    action_type: str
    status: str = "PENDING"  # PENDING, IN_PROGRESS, SUCCEEDED, FAILED, CANCELLED, DENIED, SKIPPED
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    duration_ms: float = 0.0
    parameters: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    error: str | None = None
    is_verified: bool = False
    retry_count: int = 0

    def mark_completed(self, output: Any, is_verified: bool = True) -> None:
        self.status = "SUCCEEDED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.output = output
        self.is_verified = is_verified

    def mark_failed(self, error: str, is_verified: bool = False) -> None:
        self.status = "FAILED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.error = error
        self.is_verified = is_verified

    def mark_denied(self, reason: str) -> None:
        self.status = "DENIED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.error = reason
        self.is_verified = False

    def mark_cancelled(self) -> None:
        self.status = "CANCELLED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.is_verified = False

    def mark_blocked(self, reason: str) -> None:
        self.status = "BLOCKED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.error = reason
        self.is_verified = False

    def mark_skipped(self, reason: str, output: Any = None) -> None:
        self.status = "SKIPPED"
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000
        self.output = output
        self.error = reason
        self.is_verified = output is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AREPlanExecutionState:
    """Estado persistente del ciclo de vida de un plan ARE en ejecución."""

    task_id: str
    plan_id: str
    goal: str
    status: str = "RUNNING"  # RUNNING, SUCCEEDED, FAILED, CANCELLED, AWAITING_CONFIRMATION, AWAITING_CLARIFICATION
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    total_duration_ms: float = 0.0
    step_records: dict[str, AREStepExecutionRecord] = field(default_factory=dict)
    previously_denied_actions: set[str] = field(default_factory=set)
    clarification_prompt: str | None = None
    max_budget_steps: int = 10
    max_budget_timeout: float = 120.0
    sandbox_dir: str | None = None

    def record_step_start(self, step_id: str, action_type: str, parameters: dict[str, Any]) -> AREStepExecutionRecord:
        rec = AREStepExecutionRecord(
            step_id=step_id,
            action_type=action_type,
            status="IN_PROGRESS",
            parameters=parameters,
        )
        self.step_records[step_id] = rec
        return rec

    def record_step_blocked(self, step_id: str, action_type: str, reason: str) -> AREStepExecutionRecord:
        """Registra un paso dependiente bloqueado debido al fallo de un requisito previo."""
        if step_id in self.step_records:
            rec = self.step_records[step_id]
            rec.mark_blocked(reason)
        else:
            rec = AREStepExecutionRecord(
                step_id=step_id,
                action_type=action_type,
                status="BLOCKED",
                error=reason,
            )
            rec.completed_at = time.time()
            self.step_records[step_id] = rec
        return rec

    def record_step_skipped(self, step_id: str, action_type: str, reason: str, output: Any = None) -> AREStepExecutionRecord:
        """Registra un paso omitido o reutilizado por idempotencia de escritura previa."""
        rec = AREStepExecutionRecord(
            step_id=step_id,
            action_type=action_type,
            status="SKIPPED",
            output=output,
            error=reason,
            is_verified=output is not None,
        )
        rec.completed_at = time.time()
        self.step_records[step_id] = rec
        return rec

    def record_denial(self, action_type: str, step_id: str, reason: str) -> None:
        """Registra una acción denegada por gobernanza. La acción queda marcada irrevocablemente."""
        self.previously_denied_actions.add(action_type)
        if step_id in self.step_records:
            self.step_records[step_id].mark_denied(reason)

    def mark_plan_completed(self) -> None:
        self.status = "SUCCEEDED"
        self.completed_at = time.time()
        self.total_duration_ms = (self.completed_at - self.started_at) * 1000

    def mark_plan_failed(self, error_msg: str) -> None:
        self.status = "FAILED"
        self.completed_at = time.time()
        self.total_duration_ms = (self.completed_at - self.started_at) * 1000

    def mark_plan_cancelled(self) -> None:
        self.status = "CANCELLED"
        self.completed_at = time.time()
        self.total_duration_ms = (self.completed_at - self.started_at) * 1000

    def explain_state(self) -> dict[str, Any]:
        """Genera un diagnóstico explicativo estructurado y legible sobre el estado del plan.

        Explica de manera auditada:
        - qué pasos se completaron exitosamente,
        - qué paso falló y por qué motivo,
        - qué pasos dependientes quedaron bloqueados,
        - qué pasos pueden retomarse en una reanudación sin repetir escrituras previas.
        """
        completed = []
        failed = None
        blocked = []
        skipped = []
        resumable = []

        for sid, rec in self.step_records.items():
            if rec.status == "SUCCEEDED":
                completed.append({
                    "step_id": sid,
                    "action_type": rec.action_type,
                    "duration_ms": rec.duration_ms,
                    "is_verified": rec.is_verified,
                })
            elif rec.status == "FAILED":
                failed = {
                    "step_id": sid,
                    "action_type": rec.action_type,
                    "error": rec.error,
                    "retry_count": rec.retry_count,
                }
                resumable.append(sid)
            elif rec.status == "BLOCKED":
                blocked.append({
                    "step_id": sid,
                    "action_type": rec.action_type,
                    "reason": rec.error or "Dependencia no satisfecha",
                })
                resumable.append(sid)
            elif rec.status == "SKIPPED":
                skipped.append({
                    "step_id": sid,
                    "action_type": rec.action_type,
                    "reason": rec.error or "Reutilizado por idempotencia",
                })
            elif rec.status in ("PENDING", "IN_PROGRESS"):
                resumable.append(sid)

        can_resume = (failed is not None or len(blocked) > 0) and len(resumable) > 0

        # Explicación en lenguaje natural
        lines = [f"Estado general del plan: {self.status} (Objetivo: '{self.goal}')"]
        if completed:
            lines.append(f"• Pasos completados ({len(completed)}): {', '.join(c['step_id'] for c in completed)}")
        if skipped:
            lines.append(f"• Pasos reutilizados/omitidos ({len(skipped)}): {', '.join(s['step_id'] for s in skipped)}")
        if failed:
            lines.append(f"• Paso fallido: {failed['step_id']} ({failed['action_type']}) -> Motivo: {failed['error']}")
        if blocked:
            lines.append(f"• Pasos bloqueados por dependencias ({len(blocked)}): {', '.join(b['step_id'] for b in blocked)}")
        if resumable:
            lines.append(f"• Pasos disponibles para reanudar ({len(resumable)}): {', '.join(resumable)}")
        else:
            lines.append("• No hay pasos pendientes para reanudar.")

        return {
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "completed_steps": completed,
            "failed_step": failed,
            "blocked_steps": blocked,
            "skipped_steps": skipped,
            "resumable_steps": resumable,
            "can_resume": can_resume,
            "summary_explanation": "\n".join(lines),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "goal": self.goal,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
            "previously_denied_actions": list(self.previously_denied_actions),
            "clarification_prompt": self.clarification_prompt,
            "max_budget_steps": self.max_budget_steps,
            "max_budget_timeout": self.max_budget_timeout,
            "sandbox_dir": self.sandbox_dir,
            "explanation": self.explain_state(),
            "steps": {k: v.to_dict() for k, v in self.step_records.items()},
        }

    def save_to_disk(self, target_path: Path | str) -> None:
        """Persiste atómicamente el estado de ejecución en disco."""
        p = Path(target_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        tmp.replace(p)
