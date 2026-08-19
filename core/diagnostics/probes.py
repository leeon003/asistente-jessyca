"""Sondeos y Verificadores de Salud para Subetapa 17.2 (Probes).

Implementa los sondeos deterministas y seguros para:
  - Windows Services
  - Browser Control (Playwright / Chrome)
  - OCR Engine (Tesseract / Windows OCR)
  - Microphone Input (Audio Recording)
  - Ollama Local Inference (LLM Endpoint)
  - Local Vector Store (Semantic Memory)
  - Task Scheduler (Background execution)
  - Plugin Sandbox (Extension framework)
  - Resource Exhaustion (Memory / CPU / Disk)
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any

from core.diagnostics.models import ComponentCategory, HealthCheck, HealthStatus
from core.logger import get_logger

logger = get_logger("jessyca.diagnostics.probes")


def probe_browser_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el control del navegador está disponible."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Browser control operational" if status == HealthStatus.HEALTHY else "Browser control unavailable"
            return HealthCheck(
                name="browser_control",
                component="browser",
                category=ComponentCategory.BROWSER,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="browser_control",
                component="browser",
                category=ComponentCategory.BROWSER,
                status=HealthStatus.FAILED,
                message="Browser control unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    # Detección determinista por defecto: presencia de binarios o librerías
    playwright_found = shutil.which("playwright") is not None
    chrome_found = (
        shutil.which("chrome") is not None
        or shutil.which("msedge") is not None
        or os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        or os.path.exists(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    )

    try:
        import playwright  # noqa: F401
        has_playwright_module = True
    except ImportError:
        has_playwright_module = False

    duration = (time.perf_counter() - start) * 1000

    if has_playwright_module and (chrome_found or playwright_found):
        return HealthCheck(
            name="browser_control",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.HEALTHY,
            message="Browser control operational",
            details={"chrome_or_edge_found": chrome_found, "playwright_module": True},
            duration_ms=duration,
        )
    elif has_playwright_module:
        return HealthCheck(
            name="browser_control",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.DEGRADED,
            message="Browser control degraded: Playwright installed but browser binaries not found in default paths",
            details={"chrome_or_edge_found": False, "playwright_module": True},
            duration_ms=duration,
        )
    else:
        return HealthCheck(
            name="browser_control",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.FAILED,
            message="Browser control unavailable",
            details={"reason": "playwright module not installed"},
            duration_ms=duration,
            remedy_suggestion="Instalar playwright con pip install playwright",
        )


def probe_ocr_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el motor OCR está disponible."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "OCR engine operational" if status == HealthStatus.HEALTHY else "OCR unavailable"
            return HealthCheck(
                name="ocr_engine",
                component="ocr",
                category=ComponentCategory.OCR,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="ocr_engine",
                component="ocr",
                category=ComponentCategory.OCR,
                status=HealthStatus.FAILED,
                message="OCR unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    tesseract_cmd = shutil.which("tesseract")
    windows_default_path = os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe")

    try:
        import pytesseract  # noqa: F401
        has_pytesseract = True
    except ImportError:
        has_pytesseract = False

    duration = (time.perf_counter() - start) * 1000

    if has_pytesseract and (tesseract_cmd or windows_default_path):
        return HealthCheck(
            name="ocr_engine",
            component="ocr",
            category=ComponentCategory.OCR,
            status=HealthStatus.HEALTHY,
            message="OCR engine operational",
            details={"tesseract_path": tesseract_cmd or r"C:\Program Files\Tesseract-OCR\tesseract.exe"},
            duration_ms=duration,
        )
    elif has_pytesseract:
        return HealthCheck(
            name="ocr_engine",
            component="ocr",
            category=ComponentCategory.OCR,
            status=HealthStatus.DEGRADED,
            message="OCR unavailable: pytesseract is available but tesseract executable not found in PATH",
            details={"has_pytesseract": True, "tesseract_binary": False},
            duration_ms=duration,
            remedy_suggestion="Instalar Tesseract-OCR en el sistema operativo",
        )
    else:
        return HealthCheck(
            name="ocr_engine",
            component="ocr",
            category=ComponentCategory.OCR,
            status=HealthStatus.FAILED,
            message="OCR unavailable",
            details={"reason": "pytesseract not installed"},
            duration_ms=duration,
            remedy_suggestion="pip install pytesseract",
        )


def probe_microphone_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el dispositivo de captura de audio/micrófono está disponible."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Microphone input operational" if status == HealthStatus.HEALTHY else "Microphone unavailable"
            return HealthCheck(
                name="microphone_input",
                component="microphone",
                category=ComponentCategory.MICROPHONE,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="microphone_input",
                component="microphone",
                category=ComponentCategory.MICROPHONE,
                status=HealthStatus.FAILED,
                message="Microphone unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        import sounddevice as sd  # type: ignore[import-untyped]
        devices = sd.query_devices()
        input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
        has_mic = len(input_devices) > 0
        duration = (time.perf_counter() - start) * 1000

        if has_mic:
            return HealthCheck(
                name="microphone_input",
                component="microphone",
                category=ComponentCategory.MICROPHONE,
                status=HealthStatus.HEALTHY,
                message="Microphone input operational",
                details={"input_devices_count": len(input_devices)},
                duration_ms=duration,
            )
        else:
            return HealthCheck(
                name="microphone_input",
                component="microphone",
                category=ComponentCategory.MICROPHONE,
                status=HealthStatus.FAILED,
                message="Microphone unavailable: no audio input devices detected",
                duration_ms=duration,
            )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="microphone_input",
            component="microphone",
            category=ComponentCategory.MICROPHONE,
            status=HealthStatus.DEGRADED,
            message="Microphone unavailable",
            details={"reason": str(exc)},
            duration_ms=duration,
        )


def probe_ollama_availability(endpoint_url: str = "http://localhost:11434", custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el servidor local de inferencia Ollama está respondiendo."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Ollama inference operational" if status == HealthStatus.HEALTHY else "Ollama unavailable"
            return HealthCheck(
                name="ollama_inference",
                component="ollama",
                category=ComponentCategory.OLLAMA,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="ollama_inference",
                component="ollama",
                category=ComponentCategory.OLLAMA,
                status=HealthStatus.FAILED,
                message="Ollama unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        import urllib.request
        req = urllib.request.Request(f"{endpoint_url}/api/tags", headers={"User-Agent": "JessycaDiagnostics/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            code = response.getcode()
            duration = (time.perf_counter() - start) * 1000
            if code == 200:
                return HealthCheck(
                    name="ollama_inference",
                    component="ollama",
                    category=ComponentCategory.OLLAMA,
                    status=HealthStatus.HEALTHY,
                    message="Ollama inference operational",
                    details={"endpoint": endpoint_url, "http_status": 200},
                    duration_ms=duration,
                )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="ollama_inference",
            component="ollama",
            category=ComponentCategory.OLLAMA,
            status=HealthStatus.DEGRADED,
            message="Ollama unavailable",
            details={"endpoint": endpoint_url, "reason": str(exc)},
            duration_ms=duration,
            remedy_suggestion="Verificar que el servicio de Ollama esté ejecutándose localmente",
        )

    return HealthCheck(
        name="ollama_inference",
        component="ollama",
        category=ComponentCategory.OLLAMA,
        status=HealthStatus.FAILED,
        message="Ollama unavailable",
        duration_ms=(time.perf_counter() - start) * 1000,
    )


def probe_vector_store_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si la base de datos de memoria vectorial local está operativa."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Vector store operational" if status == HealthStatus.HEALTHY else "Vector store unavailable"
            return HealthCheck(
                name="vector_store",
                component="vector_store",
                category=ComponentCategory.VECTOR_STORE,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="vector_store",
                component="vector_store",
                category=ComponentCategory.VECTOR_STORE,
                status=HealthStatus.FAILED,
                message="Vector store unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        from core.local_vector_store import get_local_vector_store
        store = get_local_vector_store()
        count = store.count() if hasattr(store, "count") else 0
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="vector_store",
            component="vector_store",
            category=ComponentCategory.VECTOR_STORE,
            status=HealthStatus.HEALTHY,
            message="Vector store operational",
            details={"entries_count": count},
            duration_ms=duration,
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="vector_store",
            component="vector_store",
            category=ComponentCategory.VECTOR_STORE,
            status=HealthStatus.FAILED,
            message="Vector store unavailable",
            details={"error": str(exc)},
            duration_ms=duration,
        )


def probe_scheduler_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el planificador de tareas en background está operativo."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Task scheduler operational" if status == HealthStatus.HEALTHY else "Scheduler failure"
            return HealthCheck(
                name="task_scheduler",
                component="scheduler",
                category=ComponentCategory.SCHEDULER,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="task_scheduler",
                component="scheduler",
                category=ComponentCategory.SCHEDULER,
                status=HealthStatus.FAILED,
                message="Scheduler failure",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        from core.task_scheduler import get_task_scheduler
        scheduler = get_task_scheduler()
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="task_scheduler",
            component="scheduler",
            category=ComponentCategory.SCHEDULER,
            status=HealthStatus.HEALTHY,
            message="Task scheduler operational",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="task_scheduler",
            component="scheduler",
            category=ComponentCategory.SCHEDULER,
            status=HealthStatus.FAILED,
            message="Scheduler failure",
            details={"error": str(exc)},
            duration_ms=duration,
        )


def probe_plugin_system_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si el marco de extensiones y plugins está saludable."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "Plugin sandbox operational" if status == HealthStatus.HEALTHY else "Plugin failure"
            return HealthCheck(
                name="plugin_system",
                component="plugin",
                category=ComponentCategory.PLUGIN,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="plugin_system",
                component="plugin",
                category=ComponentCategory.PLUGIN,
                status=HealthStatus.FAILED,
                message="Plugin failure",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        from core.plugin_loader import PluginLoader
        loader = PluginLoader()
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="plugin_system",
            component="plugin",
            category=ComponentCategory.PLUGIN,
            status=HealthStatus.HEALTHY,
            message="Plugin sandbox operational",
            duration_ms=duration,
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="plugin_system",
            component="plugin",
            category=ComponentCategory.PLUGIN,
            status=HealthStatus.FAILED,
            message="Plugin failure",
            details={"error": str(exc)},
            duration_ms=duration,
        )


def probe_service_boundary_availability(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica si la frontera de servicios del sistema está operativa."""
    start = time.perf_counter()
    if custom_checker is not None:
        try:
            res = custom_checker()
            status = res if isinstance(res, HealthStatus) else (HealthStatus.HEALTHY if res else HealthStatus.FAILED)
            msg = "System service boundary operational" if status == HealthStatus.HEALTHY else "Service unavailable"
            return HealthCheck(
                name="service_boundary",
                component="service",
                category=ComponentCategory.SERVICE,
                status=status,
                message=msg,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return HealthCheck(
                name="service_boundary",
                component="service",
                category=ComponentCategory.SERVICE,
                status=HealthStatus.FAILED,
                message="Service unavailable",
                details={"error": str(exc)},
                duration_ms=(time.perf_counter() - start) * 1000,
            )

    try:
        from config.settings import AppSettings
        settings = AppSettings()
        duration = (time.perf_counter() - start) * 1000
        status = HealthStatus.HEALTHY if settings.SERVICE_WRITE_ENABLED else HealthStatus.DISABLED
        msg = "Service control enabled" if status == HealthStatus.HEALTHY else "Service control disabled by policy"
        return HealthCheck(
            name="service_boundary",
            component="service",
            category=ComponentCategory.SERVICE,
            status=status,
            message=msg,
            duration_ms=duration,
        )
    except Exception as exc:
        duration = (time.perf_counter() - start) * 1000
        return HealthCheck(
            name="service_boundary",
            component="service",
            category=ComponentCategory.SERVICE,
            status=HealthStatus.FAILED,
            message="Service unavailable",
            details={"error": str(exc)},
            duration_ms=duration,
        )
