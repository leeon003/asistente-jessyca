"""HealthMonitor — Monitor Central de Salud y Diagnóstico Local (Etapa 17.2).

Proporciona:
  - Ejecución de sondeos de componentes (Browser, OCR, Micrófono, Ollama, etc.).
  - Detección de tasa excesiva de errores (excessive error rate).
  - Detección de fallos repetidos en acciones (repeated action failure).
  - Verificación de agotamiento de recursos (resource exhaustion).
  - Interrupción temprana con mensajes informativos claros ("Browser control unavailable")
    en lugar de bucles de reintento indefinidos.
  - Fail-safe absoluto: NO ejecuta autoreparación peligrosa.
"""

from __future__ import annotations

import collections
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.diagnostics.models import (
    ComponentCategory,
    HealthCheck,
    HealthReport,
    HealthStatus,
)
from core.diagnostics.probes import (
    probe_browser_availability,
    probe_microphone_availability,
    probe_ocr_availability,
    probe_ollama_availability,
    probe_plugin_system_availability,
    probe_scheduler_availability,
    probe_service_boundary_availability,
    probe_vector_store_availability,
)
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.diagnostics.monitor")


class ComponentUnavailableError(MCPError):
    """Error emitido cuando una herramienta/capacidad no puede ejecutarse porque el componente está no disponible."""

    pass


class HealthMonitor:
    """Monitor singleton y orquestador de chequeos de salud de JESSYCA 3.0."""

    _instance: HealthMonitor | None = None
    _singleton_lock: threading.Lock = threading.Lock()

    # Umbrales por defecto
    MAX_CONSECUTIVE_ACTION_FAILURES: int = 3
    EXCESSIVE_ERROR_RATE_THRESHOLD: float = 0.30  # 30% de fallos en ventana móvil
    EVENT_WINDOW_SIZE: int = 50

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._custom_probes: dict[str, Callable[[], HealthCheck]] = {}
        self._last_report: HealthReport | None = None
        self._last_checked_at: datetime | None = None

        # Seguimiento de fallos repetidos por acción/tool
        self._consecutive_failures: dict[str, int] = collections.defaultdict(int)

        # Ventana móvil de eventos (True=éxito, False=fallo)
        self._event_window: collections.deque[bool] = collections.deque(maxlen=self.EVENT_WINDOW_SIZE)

        # Registrar sondeos estándar por defecto
        self._register_default_probes()

    @classmethod
    def get_instance(cls) -> HealthMonitor:
        """Obtiene la instancia singleton thread-safe del HealthMonitor."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _register_default_probes(self) -> None:
        """Registra los sondeos predeterminados del sistema."""
        self.register_probe("browser", probe_browser_availability)
        self.register_probe("ocr", probe_ocr_availability)
        self.register_probe("microphone", probe_microphone_availability)
        self.register_probe("ollama", probe_ollama_availability)
        self.register_probe("vector_store", probe_vector_store_availability)
        self.register_probe("scheduler", probe_scheduler_availability)
        self.register_probe("plugin", probe_plugin_system_availability)
        self.register_probe("service", probe_service_boundary_availability)

    def register_probe(self, name: str, probe_fn: Callable[[], HealthCheck]) -> None:
        """Registra un sondeo personalizado para un componente."""
        with self._lock:
            self._custom_probes[name.lower()] = probe_fn

    def record_action_result(self, action_name: str, success: bool) -> None:
        """Registra el resultado de una acción para detectar fallos repetidos y tasa de error."""
        with self._lock:
            key = action_name.strip().lower()
            if success:
                self._consecutive_failures[key] = 0
            else:
                self._consecutive_failures[key] += 1
                failures = self._consecutive_failures[key]
                if failures >= self.MAX_CONSECUTIVE_ACTION_FAILURES:
                    logger.warning(
                        f"[HEALTH WARNING] Acción '{action_name}' ha fallado {failures} veces consecutivas. "
                        "Deteniendo reintentos automáticos."
                    )

            self._event_window.append(success)

    def get_error_rate(self) -> float:
        """Calcula la tasa de error en la ventana móvil actual."""
        with self._lock:
            if not self._event_window:
                return 0.0
            failures = sum(1 for success in self._event_window if not success)
            return failures / len(self._event_window)

    def run_all_checks(self) -> HealthReport:
        """Ejecuta todos los chequeos de diagnóstico y genera un HealthReport integral."""
        with self._lock:
            probes = dict(self._custom_probes)

        checks: dict[str, HealthCheck] = {}
        unavailable_components: list[str] = []
        user_friendly_messages: list[str] = []

        # 1. Ejecutar sondeos de componentes
        for name, probe_fn in probes.items():
            try:
                check_result = probe_fn()
            except Exception as exc:
                check_result = HealthCheck(
                    name=name,
                    component=name,
                    status=HealthStatus.FAILED,
                    message=f"{name.capitalize()} diagnostic check failed: {exc}",
                )
            checks[name] = check_result

            if not check_result.is_available:
                unavailable_components.append(name)
                user_friendly_messages.append(check_result.message)

        # 2. Diagnóstico de tasa excesiva de errores (Excessive Error Rate)
        error_rate = self.get_error_rate()
        if error_rate >= self.EXCESSIVE_ERROR_RATE_THRESHOLD and len(self._event_window) >= 5:
            checks["error_rate"] = HealthCheck(
                name="error_rate",
                component="system",
                category=ComponentCategory.SYSTEM,
                status=HealthStatus.DEGRADED,
                message=f"Excessive error rate detected ({round(error_rate * 100, 1)}% in last {len(self._event_window)} operations)",
                details={"error_rate": error_rate, "sample_size": len(self._event_window)},
            )
            user_friendly_messages.append(f"Excessive error rate ({round(error_rate * 100, 1)}%)")
        else:
            checks["error_rate"] = HealthCheck(
                name="error_rate",
                component="system",
                category=ComponentCategory.SYSTEM,
                status=HealthStatus.HEALTHY,
                message="Error rate within acceptable bounds",
                details={"error_rate": error_rate},
            )

        # 3. Diagnóstico de fallos repetidos (Repeated Action Failure)
        repeated_failures: dict[str, int] = {}
        with self._lock:
            for act, count in self._consecutive_failures.items():
                if count >= self.MAX_CONSECUTIVE_ACTION_FAILURES:
                    repeated_failures[act] = count

        if repeated_failures:
            checks["repeated_failures"] = HealthCheck(
                name="repeated_failures",
                component="system",
                category=ComponentCategory.SYSTEM,
                status=HealthStatus.DEGRADED,
                message=f"Repeated action failures on: {', '.join(repeated_failures.keys())}",
                details={"failing_actions": repeated_failures},
            )
            for act, cnt in repeated_failures.items():
                user_friendly_messages.append(f"Action '{act}' failing repeatedly ({cnt} consecutive errors)")

        # 4. Determinar estado general (Overall Status)
        failed_count = sum(1 for c in checks.values() if c.status == HealthStatus.FAILED)
        degraded_count = sum(1 for c in checks.values() if c.status == HealthStatus.DEGRADED)

        if failed_count > 0:
            overall = HealthStatus.FAILED
        elif degraded_count > 0:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        report = HealthReport(
            overall_status=overall,
            checks=checks,
            timestamp=datetime.now(UTC),
            unavailable_components=unavailable_components,
            user_friendly_messages=user_friendly_messages,
            error_rate=error_rate,
            repeated_failures_count=dict(repeated_failures),
        )

        with self._lock:
            self._last_report = report
            self._last_checked_at = report.timestamp

        return report

    def is_component_available(self, component_name: str) -> bool:
        """Verifica si un componente está disponible sin re-ejecutar todos los sondeos si hay un reporte reciente."""
        with self._lock:
            report = self._last_report

        if report is not None:
            return report.is_component_available(component_name)

        # Si no hay reporte previo, evaluar
        return self.run_all_checks().is_component_available(component_name)

    def assert_available(self, component_name: str) -> None:
        """Verifica que el componente esté disponible. Si no lo está, lanza ComponentUnavailableError

        con el mensaje informativo exacto para evitar bucles de ejecución indefinidos.
        """
        report = self.run_all_checks()
        if not report.is_component_available(component_name):
            notice = report.get_user_notice(component_name) or f"{component_name.capitalize()} is unavailable"
            raise ComponentUnavailableError(f"[SELF-DIAGNOSTICS] {notice}")

    def reset_failures(self) -> None:
        """Restablece el contador de fallos repetidos y la ventana de eventos (para tests o recuperación)."""
        with self._lock:
            self._consecutive_failures.clear()
            self._event_window.clear()
            self._last_report = None


# Función de conveniencia
def get_health_monitor() -> HealthMonitor:
    """Retorna el singleton global del HealthMonitor."""
    return HealthMonitor.get_instance()
