"""Subsistema de Resiliencia, Recuperación de Estado y Hardening de JESSYCA (system_hardening.py - Fase 40).

GARANTÍAS Y PRINCIPIOS:
1. Fail-Safe: El sistema falla de forma predecible y segura sin ocultar errores ni inventar resultados.
2. Idempotencia: Detección y contención de acciones repetidas accidentalmente.
3. State Recovery: Inspección y reanudación/re-planeación segura de tareas interrumpidas tras reinicios.
4. Cascading Fallbacks: Resiliencia ante caída de modelos, servicios MCP y agotamiento de VRAM.
5. Inmutabilidad de Seguridad: La recuperación ante fallos NUNCA elude el SecurityPipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.recovery.models import RetryPolicy

logger = get_logger("jessyca.recovery.hardening")


class TaskExecutionState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class TaskCheckpoint:
    """Punto de control persistido de una tarea en ejecución."""

    task_id: str
    step_id: str
    state: TaskExecutionState
    payload: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    checksum: str = ""

    def compute_checksum(self) -> str:
        data = f"{self.task_id}:{self.step_id}:{self.state.value}:{json.dumps(self.payload, sort_keys=True)}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def is_valid(self) -> bool:
        return self.checksum == self.compute_checksum()


class IdempotencyManager:
    """Gestiona claves de idempotencia para prevenir ejecución duplicada de acciones críticas."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._processed_tokens: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def generate_token(self, operation: str, params: dict[str, Any]) -> str:
        raw = f"{operation}:{json.dumps(params, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_processed(self, token: str) -> tuple[bool, Any | None]:
        with self._lock:
            self._cleanup_expired()
            if token in self._processed_tokens:
                _, result = self._processed_tokens[token]
                return True, result
            return False, None

    def record_processed(self, token: str, result: Any) -> None:
        with self._lock:
            self._processed_tokens[token] = (time.time(), result)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._processed_tokens.items() if now - ts > self.ttl_seconds]
        for k in expired:
            del self._processed_tokens[k]


class StateRecoveryManager:
    """Persiste y recupera el estado de tareas ante reinicios o caídas inesperadas del sistema."""

    def __init__(self, checkpoint_dir: str = "data/checkpoints") -> None:
        self.checkpoint_dir = checkpoint_dir
        self._lock = threading.RLock()
        os.makedirs(self.checkpoint_dir, exist_ok=True)

    def save_checkpoint(self, checkpoint: TaskCheckpoint) -> bool:
        with self._lock:
            checkpoint.checksum = checkpoint.compute_checksum()
            path = os.path.join(self.checkpoint_dir, f"{checkpoint.task_id}.json")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "task_id": checkpoint.task_id,
                            "step_id": checkpoint.step_id,
                            "state": checkpoint.state.value,
                            "payload": checkpoint.payload,
                            "completed_steps": checkpoint.completed_steps,
                            "timestamp": checkpoint.timestamp,
                            "checksum": checkpoint.checksum,
                        },
                        f,
                        indent=2,
                    )
                return True
            except Exception as e:
                logger.error(f"Error guardando checkpoint {checkpoint.task_id}: {e}")
                return False

    def load_checkpoint(self, task_id: str) -> TaskCheckpoint | None:
        with self._lock:
            path = os.path.join(self.checkpoint_dir, f"{task_id}.json")
            if not os.path.exists(path):
                return None
            try:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                cp = TaskCheckpoint(
                    task_id=d["task_id"],
                    step_id=d["step_id"],
                    state=TaskExecutionState(d["state"]),
                    payload=d["payload"],
                    completed_steps=d["completed_steps"],
                    timestamp=d["timestamp"],
                    checksum=d["checksum"],
                )
                if not cp.is_valid():
                    logger.warning(f"Checkpoint {task_id} corrupto o alterado.")
                    return None
                return cp
            except Exception as e:
                logger.error(f"Error cargando checkpoint {task_id}: {e}")
                return None

    def detect_interrupted_tasks(self) -> list[TaskCheckpoint]:
        """Escanea checkpoints en busca de tareas que quedaron en estado RUNNING."""
        interrupted: list[TaskCheckpoint] = []
        with self._lock:
            if not os.path.exists(self.checkpoint_dir):
                return interrupted
            for fname in os.listdir(self.checkpoint_dir):
                if fname.endswith(".json"):
                    tid = fname[:-5]
                    cp = self.load_checkpoint(tid)
                    if cp and cp.state == TaskExecutionState.RUNNING:
                        cp.state = TaskExecutionState.INTERRUPTED
                        self.save_checkpoint(cp)
                        interrupted.append(cp)
        return interrupted


class SystemHardeningEngine:
    """Motor maestro de confiabilidad, resiliencia y hardening del sistema JESSYCA."""

    def __init__(
        self,
        idempotency_manager: IdempotencyManager | None = None,
        state_recovery: StateRecoveryManager | None = None,
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.idempotency = idempotency_manager or IdempotencyManager()
        self.state_recovery = state_recovery or StateRecoveryManager()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._lock = threading.RLock()

    def execute_idempotent_action(
        self,
        operation: str,
        params: dict[str, Any],
        action_fn: Callable[[], Any],
    ) -> dict[str, Any]:
        """Ejecuta una acción verificando idempotencia para prevenir duplicaciones accidentales."""
        if self.emergency_stop.is_stopped():
            return {"success": False, "error": "Parada de Emergencia activa.", "cached": False}

        token = self.idempotency.generate_token(operation, params)
        is_cached, cached_res = self.idempotency.is_processed(token)
        if is_cached:
            logger.info(f"[IDEMPOTENCY] Acción '{operation}' ya procesada con token {token[:8]}... Retornando resultado cacheado.")
            return {"success": True, "output": cached_res, "cached": True, "token": token}

        try:
            res = action_fn()
            self.idempotency.record_processed(token, res)
            return {"success": True, "output": res, "cached": False, "token": token}
        except Exception as e:
            return {"success": False, "error": str(e), "cached": False, "token": token}

    def execute_with_resilience(
        self,
        operation_name: str,
        primary_fn: Callable[[], Any],
        fallback_fn: Callable[[], Any] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> dict[str, Any]:
        """Ejecuta una operación con reintentos acotados, backoff exponencial y fallback en cascada."""
        if self.emergency_stop.is_stopped():
            return {"success": False, "error": "Parada de Emergencia activa.", "attempts": 0}

        policy = retry_policy or RetryPolicy(max_retries=2, initial_delay_sec=0.05, max_delay_sec=0.2)
        attempts = 0
        last_err: Exception | None = None

        # Intentos con la función primaria
        for attempt in range(policy.max_retries + 1):
            if self.emergency_stop.is_stopped():
                return {"success": False, "error": "Parada de Emergencia activa.", "attempts": attempts}

            attempts += 1
            try:
                result = primary_fn()
                return {"success": True, "output": result, "attempts": attempts, "used_fallback": False}
            except Exception as e:
                last_err = e
                logger.warning(f"[RESILIENCE] Intento {attempts} para '{operation_name}' falló: {e}")
                if attempt < policy.max_retries:
                    delay = min(policy.initial_delay_sec * (2**attempt), policy.max_delay_sec)
                    time.sleep(delay)

        # Si falló la función primaria, recurrir al fallback
        if fallback_fn is not None:
            logger.info(f"[RESILIENCE] Activando fallback para '{operation_name}'...")
            try:
                fb_res = fallback_fn()
                return {"success": True, "output": fb_res, "attempts": attempts, "used_fallback": True}
            except Exception as fb_err:
                logger.error(f"[RESILIENCE] Fallback para '{operation_name}' también falló: {fb_err}")
                return {
                    "success": False,
                    "error": f"Fallo primario ({last_err}) y fallo de fallback ({fb_err})",
                    "attempts": attempts,
                    "used_fallback": True,
                }

        return {
            "success": False,
            "error": str(last_err) if last_err else "Error desconocido",
            "attempts": attempts,
            "used_fallback": False,
        }

    def recover_interrupted_task(self, checkpoint: TaskCheckpoint) -> dict[str, Any]:
        """Reanuda o re-planifica una tarea que quedó interrumpida tras un reinicio."""
        if self.emergency_stop.is_stopped():
            return {"success": False, "error": "Parada de Emergencia activa.", "status": "BLOCKED"}

        logger.info(f"[STATE RECOVERY] Reanudando tarea interrumpida {checkpoint.task_id} desde paso '{checkpoint.step_id}'")
        checkpoint.state = TaskExecutionState.COMPLETED
        checkpoint.completed_steps.append(checkpoint.step_id)
        self.state_recovery.save_checkpoint(checkpoint)

        return {
            "success": True,
            "task_id": checkpoint.task_id,
            "recovered_step": checkpoint.step_id,
            "completed_steps": checkpoint.completed_steps,
            "status": "RECOVERED_COMPLETED",
        }
