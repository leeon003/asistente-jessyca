"""Gestor central del Centro de Control y Observabilidad en Tiempo Real (control_center.py - Fase 24).

Proporciona la interfaz unificada para supervisión de telemetría y controles seguros:
- Visualización de modelo activo, agente, tarea, paso, riesgo, VRAM, tokens, latencia, herramientas y seguridad.
- Controles seguros: STOP (EmergencyStop), PAUSE, RESUME, DETAILS.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. CONTROL CENTER != TOOL EXECUTOR: Prohibida la ejecución directa de herramientas desde la interfaz.
2. CONTROL CENTER != POLICY MANAGER: Prohibida la modificación de políticas de seguridad.
3. STOP prevalece atómicamente a través de EmergencyStopManager.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger
from core.observability.control_center_models import (
    ControlCenterSnapshot,
    ControlCommandResult,
    SystemState,
)
from core.security_architecture import SecurityLevel

logger = get_logger("jessyca.observability.control_center")

MAX_RECORDED_TOOLS: int = 50


class ControlCenter:
    """Núcleo thread-safe de observabilidad y control seguro del sistema."""

    _instance: ClassVar[ControlCenter | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, emergency_stop: EmergencyStopManager | None = None) -> None:
        self._lock = threading.RLock()
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._subscribers: list[Callable[[ControlCenterSnapshot], None]] = []
        self._recent_tools: list[str] = []
        self._security_events_count: int = 0
        self._latest_security_event: str | None = None

        self._snapshot = ControlCenterSnapshot(
            timestamp=datetime.now(UTC),
            state=SystemState.IDLE,
            emergency_stop_active=self.emergency_stop.is_stopped(),
        )

    @classmethod
    def get_instance(cls) -> ControlCenter:
        """Obtiene la instancia singleton global del ControlCenter."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ControlCenter()
            return cls._instance

    def reset(self, reason: str = "cleanup") -> None:
        """Restablece el estado del ControlCenter para aislamiento de pruebas."""
        with self._lock:
            self._recent_tools.clear()
            self._security_events_count = 0
            self._latest_security_event = None
            self._snapshot = ControlCenterSnapshot(
                timestamp=datetime.now(UTC),
                state=SystemState.IDLE,
                emergency_stop_active=self.emergency_stop.is_stopped(),
            )

    # ── ACTUALIZACIÓN DE ESTADO Y TELEMETRÍA ──

    def update_state(
        self,
        state: SystemState,
        active_model: str | None = None,
        active_agent: str | None = None,
        current_task: str | None = None,
        current_step: str | None = None,
        risk_level: SecurityLevel | None = None,
        vram_mb: float | None = None,
        tokens_consumed: int | None = None,
        latency_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> ControlCenterSnapshot:
        """Actualiza el estado global del sistema y notifica a los observadores registrados."""
        with self._lock:
            is_stopped = self.emergency_stop.is_stopped()
            resolved_state = SystemState.STOPPED if is_stopped else state

            self._snapshot = ControlCenterSnapshot(
                timestamp=datetime.now(UTC),
                state=resolved_state,
                active_model=active_model if active_model is not None else self._snapshot.active_model,
                active_agent=active_agent if active_agent is not None else self._snapshot.active_agent,
                current_task=current_task if current_task is not None else self._snapshot.current_task,
                current_step=current_step if current_step is not None else self._snapshot.current_step,
                risk_level=risk_level if risk_level is not None else self._snapshot.risk_level,
                vram_mb=vram_mb if vram_mb is not None else self._snapshot.vram_mb,
                tokens_consumed=tokens_consumed if tokens_consumed is not None else self._snapshot.tokens_consumed,
                latency_ms=latency_ms if latency_ms is not None else self._snapshot.latency_ms,
                tools_executed=tuple(self._recent_tools),
                security_events_count=self._security_events_count,
                latest_security_event=self._latest_security_event,
                emergency_stop_active=is_stopped,
                details=details if details is not None else self._snapshot.details,
            )
            snapshot_copy = self._snapshot
            subscribers_copy = list(self._subscribers)

        # Notificar fuera del lock para evitar deadlocks
        for sub in subscribers_copy:
            try:
                sub(snapshot_copy)
            except Exception as e:
                logger.warning(f"[CONTROL CENTER SUBSCRIBER ERROR] Error al notificar suscriptor: {e}")

        return snapshot_copy

    def record_tool_execution(self, tool_name: str) -> None:
        """Registra una herramienta ejecutada en el buffer circular de telemetría."""
        with self._lock:
            self._recent_tools.append(tool_name)
            if len(self._recent_tools) > MAX_RECORDED_TOOLS:
                self._recent_tools.pop(0)

            self.update_state(state=self._snapshot.state)

    def record_security_event(self, description: str) -> None:
        """Registra un evento o alerta de seguridad observado."""
        with self._lock:
            self._security_events_count += 1
            self._latest_security_event = str(description).strip()
            self.update_state(state=self._snapshot.state)

    def get_snapshot(self) -> ControlCenterSnapshot:
        """Retorna la última instantánea de observabilidad inmutable."""
        with self._lock:
            is_stopped = self.emergency_stop.is_stopped()
            if is_stopped and self._snapshot.state != SystemState.STOPPED:
                return self.update_state(state=SystemState.STOPPED)
            return self._snapshot

    def subscribe(self, callback: Callable[[ControlCenterSnapshot], None]) -> Callable[[], None]:
        """Registra un listener reactivo y retorna una función de desuscripción."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    # ── CONTROLES SEGUROS ──

    def stop(self, reason: str = "Parada solicitada desde Centro de Control") -> ControlCommandResult:
        """Ejecuta la Parada de Emergencia formal a través de EmergencyStopManager."""
        self.emergency_stop.trigger_stop(reason=reason, source="control_center_ui")
        updated = self.update_state(state=SystemState.STOPPED)

        logger.critical(f"[CONTROL CENTER STOP EXECUTED] {reason}")
        return ControlCommandResult(
            command="STOP",
            success=True,
            message="Parada de Emergencia activada exitosamente.",
            current_state=updated.state,
            data={"reason": reason, "emergency_stop_active": True},
        )

    def pause(self, reason: str = "Pausa solicitada desde Centro de Control") -> ControlCommandResult:
        """Pausa controladamente el sistema."""
        with self._lock:
            if self.emergency_stop.is_stopped():
                return ControlCommandResult(
                    command="PAUSE",
                    success=False,
                    message="No se puede pausar: El sistema se encuentra en Parada de Emergencia (STOPPED).",
                    current_state=SystemState.STOPPED,
                )

            updated = self.update_state(state=SystemState.PAUSED, details={"pause_reason": reason})
            logger.info(f"[CONTROL CENTER PAUSE EXECUTED] {reason}")
            return ControlCommandResult(
                command="PAUSE",
                success=True,
                message="Sistema pausado controladamente.",
                current_state=updated.state,
                data={"reason": reason},
            )

    def resume(self, reason: str = "Reanudación solicitada desde Centro de Control") -> ControlCommandResult:
        """Reanuda la operación si la Parada de Emergencia no está activa."""
        with self._lock:
            if self.emergency_stop.is_stopped():
                return ControlCommandResult(
                    command="RESUME",
                    success=False,
                    message="No se puede reanudar: La Parada de Emergencia sigue activa. Requiere reset() explícito de seguridad.",
                    current_state=SystemState.STOPPED,
                )

            updated = self.update_state(state=SystemState.RUNNING, details={"resume_reason": reason})
            logger.info(f"[CONTROL CENTER RESUME EXECUTED] {reason}")
            return ControlCommandResult(
                command="RESUME",
                success=True,
                message="Operación reanudada exitosamente.",
                current_state=updated.state,
                data={"reason": reason},
            )

    def get_details(self) -> ControlCommandResult:
        """Retorna un reporte detallado del estado del sistema, telemetría y diagnósticos."""
        with self._lock:
            snap = self.get_snapshot()
            data = {
                "snapshot": snap.to_dict(),
                "active_subscribers": len(self._subscribers),
                "recorded_tools_count": len(self._recent_tools),
                "security_events_total": self._security_events_count,
            }
            return ControlCommandResult(
                command="DETAILS",
                success=True,
                message="Detalles de telemetría y estado obtenidos correctamente.",
                current_state=snap.state,
                data=data,
            )


def get_control_center() -> ControlCenter:
    """Acceso helper al singleton global de ControlCenter."""
    return ControlCenter.get_instance()
