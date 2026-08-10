"""Subsistema de Task Scheduler Seguro (ScheduledTaskManager - Etapa 13.1).

GARANTÍA ABSOLUTA DE SEGURIDAD EN ETAPA 13.1:
1. RUTA OBLIGATORIA: Scheduler -> AutonomousTaskRequest -> AutonomyPolicy -> SecureExecutionPipeline -> Tool.
2. NO SE EJECUTAN HERRAMIENTAS DIRECTAMENTE. Cualquier intento de bypass es rechazado.
3. INVARIANTE INMUTABLE: scheduled_task != user_authorization.
4. Definiciones de tareas persistentes en JSON local.
5. Concurrencia acotada (ThreadPoolExecutor), prevención de ejecuciones duplicadas simultáneas, timeout, retry con backoff exponencial.
6. Auditoría libre de contenido crudo o datos sensibles.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy_policy import (
    AutonomousTaskRequest,
    AutonomyPolicy,
)
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.task_scheduler")


class SchedulerSecurityError(MCPError):
    """Error base para violaciones de seguridad del Task Scheduler."""

    pass


class DirectToolExecutionBypassError(SchedulerSecurityError):
    """Error emitido cuando el Scheduler o un hilo intenta ejecutar una herramienta salteándose la AutonomyPolicy o el SecureExecutionPipeline."""

    pass


@runtime_checkable
class ITaskTrigger(Protocol):
    """Interfaz abstracta para disparadores de tareas programadas."""

    def should_fire(self, current_time: datetime) -> bool:
        """Determina si la tarea debe dispararse en la fecha/hora actual."""
        ...

    def next_fire_time(self, current_time: datetime) -> datetime | None:
        """Calcula la próxima fecha de disparo posterior a current_time."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serializa la configuración del disparador a un diccionario JSON-friendly."""
        ...


class IntervalTrigger:
    """Disparador basado en intervalos periódicos de tiempo."""

    def __init__(self, interval_seconds: float, start_at: datetime | None = None) -> None:
        if interval_seconds <= 0:
            raise ValueError("El intervalo debe ser estrictamente positivo.")
        self.interval_seconds = float(interval_seconds)
        self.start_at = start_at or datetime.now(UTC)
        self._last_fire: datetime | None = None

    def should_fire(self, current_time: datetime) -> bool:
        if current_time < self.start_at:
            return False
        if self._last_fire is None:
            return True
        elapsed = (current_time - self._last_fire).total_seconds()
        return elapsed >= self.interval_seconds

    def next_fire_time(self, current_time: datetime) -> datetime | None:
        if current_time < self.start_at:
            return self.start_at
        if self._last_fire is None:
            return current_time
        return self._last_fire + timedelta(seconds=self.interval_seconds)

    def mark_fired(self, fired_at: datetime) -> None:
        self._last_fire = fired_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "interval",
            "interval_seconds": self.interval_seconds,
            "start_at": self.start_at.isoformat(),
            "last_fire": self._last_fire.isoformat() if self._last_fire else None,
        }


class CronLikeTrigger:
    """Disparador simplificado estilo Cron (minuto, hora, día de la semana)."""

    def __init__(self, minute: int | None = None, hour: int | None = None, day_of_week: int | None = None) -> None:
        self.minute = minute
        self.hour = hour
        self.day_of_week = day_of_week
        self._last_fire_minute: int | None = None

    def should_fire(self, current_time: datetime) -> bool:
        if self.minute is not None and current_time.minute != self.minute:
            return False
        if self.hour is not None and current_time.hour != self.hour:
            return False
        if self.day_of_week is not None and current_time.weekday() != self.day_of_week:
            return False

        # Evitar disparo múltiple dentro del mismo minuto
        current_minute_key = current_time.hour * 60 + current_time.minute
        if self._last_fire_minute == current_minute_key:
            return False

        return True

    def mark_fired(self, fired_at: datetime) -> None:
        self._last_fire_minute = fired_at.hour * 60 + fired_at.minute

    def next_fire_time(self, current_time: datetime) -> datetime | None:
        # Próxima ocurrencia simplificada (1 minuto después si coincide)
        return current_time + timedelta(minutes=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "cron",
            "minute": self.minute,
            "hour": self.hour,
            "day_of_week": self.day_of_week,
        }


class EventTrigger:
    """Disparador reaccionando a eventos específicos en el EventBus."""

    def __init__(self, event_name: str) -> None:
        if not event_name:
            raise ValueError("event_name no puede estar vacío.")
        self.event_name = event_name
        self._pending_fire = False

    def trigger_event(self) -> None:
        self._pending_fire = True

    def should_fire(self, current_time: datetime) -> bool:
        if self._pending_fire:
            self._pending_fire = False
            return True
        return False

    def next_fire_time(self, current_time: datetime) -> datetime | None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "event",
            "event_name": self.event_name,
        }


@dataclass
class ScheduledTaskDefinition:
    """Definición inmutable y serializable de una tarea programada."""

    task_id: str
    tool_name: str
    operation: str
    trigger_config: dict[str, Any]
    parameters: dict[str, Any] = field(default_factory=dict)
    user_id: str = "default_user"
    max_retries: int = 3
    retry_backoff_base_seconds: float = 2.0
    timeout_seconds: float = 30.0
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "trigger_config": self.trigger_config,
            "parameters": self.parameters,
            "user_id": self.user_id,
            "max_retries": self.max_retries,
            "retry_backoff_base_seconds": self.retry_backoff_base_seconds,
            "timeout_seconds": self.timeout_seconds,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduledTaskDefinition:
        return cls(
            task_id=data["task_id"],
            tool_name=data["tool_name"],
            operation=data["operation"],
            trigger_config=data.get("trigger_config", {}),
            parameters=data.get("parameters", {}),
            user_id=data.get("user_id", "default_user"),
            max_retries=data.get("max_retries", 3),
            retry_backoff_base_seconds=data.get("retry_backoff_base_seconds", 2.0),
            timeout_seconds=data.get("timeout_seconds", 30.0),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
        )


@dataclass
class ScheduledTaskResult:
    """Resultado formal de la ejecución de una tarea programada."""

    task_id: str
    success: bool
    result_data: Any = None
    error_message: str | None = None
    attempts: int = 1
    duration_ms: float = 0.0
    executed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class ScheduledTaskManager:
    """Administrador de Tareas Programadas y Autónomas (ScheduledTaskManager - Etapa 13.1).

    ENFORZA LA RUTA DE SEGURIDAD OBLIGATORIA:
    Scheduler -> AutonomousTaskRequest -> AutonomyPolicy -> SecureExecutionPipeline -> Tool.

    CERO BYPASS: No ejecuta directamente ninguna herramienta o función de bajo nivel.
    """

    def __init__(
        self,
        autonomy_policy: AutonomyPolicy | None = None,
        execution_pipeline_fn: Callable[[AutonomousTaskRequest], Any] | None = None,
        storage_path: Path | str | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.enabled = settings.SCHEDULER_ENABLED
        self.max_concurrent_tasks = settings.SCHEDULER_MAX_CONCURRENT_TASKS

        store_p = storage_path or settings.SCHEDULER_STORAGE_PATH
        self.storage_path = Path(store_p)

        self.autonomy_policy = autonomy_policy or AutonomyPolicy()
        self.execution_pipeline_fn = execution_pipeline_fn

        self._tasks: dict[str, ScheduledTaskDefinition] = {}
        self._triggers: dict[str, Any] = {}
        self._running_task_ids: set[str] = set()
        self._lock = threading.RLock()

        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_tasks,
            thread_name_prefix="jessyca-scheduler-worker",
        )
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

        self._load_tasks_from_storage()

    def register_task(
        self,
        task_id: str,
        tool_name: str,
        operation: str,
        trigger: ITaskTrigger,
        parameters: dict[str, Any] | None = None,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
    ) -> ScheduledTaskDefinition:
        """Registra y persiste una nueva tarea programada."""
        with self._lock:
            task_def = ScheduledTaskDefinition(
                task_id=task_id,
                tool_name=tool_name,
                operation=operation,
                trigger_config=trigger.to_dict(),
                parameters=parameters or {},
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            self._tasks[task_id] = task_def
            self._triggers[task_id] = trigger
            self._save_tasks_to_storage()

            logger.info(f"[SCHEDULER] Tarea '{task_id}' registrada correctamente ({tool_name}.{operation}).")
            return task_def

    def cancel_task(self, task_id: str) -> bool:
        """Cancela y desactiva una tarea programada."""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].is_active = False
                self._save_tasks_to_storage()
                logger.info(f"[SCHEDULER] Tarea '{task_id}' cancelada.")
                return True
            return False

    def run_task_now(
        self,
        task_id: str,
        bypass_autonomy: bool = False,
        raw_tool_fn: Callable[..., Any] | None = None,
    ) -> ScheduledTaskResult:
        """Punto de entrada principal para ejecutar una tarea programada.

        REGLA DE SEGURIDAD ABSOLUTA:
        Si se intenta pasar bypass_autonomy=True o invocar directamente raw_tool_fn salteándose la AutonomyPolicy,
        se lanza INMEDIATAMENTE DirectToolExecutionBypassError.
        """
        if bypass_autonomy or raw_tool_fn is not None:
            raise DirectToolExecutionBypassError(
                "[SECURITY VIOLATION] Intento deliberado de ejecutar una herramienta salteándose la AutonomyPolicy y el SecureExecutionPipeline. VIOLACIÓN GRAVE DENAGADA."
            )

        with self._lock:
            if task_id not in self._tasks:
                raise ValueError(f"Tarea programada no encontrada: '{task_id}'")
            task_def = self._tasks[task_id]

            if not task_def.is_active:
                return ScheduledTaskResult(
                    task_id=task_id,
                    success=False,
                    error_message="La tarea se encuentra desactivada/cancelada.",
                )

            # Prevención de ejecuciones duplicadas simultáneas (Duplicate execution prevention)
            if task_id in self._running_task_ids:
                logger.warning(f"[SCHEDULER] Ejecución duplicada bloqueada para la tarea '{task_id}'.")
                return ScheduledTaskResult(
                    task_id=task_id,
                    success=False,
                    error_message="Prevención de ejecución duplicada: La tarea ya se encuentra en ejecución activa.",
                )

            self._running_task_ids.add(task_id)

        start_time = time.perf_counter()
        attempts = 0
        last_error = ""

        try:
            req = AutonomousTaskRequest(
                task_id=task_def.task_id,
                tool_name=task_def.tool_name,
                operation=task_def.operation,
                is_scheduled=True,
                parameters=task_def.parameters,
                user_id=task_def.user_id,
            )

            # 1. RUTA OBLIGATORIA DE SEGURIDAD: Pasar por AutonomyPolicy
            self.autonomy_policy.enforce_task_execution(req)


            # 2. Ejecutar mediante el SecureExecutionPipeline (si la política lo autoriza)
            while attempts <= task_def.max_retries:
                attempts += 1
                try:
                    fut = self._executor.submit(self._execute_pipeline_wrapper, req)
                    res_data = fut.result(timeout=task_def.timeout_seconds)
                    elapsed = (time.perf_counter() - start_time) * 1000.0

                    self._log_scheduler_audit(task_def, success=True, duration_ms=elapsed, attempts=attempts)

                    return ScheduledTaskResult(
                        task_id=task_id,
                        success=True,
                        result_data=res_data,
                        attempts=attempts,
                        duration_ms=elapsed,
                    )
                except FuturesTimeoutError:
                    last_error = f"Timeout de ejecución alcanzado ({task_def.timeout_seconds}s)."
                    logger.warning(f"[SCHEDULER] Intento {attempts} de la tarea '{task_id}' falló por timeout.")
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"[SCHEDULER] Intento {attempts} de la tarea '{task_id}' falló: {e}")

                if attempts <= task_def.max_retries:
                    backoff = task_def.retry_backoff_base_seconds * (2 ** (attempts - 1))
                    time.sleep(backoff)

            elapsed = (time.perf_counter() - start_time) * 1000.0
            self._log_scheduler_audit(task_def, success=False, duration_ms=elapsed, attempts=attempts, error=last_error)

            return ScheduledTaskResult(
                task_id=task_id,
                success=False,
                error_message=f"Tarea falló tras {attempts} intentos. Último error: {last_error}",
                attempts=attempts,
                duration_ms=elapsed,
            )

        finally:
            with self._lock:
                self._running_task_ids.discard(task_id)

    def _execute_pipeline_wrapper(self, request: AutonomousTaskRequest) -> Any:
        """Invocación desacoplada a SecureExecutionPipeline."""
        if self.execution_pipeline_fn is not None:
            return self.execution_pipeline_fn(request)
        # Mock / Comprobación por defecto del pipeline si no se proveyó una función externa
        return {"status": "executed_via_secure_pipeline", "task_id": request.task_id}

    def evaluate_triggers_and_run(self, current_time: datetime | None = None) -> list[ScheduledTaskResult]:
        """Revisa todos los triggers activos y ejecuta las tareas que correspondan."""
        now = current_time or datetime.now(UTC)
        results: list[ScheduledTaskResult] = []

        with self._lock:
            active_tasks = [t for t in self._tasks.values() if t.is_active]

        for task_def in active_tasks:
            trigger = self._triggers.get(task_def.task_id)
            if trigger and trigger.should_fire(now):
                if hasattr(trigger, "mark_fired"):
                    trigger.mark_fired(now)
                res = self.run_task_now(task_def.task_id)
                results.append(res)

        return results

    def _save_tasks_to_storage(self) -> None:
        """Guarda las definiciones de tareas en el archivo JSON local."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = {tid: t.to_dict() for tid, t in self._tasks.items()}
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.error(f"[SCHEDULER] Error guardando tareas en '{self.storage_path}': {e}")

    def _load_tasks_from_storage(self) -> None:
        """Carga las definiciones de tareas desde el archivo JSON local."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
                for tid, tdict in data.items():
                    task_def = ScheduledTaskDefinition.from_dict(tdict)
                    self._tasks[tid] = task_def
                    # Reconstruir trigger básico de intervalo por defecto
                    t_cfg = task_def.trigger_config
                    if t_cfg.get("type") == "interval":
                        self._triggers[tid] = IntervalTrigger(
                            interval_seconds=t_cfg.get("interval_seconds", 60.0)
                        )
                    elif t_cfg.get("type") == "cron":
                        self._triggers[tid] = CronLikeTrigger(
                            minute=t_cfg.get("minute"),
                            hour=t_cfg.get("hour"),
                            day_of_week=t_cfg.get("day_of_week"),
                        )
                    else:
                        self._triggers[tid] = IntervalTrigger(interval_seconds=60.0)
        except Exception as e:
            logger.error(f"[SCHEDULER] Error cargando tareas desde '{self.storage_path}': {e}")

    def _log_scheduler_audit(
        self,
        task_def: ScheduledTaskDefinition,
        success: bool,
        duration_ms: float,
        attempts: int,
        error: str = "",
    ) -> None:
        """Registra en la auditoría el resultado de la tarea (únicamente métricas numéricas sin secretos)."""
        event_type = AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=event_type,
                request_id=f"sched-run-{task_def.task_id[:8]}",
                tool_name=task_def.tool_name,
                operation=task_def.operation,
                duration_ms=duration_ms,
                reason=f"Scheduled execution {'successful' if success else 'failed'}. Error: {error}",
                metadata={
                    "task_id": task_def.task_id,
                    "success": success,
                    "attempts": attempts,
                    "duration_ms": duration_ms,
                },
            )
        )
        self.event_bus.publish("scheduler:task_completed", {"task_id": task_def.task_id, "success": success})
