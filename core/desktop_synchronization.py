"""Capa de sincronización explícita y basada en condiciones para automatización de escritorio (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Elimina la dependencia de sleeps estáticos arbitrarios (sleep(N) PROHIBIDO como mecanismo principal).
Toda sincronización de interfaz se realiza mediante polling de condiciones explícitas no bloqueantes con
CancellationToken, comprobación de Parada de Emergencia (EmergencyStopManager) e integración con el Fail-Safe.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.emergency_stop import CancellationToken, EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.ui_inspection_models import UIElementRequest, compute_ui_state_hash
from tools.desktop.ui_backend import (
    IUIInspectionBackend,
    WindowsUIAutomationBackend,
)

logger = get_logger("jessyca.core.desktop_synchronization")


class SynchronizationStatus(StrEnum):
    """Estados controlados del subsistema de sincronización UI."""

    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    ABORTED_BY_EMERGENCY_STOP = "ABORTED_BY_EMERGENCY_STOP"
    PROVIDER_ERROR = "PROVIDER_ERROR"


@dataclass(frozen=True)
class SynchronizationResult:
    """Resultado inmutable del proceso de sincronización por condición."""

    status: SynchronizationStatus
    success: bool
    elapsed_time_ms: float
    poll_count: int
    reason: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario estructurado para auditoría."""
        return {
            "status": str(self.status),
            "success": self.success,
            "elapsed_time_ms": round(self.elapsed_time_ms, 2),
            "poll_count": self.poll_count,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


class IClock(Protocol):
    """Protocolo abstracto de reloj para control de tiempo y temporizadores."""

    def time(self) -> float:
        """Obtiene la marca de tiempo actual en segundos."""
        ...

    def sleep(self, seconds: float) -> None:
        """Pausa la ejecución el número de segundos indicado."""
        ...


class RealClock(IClock):
    """Reloj de producción basado en las funciones del sistema operativo."""

    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock(IClock):
    """Reloj sintético determinista para pruebas unitarias rápidas sin retrasos reales del SO."""

    def __init__(self, start_time: float = 1000.0) -> None:
        self._current_time: float = start_time
        self.sleep_calls: list[float] = []

    def time(self) -> float:
        return self._current_time

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self._current_time += seconds

    def advance(self, seconds: float) -> None:
        """Avanza el tiempo sintético sin registrar sleep."""
        self._current_time += seconds


class DesktopSynchronizer:
    """Motor de sincronización explícita por condiciones para la interfaz gráfica."""

    def __init__(
        self,
        emergency_stop_manager: EmergencyStopManager | None = None,
        clock: IClock | None = None,
    ) -> None:
        self.emergency_stop = emergency_stop_manager or get_emergency_stop_manager()
        self.clock = clock or RealClock()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def wait_until(
        self,
        condition: Callable[[], bool],
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        cancellation_token: CancellationToken | None = None,
        sync_name: str = "custom_condition",
    ) -> SynchronizationResult:
        """Espera de forma no bloqueante hasta que la condición se cumpla o venza el timeout.

        Integra comprobación explícita de Parada de Emergencia y CancellationToken en cada ciclo de polling.
        NUNCA realiza sleeps estáticos no cancelables.
        """
        start_t = datetime.now(UTC)
        start_clock = self.clock.time()
        deadline = start_clock + max(0.001, timeout_seconds)
        poll_count = 0

        logger.debug(f"[SYNCHRONIZER] Iniciando wait_until '{sync_name}' (timeout={timeout_seconds}s, interval={poll_interval_seconds}s)")

        while self.clock.time() <= deadline:
            poll_count += 1

            # 1. Comprobación inmediata de Parada de Emergencia (Fail-Safe)
            if self.emergency_stop.is_stopped():
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                res = SynchronizationResult(
                    status=SynchronizationStatus.ABORTED_BY_EMERGENCY_STOP,
                    success=False,
                    elapsed_time_ms=proc_ms,
                    poll_count=poll_count,
                    reason=f"Sincronización '{sync_name}' abortada: Parada de Emergencia activa.",
                    timestamp=datetime.now(UTC),
                )
                self._log_audit(sync_name, res)
                return res

            # 2. Comprobación de Token de Cancelación
            if cancellation_token and cancellation_token.is_cancellation_requested():
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                res = SynchronizationResult(
                    status=SynchronizationStatus.CANCELLED,
                    success=False,
                    elapsed_time_ms=proc_ms,
                    poll_count=poll_count,
                    reason=f"Sincronización '{sync_name}' cancelada por el token de cancelación.",
                    timestamp=datetime.now(UTC),
                )
                self._log_audit(sync_name, res)
                return res

            # 3. Evaluación de la condición verificable
            try:
                if condition():
                    proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                    res = SynchronizationResult(
                        status=SynchronizationStatus.SUCCESS,
                        success=True,
                        elapsed_time_ms=proc_ms,
                        poll_count=poll_count,
                        reason=f"Sincronización '{sync_name}' completada exitosamente.",
                        timestamp=datetime.now(UTC),
                    )
                    self._log_audit(sync_name, res)
                    return res
            except Exception as e:
                proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                logger.warning(f"[SYNCHRONIZER PROVIDER ERROR] Excepción durante la evaluación de la condición '{sync_name}': {e}")
                res = SynchronizationResult(
                    status=SynchronizationStatus.PROVIDER_ERROR,
                    success=False,
                    elapsed_time_ms=proc_ms,
                    poll_count=poll_count,
                    reason=f"Error en el proveedor de la condición '{sync_name}': {e}",
                    timestamp=datetime.now(UTC),
                )
                self._log_audit(sync_name, res)
                return res

            # 4. Espera del intervalo de polling usando el reloj inyectado
            if cancellation_token:
                if cancellation_token.wait_or_cancelled(poll_interval_seconds):
                    proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
                    res = SynchronizationResult(
                        status=SynchronizationStatus.CANCELLED,
                        success=False,
                        elapsed_time_ms=proc_ms,
                        poll_count=poll_count,
                        reason=f"Sincronización '{sync_name}' cancelada durante el intervalo de polling.",
                        timestamp=datetime.now(UTC),
                    )
                    self._log_audit(sync_name, res)
                    return res
                else:
                    self.clock.sleep(0.0)  # Avance mínimo en FakeClock si aplica
            else:
                self.clock.sleep(poll_interval_seconds)

        # 5. Expiración del tiempo límite (TIMEOUT)
        proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
        res = SynchronizationResult(
            status=SynchronizationStatus.TIMEOUT,
            success=False,
            elapsed_time_ms=proc_ms,
            poll_count=poll_count,
            reason=f"Tiempo límite de sincronización '{sync_name}' excede el timeout ({timeout_seconds}s).",
            timestamp=datetime.now(UTC),
        )
        self._log_audit(sync_name, res)
        return res

    def wait_for_window(
        self,
        window_title: str,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        ui_backend: IUIInspectionBackend | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> SynchronizationResult:
        """Espera de forma explícita a que una ventana con el título indicado aparezca y sea visible."""
        backend = ui_backend or WindowsUIAutomationBackend()

        def window_condition() -> bool:
            req = UIElementRequest(window_title=window_title, max_depth=2, max_elements=10)
            res = backend.inspect_ui(req)
            return any(window_title.lower() in e.name.lower() for e in res.elements_flat)

        return self.wait_until(
            condition=window_condition,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            cancellation_token=cancellation_token,
            sync_name=f"wait_for_window({window_title})",
        )

    def wait_for_element(
        self,
        window_title: str | None,
        control_type: str | None,
        element_name: str | None,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        ui_backend: IUIInspectionBackend | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> SynchronizationResult:
        """Espera de forma explícita a que un elemento UI específico esté presente en la interfaz."""
        backend = ui_backend or WindowsUIAutomationBackend()

        def element_condition() -> bool:
            req = UIElementRequest(window_title=window_title, control_type=control_type, max_depth=10, max_elements=50)
            res = backend.inspect_ui(req)
            for e in res.elements_flat:
                if element_name and element_name.lower() not in e.name.lower():
                    continue
                if control_type and control_type.lower() not in e.control_type.value.lower():
                    continue
                return True
            return False

        name_repr = element_name or control_type or window_title or "element"
        return self.wait_until(
            condition=element_condition,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            cancellation_token=cancellation_token,
            sync_name=f"wait_for_element({name_repr})",
        )

    def wait_for_state(
        self,
        expected_state_hash: str,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.1,
        ui_backend: IUIInspectionBackend | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> SynchronizationResult:
        """Espera de forma explícita a que el fingerprint criptográfico de estado visual coincida con el esperado."""
        backend = ui_backend or WindowsUIAutomationBackend()

        def state_condition() -> bool:
            active_win = backend.get_active_window()
            current_hash = compute_ui_state_hash(active_win.hwnd, active_win.title, active_win.bounds, "Window")
            return current_hash == expected_state_hash

        return self.wait_until(
            condition=state_condition,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            cancellation_token=cancellation_token,
            sync_name=f"wait_for_state({expected_state_hash[:8]})",
        )

    def _log_audit(self, sync_name: str, res: SynchronizationResult) -> None:
        """Registra auditoría y publica eventos en EventBus con metadatos exclusivamente."""
        audit_meta = res.to_dict()
        event_type = AuditEventType.DESKTOP_ACTION_SUCCEEDED if res.success else AuditEventType.DESKTOP_ACTION_FAILED

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=event_type,
                request_id=f"sync-{sync_name}",
                tool_name="windows.desktop",
                operation="synchronize_ui",
                duration_ms=res.elapsed_time_ms,
                reason=res.reason,
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:synchronization_completed", audit_meta)
