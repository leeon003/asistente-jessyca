"""Mecanismo global y thread-safe de Parada de Emergencia / Fail-Safe (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Capa de control independiente del ciclo de razonamiento del agente.
Estados explícitos: RUNNING, STOP_REQUESTED, STOPPED, FAULTED.
Cuando la Parada de Emergencia está ACTIVA, TODA acción sobre la interfaz gráfica del escritorio
es DENEGADA E INTERRUMPIDA INMEDIATAMENTE con prioridad sobre cualquier decisión ALLOW o confirmación.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.emergency_stop")


class EmergencyStopState(StrEnum):
    """Estados explícitos del subsistema de Parada de Emergencia."""

    RUNNING = "RUNNING"
    STOP_REQUESTED = "STOP_REQUESTED"
    STOPPED = "STOPPED"
    FAULTED = "FAULTED"


class EmergencyStopError(MCPError):
    """Error base del subsistema de Parada de Emergencia."""

    pass


class EmergencyStopTriggeredError(EmergencyStopError):
    """Error emitido cuando una acción es abortada por la activación de Parada de Emergencia."""

    pass


class CancellationToken:
    """Token de cancelación thread-safe basado en eventos no bloqueantes."""

    def __init__(self, event: threading.Event | None = None) -> None:
        self._event = event or threading.Event()

    def is_cancellation_requested(self) -> bool:
        """Indica si se ha solicitado la cancelación."""
        return self._event.is_set()

    def wait_or_cancelled(self, timeout_seconds: float) -> bool:
        """Espera de forma no bloqueante hasta el timeout o hasta recibir cancelación.

        Retorna True si la cancelación fue activada durante la espera, False si transcurrió el tiempo normal.
        """
        if timeout_seconds <= 0:
            return self.is_cancellation_requested()
        return self._event.wait(timeout=timeout_seconds)


class IEmergencyStopController(Protocol):
    """Protocolo abstracto para el controlador de Parada de Emergencia."""

    def trigger_stop(self, reason: str = "Parada de emergencia activada.", source: str = "user") -> None:
        """Activa de inmediato la Parada de Emergencia."""
        ...

    def reset(self, reason: str = "manual_reset") -> None:
        """Restablece el estado de Parada de Emergencia a RUNNING."""
        ...

    def is_stopped(self) -> bool:
        """Indica si el subsistema está en estado detenido."""
        ...

    def check_cancellation(self, phase: str = "execution") -> None:
        """Verifica la cancelación y lanza EmergencyStopTriggeredError si el sistema está detenido."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Obtiene el resumen de estado del controlador."""
        ...


class EmergencyStopManager(IEmergencyStopController):
    """Gestor global singleton thread-safe de Parada de Emergencia / Fail-Safe."""

    _instance: EmergencyStopManager | None = None
    _singleton_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._state: EmergencyStopState = EmergencyStopState.RUNNING
        self._state_lock: threading.RLock = threading.RLock()
        self._cancellation_event: threading.Event = threading.Event()
        self._reason: str | None = None
        self._source: str | None = None
        self._activation_timestamp: datetime | None = None
        self._activation_count: int = 0
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    @classmethod
    def get_instance(cls) -> EmergencyStopManager:
        """Obtiene la instancia singleton thread-safe del Gestor de Parada de Emergencia."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def cancellation_token(self) -> CancellationToken:
        """Retorna un token de cancelación vinculado al evento interno."""
        return CancellationToken(event=self._cancellation_event)

    def trigger_stop(self, reason: str = "Parada de emergencia activada.", source: str = "user") -> None:
        """Activa de inmediato la Parada de Emergencia. Idempotente ante múltiples llamadas concurrentes."""
        with self._state_lock:
            if self._state in (EmergencyStopState.STOP_REQUESTED, EmergencyStopState.STOPPED):
                logger.info(f"[EMERGENCY STOP RE-TRIGGERED] Solicitud duplicada recibida ({reason}). Estado actual: {self._state}")
                return

            self._state = EmergencyStopState.STOP_REQUESTED
            self._cancellation_event.set()
            self._reason = reason
            self._source = source
            self._activation_timestamp = datetime.now(UTC)
            self._activation_count += 1
            self._state = EmergencyStopState.STOPPED

            logger.warning(f"[EMERGENCY STOP ACTIVATED] {reason} (Fuente: {source})")

            audit_meta = {
                "reason": reason,
                "source": source,
                "activation_count": self._activation_count,
                "state": str(self._state),
            }

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EMERGENCY_STOP_ACTIVATED,
                    request_id=f"estop-{self._activation_count}",
                    tool_name="system.emergency_stop",
                    operation="trigger_stop",
                    duration_ms=0.0,
                    reason=f"Parada de emergencia activada por {source}: {reason}",
                    metadata=audit_meta,
                )
            )

            self.event_bus.publish("desktop:emergency_stop_activated", audit_meta)

            # Etapa 17.0 — emit SecurityEvent CRITICAL + update metric
            try:
                from core.observability.security_event_emitter import get_security_event_emitter
                from core.observability.security_event_models import SecurityEventType, SecuritySeverity
                get_security_event_emitter().emit_violation(
                    event_type=SecurityEventType.EMERGENCY_STOP_ACTIVATED,
                    severity=SecuritySeverity.CRITICAL,
                    component="emergency_stop",
                    description=f"Emergency Stop activated by {source}: {reason[:200]}",
                    blocked=True,
                    tool_name="system.emergency_stop",
                    operation="trigger_stop",
                    metadata={"source": source, "activation_count": self._activation_count},
                )
            except ImportError:
                pass
            try:
                from core.observability.metric_collector import get_metric_collector
                get_metric_collector().record_emergency_stop()
            except ImportError:
                pass

    def reset(self, reason: str = "manual_reset") -> None:
        """Restablece el estado de Parada de Emergencia a RUNNING permitiendo reanudar operaciones de forma segura."""
        with self._state_lock:
            self._state = EmergencyStopState.RUNNING
            self._cancellation_event.clear()
            self._reason = None
            self._source = None
            logger.info(f"[EMERGENCY STOP RESET] El sistema ha restablecido la operación normal ({reason}).")

            audit_meta = {"reason": reason, "state": str(self._state)}
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.EMERGENCY_STOP_DEACTIVATED,
                    request_id="estop-reset",
                    tool_name="system.emergency_stop",
                    operation="reset",
                    duration_ms=0.0,
                    reason=f"Parada de emergencia restablecida: {reason}",
                    metadata=audit_meta,
                )
            )

            self.event_bus.publish("desktop:emergency_stop_deactivated", audit_meta)

            # Etapa 17.0 — emit SecurityEvent + update metric gauge
            try:
                from core.observability.security_event_emitter import get_security_event_emitter
                from core.observability.security_event_models import SecurityEventType, SecuritySeverity
                get_security_event_emitter().emit_violation(
                    event_type=SecurityEventType.EMERGENCY_STOP_RESET,
                    severity=SecuritySeverity.HIGH,
                    component="emergency_stop",
                    description=f"Emergency Stop reset: {reason[:200]}",
                    blocked=False,
                    tool_name="system.emergency_stop",
                    operation="reset",
                )
            except ImportError:
                pass
            try:
                from core.observability.metric_collector import get_metric_collector
                get_metric_collector().record_emergency_stop_reset()
            except ImportError:
                pass

    def is_stopped(self) -> bool:
        """Consulta de forma thread-safe si la Parada de Emergencia está activa."""
        with self._state_lock:
            return self._state in (EmergencyStopState.STOP_REQUESTED, EmergencyStopState.STOPPED, EmergencyStopState.FAULTED)

    # Alias de retrocompatibilidad
    def is_active(self) -> bool:
        return self.is_stopped()

    def activate(self, reason: str = "Parada de Emergencia activada por el usuario o sistema.") -> None:
        self.trigger_stop(reason=reason, source="legacy_activate")

    def deactivate(self) -> None:
        self.reset(reason="legacy_deactivate")

    def check_cancellation(self, phase: str = "execution") -> None:
        """Verifica el estado de cancelación y lanza EmergencyStopTriggeredError si el sistema está detenido."""
        if self.is_stopped():
            sid_reason = self._reason or "Parada de emergencia activa"
            audit_meta = {"phase": phase, "reason": sid_reason}

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.ACTION_ABORTED_BY_EMERGENCY_STOP,
                    request_id=f"estop-abort-{phase}",
                    tool_name="system.emergency_stop",
                    operation="check_cancellation",
                    duration_ms=0.0,
                    reason=f"Acción interrumpida en fase '{phase}' por Parada de Emergencia.",
                    metadata=audit_meta,
                )
            )

            self.event_bus.publish("desktop:action_aborted", audit_meta)
            raise EmergencyStopTriggeredError(f"Acción abortada en fase '{phase}': {sid_reason}")

    def get_status(self) -> dict[str, Any]:
        """Obtiene un resumen thread-safe del estado actual de Parada de Emergencia."""
        with self._state_lock:
            return {
                "state": str(self._state),
                "is_stopped": self.is_stopped(),
                "reason": self._reason,
                "source": self._source,
                "activation_count": self._activation_count,
                "activation_timestamp": self._activation_timestamp.isoformat() if self._activation_timestamp else None,
            }


class FakeEmergencyStopController:
    """Controlador sintético de Parada de Emergencia para pruebas unitarias deterministas."""

    def __init__(self) -> None:
        self._stopped: bool = False
        self._reason: str | None = None
        self._phase_stopped: str | None = None

    def trigger_stop(self, reason: str = "Fake stop", source: str = "test") -> None:
        self._stopped = True
        self._reason = reason

    def reset(self, reason: str = "test_reset") -> None:
        self._stopped = False
        self._reason = None
        self._phase_stopped = None

    def is_stopped(self) -> bool:
        return self._stopped

    def check_cancellation(self, phase: str = "execution") -> None:
        if self._stopped or (self._phase_stopped and self._phase_stopped == phase):
            raise EmergencyStopTriggeredError(f"Acción de prueba abortada en fase '{phase}': {self._reason or 'Fake stop'}")

    def set_phase_stop(self, phase: str) -> None:
        """Simula la activación de parada de emergencia en una fase específica de la acción."""
        self._phase_stopped = phase

    def get_status(self) -> dict[str, Any]:
        return {"state": "STOPPED" if self._stopped else "RUNNING", "is_stopped": self._stopped, "reason": self._reason}


def get_emergency_stop_manager() -> EmergencyStopManager:
    """Función de conveniencia para acceder al singleton de EmergencyStopManager."""
    return EmergencyStopManager.get_instance()
