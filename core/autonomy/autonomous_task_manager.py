"""Administrador de Tareas Autónomas y Persistencia (autonomous_task_manager.py - Fase 15).

Orquesta el ciclo de vida de tareas programadas persistentes sobre el sistema de agentes especializados:
- Cancelación (cancel_task)
- Pausa y Reanudación (pause_task / resume_task)
- Recuperación segura tras reinicio (recover_on_startup)
- Acotamiento estricto por presupuesto (AgentBudget)
- Integración inmediata con EmergencyStop

INVARIANTE DE SEGURIDAD ABSOLUTA:
- SCHEDULER != AUTHORIZATION / TASK != AUTHORIZATION / AGENT != AUTHORIZATION.
- Ningún agente puede modificar su propio nivel de autonomía.
- Toda acción individual vuelve al pipeline de seguridad.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.agents.base_agent import BaseSpecializedAgent
from core.agents.desktop_agent import DesktopAgent
from core.agents.file_agent import FileAgent
from core.agents.system_agent import SystemAgent
from core.autonomy.autonomous_task_models import (
    AutonomousTaskDefinition,
    AutonomousTaskStatus,
)
from core.autonomy.autonomy_level import TaskActionRisk
from core.control_plane.models import AgentBudget, AgentLoopResult, AgentLoopState
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger

logger = get_logger("jessyca.autonomy.task_manager")


class AutonomousTaskManager:
    """Gestor central de tareas autónomas persistentes con ciclo de vida y control de seguridad."""

    def __init__(
        self,
        storage_path: Path | str = "data/autonomous_tasks.json",
        agents_catalog: dict[str, BaseSpecializedAgent] | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._lock = threading.RLock()
        self._tasks: dict[str, AutonomousTaskDefinition] = {}

        # Catálogo de agentes ejecutores
        if agents_catalog:
            self._agents_catalog = dict(agents_catalog)
        else:
            desk = DesktopAgent(emergency_stop=self.emergency_stop)
            sys = SystemAgent(emergency_stop=self.emergency_stop)
            file_ag = FileAgent(emergency_stop=self.emergency_stop)
            self._agents_catalog = {
                desk.identity.agent_id: desk,
                sys.identity.agent_id: sys,
                file_ag.identity.agent_id: file_ag,
            }

        # Cargar tareas persistidas
        self._load_tasks()

    def create_task(
        self,
        intent: str,
        schedule: str,
        agent_id: str = "agent_system",
        owner: str = "user",
        allowed_tools: tuple[str, ...] = (),
        max_steps: int = 10,
        max_time_seconds: float = 30.0,
        risk_ceiling: TaskActionRisk = TaskActionRisk.MEDIUM_RISK,
        metadata: dict[str, Any] | None = None,
    ) -> AutonomousTaskDefinition:
        """Crea y persiste una nueva tarea autónoma con presupuesto acotado."""
        task_id = f"autotask-{uuid.uuid4().hex[:8]}"

        budget = AgentBudget.create(
            max_steps=max_steps,
            max_time=max_time_seconds,
            max_actions=max_steps,
            max_risk=risk_ceiling,
        )

        task = AutonomousTaskDefinition(
            task_id=task_id,
            owner=owner,
            schedule=schedule,
            agent_id=agent_id,
            intent=intent,
            allowed_tools=allowed_tools,
            budget=budget,
            max_steps=max_steps,
            max_time_seconds=max_time_seconds,
            risk_ceiling=risk_ceiling,
            status=AutonomousTaskStatus.PENDING,
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._tasks[task_id] = task
            self._save_tasks()

        logger.info(f"[AUTONOMOUS TASK CREATED] Tarea '{task_id}' creada para agente '{agent_id}' ({schedule}).")
        return task

    def get_task(self, task_id: str) -> AutonomousTaskDefinition | None:
        """Obtiene la definición de una tarea por su identificador."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, status: AutonomousTaskStatus | None = None) -> list[AutonomousTaskDefinition]:
        """Lista todas las tareas registradas, opcionalmente filtradas por estado."""
        with self._lock:
            if status is None:
                return list(self._tasks.values())
            return [t for t in self._tasks.values() if t.status == status]

    def cancel_task(self, task_id: str) -> bool:
        """Cancela determinísticamente una tarea autónoma."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (AutonomousTaskStatus.CANCELLED, AutonomousTaskStatus.COMPLETED):
                return True

            updated = task.with_status(AutonomousTaskStatus.CANCELLED)
            self._tasks[task_id] = updated
            self._save_tasks()
            logger.info(f"[AUTONOMOUS TASK CANCELLED] Tarea '{task_id}' cancelada.")
            return True

    def pause_task(self, task_id: str) -> bool:
        """Pausa una tarea autónoma impidiendo su ejecución automática."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status == AutonomousTaskStatus.CANCELLED:
                return False

            updated = task.with_status(AutonomousTaskStatus.PAUSED)
            self._tasks[task_id] = updated
            self._save_tasks()
            logger.info(f"[AUTONOMOUS TASK PAUSED] Tarea '{task_id}' pausada.")
            return True

    def resume_task(self, task_id: str) -> bool:
        """Reanuda una tarea autónoma previamente pausada."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status != AutonomousTaskStatus.PAUSED:
                return False

            updated = task.with_status(AutonomousTaskStatus.PENDING)
            self._tasks[task_id] = updated
            self._save_tasks()
            logger.info(f"[AUTONOMOUS TASK RESUMED] Tarea '{task_id}' reanudada a PENDING.")
            return True

    def execute_task(self, task_id: str, custom_executor: Callable[[str], AgentLoopResult] | None = None) -> AgentLoopResult:
        """Ejecuta una tarea autónoma programada a través del agente especializado asignado."""
        with self._lock:
            task = self._tasks.get(task_id)

        if not task:
            return AgentLoopResult(
                task_id=task_id,
                intent="",
                final_state=AgentLoopState.STOPPED_ERROR,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason=f"Tarea autónoma '{task_id}' no encontrada.",
            )

        # 1. Comprobar estado ejecutable
        if task.status in (AutonomousTaskStatus.PAUSED, AutonomousTaskStatus.CANCELLED):
            return AgentLoopResult(
                task_id=task_id,
                intent=task.intent,
                final_state=AgentLoopState.STOPPED_PERMISSION_DENIED,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason=f"La tarea '{task_id}' no puede ejecutarse en estado '{task.status}'.",
            )

        # 2. Comprobar Parada de Emergencia
        if self.emergency_stop.is_stopped():
            with self._lock:
                self._tasks[task_id] = task.with_status(AutonomousTaskStatus.FAILED, error="EMERGENCY_STOP_ACTIVE")
                self._save_tasks()
            return AgentLoopResult(
                task_id=task_id,
                intent=task.intent,
                final_state=AgentLoopState.STOPPED_EMERGENCY,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason="Parada de emergencia activa. Ejecución autónoma abortada.",
            )

        # 3. Marcar estado RUNNING
        with self._lock:
            self._tasks[task_id] = task.with_status(AutonomousTaskStatus.RUNNING)
            self._save_tasks()

        # 4. Resolver agente ejecutor
        agent = self._agents_catalog.get(task.agent_id)
        if not agent and not custom_executor:
            with self._lock:
                self._tasks[task_id] = task.with_status(AutonomousTaskStatus.FAILED, error=f"Agente '{task.agent_id}' no encontrado.")
                self._save_tasks()
            return AgentLoopResult(
                task_id=task_id,
                intent=task.intent,
                final_state=AgentLoopState.STOPPED_ERROR,
                iterations_executed=0,
                tools_executed=0,
                tokens_consumed=0,
                duration_seconds=0.0,
                stop_reason=f"Agente especializado '{task.agent_id}' no registrado en el catálogo.",
            )

        # 5. Ejecutar la tarea bajo ControlledAgentLoop
        logger.info(f"[AUTONOMOUS TASK RUNNING] Ejecutando '{task_id}' con agente '{task.agent_id}': '{task.intent}'")

        if custom_executor:
            result = custom_executor(task.intent)
        else:
            assert agent is not None
            result = agent.run(intent=task.intent)

        # 6. Actualizar estado post-ejecución
        with self._lock:
            final_task_status = AutonomousTaskStatus.COMPLETED if result.is_success else AutonomousTaskStatus.FAILED
            self._tasks[task_id] = self._tasks[task_id].with_status(
                final_task_status,
                error=result.stop_reason if not result.is_success else None,
            )
            self._save_tasks()

        return result

    def recover_on_startup(self) -> dict[str, int]:
        """Recupera y revalida las tareas persistidas tras un reinicio del sistema."""
        with self._lock:
            recovered_count = len(self._tasks)
            paused_dangerous = 0

            updated_tasks: dict[str, AutonomousTaskDefinition] = {}
            for tid, t in self._tasks.items():
                # Si una tarea estaba en RUNNING al momento del crash/reinicio -> FAILED / REQUIRES_RESTART
                if t.status == AutonomousTaskStatus.RUNNING:
                    updated_tasks[tid] = t.with_status(AutonomousTaskStatus.PENDING, error="Recuperada tras reinicio del sistema.")
                # Si la tarea posee un techo de riesgo DANGEROUS/CRITICAL, se pausa por seguridad preventiva
                elif t.risk_ceiling in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
                    updated_tasks[tid] = t.with_status(AutonomousTaskStatus.PAUSED, error="Pausada preventivamente por riesgo elevado tras reinicio.")
                    paused_dangerous += 1
                else:
                    updated_tasks[tid] = t

            self._tasks = updated_tasks
            self._save_tasks()

            logger.info(
                f"[STARTUP RECOVERY] {recovered_count} tareas recuperadas. "
                f"{paused_dangerous} tareas de alto riesgo pausadas para revisión."
            )
            return {"recovered_tasks": recovered_count, "paused_for_review": paused_dangerous}

    def _load_tasks(self) -> None:
        """Carga las tareas desde el archivo JSON si existe."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        t = AutonomousTaskDefinition.from_dict(item)
                        self._tasks[t.task_id] = t
                elif isinstance(data, dict):
                    for item in data.values():
                        t = AutonomousTaskDefinition.from_dict(item)
                        self._tasks[t.task_id] = t
        except Exception as e:
            logger.error(f"[AUTONOMOUS TASK STORAGE] Error cargando tareas persistidas: {e}")

    def _save_tasks(self) -> None:
        """Guarda las tareas en el almacenamiento persistente JSON de forma atómica."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            serialized = [t.to_dict() for t in self._tasks.values()]
            temp_file = self.storage_path.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.storage_path)
        except Exception as e:
            logger.error(f"[AUTONOMOUS TASK STORAGE] Error guardando tareas persistidas: {e}")
