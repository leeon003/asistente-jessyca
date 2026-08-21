"""Subsistema de Diagnóstico Local y Salud de Componentes (Fase 29).

Proporciona:
  - HealthStatus / ComponentStatus: Estados canónicos (HEALTHY, DEGRADED, UNAVAILABLE, ERROR).
  - HealthCheck: Resultado inmutable de un chequeo de componente.
  - HealthReport: Informe integral del estado del sistema.
  - HealthMonitor: Monitor singleton y orquestador de diagnósticos.
  - ComponentUnavailableError: Excepción para interrupción temprana.
  - Probes de los 14 componentes del sistema.
"""

from core.diagnostics.models import (
    ComponentCategory,
    ComponentStatus,
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
    probe_browser_health,
    probe_desktop_health,
    probe_gpu_health,
    probe_mcp_health,
    probe_memory_health,
    probe_microphone_availability,
    probe_model_manager_health,
    probe_models_health,
    probe_ocr_availability,
    probe_ollama_availability,
    probe_ollama_health,
    probe_plugin_system_availability,
    probe_plugins_health,
    probe_scheduler_availability,
    probe_scheduler_health,
    probe_security_health,
    probe_service_boundary_availability,
    probe_system_health,
    probe_vector_store_availability,
    probe_voice_health,
    probe_vram_health,
)

__all__ = [
    "HealthStatus",
    "ComponentStatus",
    "ComponentCategory",
    "HealthCheck",
    "HealthReport",
    "HealthMonitor",
    "get_health_monitor",
    "ComponentUnavailableError",
    "probe_system_health",
    "probe_gpu_health",
    "probe_vram_health",
    "probe_ollama_health",
    "probe_models_health",
    "probe_model_manager_health",
    "probe_memory_health",
    "probe_browser_health",
    "probe_desktop_health",
    "probe_voice_health",
    "probe_scheduler_health",
    "probe_mcp_health",
    "probe_security_health",
    "probe_plugins_health",
    # Retrocompatibles
    "probe_browser_availability",
    "probe_ocr_availability",
    "probe_microphone_availability",
    "probe_ollama_availability",
    "probe_vector_store_availability",
    "probe_scheduler_availability",
    "probe_plugin_system_availability",
    "probe_service_boundary_availability",
]
