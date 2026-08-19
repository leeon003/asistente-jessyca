"""Subsistema de Diagnóstico Local y Salud de Componentes (Etapa 17.2).

Proporciona:
  - HealthStatus: Estados canónicos (HEALTHY, DEGRADED, FAILED, DISABLED).
  - HealthCheck: Resultado inmutable de un chequeo de componente.
  - HealthReport: Informe integral del estado del sistema.
  - HealthMonitor: Monitor singleton y orquestador de diagnósticos.
  - ComponentUnavailableError: Excepción para interrupción temprana sin reintentos infinitos.
  - Probes de subsistemas (Browser, OCR, Micrófono, Ollama, VectorStore, Scheduler, etc.).
"""

from core.diagnostics.models import (
    ComponentCategory,
    HealthCheck,
    HealthReport,
    HealthStatus,
)
from core.diagnostics.monitor import (
    ComponentUnavailableError,
    HealthMonitor,
    get_health_monitor,
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

__all__ = [
    "HealthStatus",
    "ComponentCategory",
    "HealthCheck",
    "HealthReport",
    "HealthMonitor",
    "get_health_monitor",
    "ComponentUnavailableError",
    "probe_browser_availability",
    "probe_ocr_availability",
    "probe_microphone_availability",
    "probe_ollama_availability",
    "probe_vector_store_availability",
    "probe_scheduler_availability",
    "probe_plugin_system_availability",
    "probe_service_boundary_availability",
]
