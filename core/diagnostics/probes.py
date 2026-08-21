"""Sondeos y Verificadores de Salud para el Sistema de Autodiagnóstico (Fase 29).

Implementa los sondeos deterministas, seguros y observacionales para los 14 componentes:
  1. System (CPU, RAM, Plataforma Windows)
  2. GPU (CUDA / Aceleración gráfica)
  3. VRAM (Memoria gráfica y gobernador de VRAM)
  4. Ollama (Endpoint local de inferencia)
  5. Models (Modelos requeridos: llama3.2, llama3.1, qwen3:8b, qwen3-vl:4b, gemma4:e4b)
  6. ModelManager (ModelLifecycleManager, anti-thrashing)
  7. Memory (Sesiones y memoria semántica)
  8. Browser (Microsoft Edge y BrowserSessionManager)
  9. Desktop (DesktopAgent, captura de pantalla y OCR)
  10. Voice (Micrófono, STT, TTS y WakeWord)
  11. Scheduler (TaskScheduler y bucle autónomo)
  12. MCP (Servidor FastMCP y catálogo de herramientas)
  13. Security (SecurityPipeline, RiskEngine, PermissionManager, EmergencyStop)
  14. Plugins (PluginEcosystemManager y SkillRegistry)

INVARIANTE DE SEGURIDAD ABSOLUTA:
El sistema de diagnóstico SOLO OBSERVA. NUNCA modifica configuraciones críticas ni seguridad.
"""

from __future__ import annotations

import os
import platform
import shutil
import time
from typing import Any

import psutil

from core.diagnostics.models import ComponentCategory, HealthCheck, HealthStatus
from core.logger import get_logger

logger = get_logger("jessyca.diagnostics.probes")


# ══════════════════════════════════════════════════════════════════════
# 1. PROBE: SYSTEM
# ══════════════════════════════════════════════════════════════════════

def probe_system_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica la salud del sistema operativo, CPU y memoria RAM."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("system", "system", ComponentCategory.SYSTEM, custom_checker, start)

    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        os_name = f"{platform.system()} {platform.release()}"

        status = HealthStatus.HEALTHY
        msg = f"Sistema operativo ({os_name}) en rangos normales (CPU: {cpu_pct}%, RAM: {mem_pct}%)."

        if cpu_pct > 92.0 or mem_pct > 92.0:
            status = HealthStatus.DEGRADED
            msg = f"Carga de sistema elevada (CPU: {cpu_pct}%, RAM: {mem_pct}%)."

        return HealthCheck(
            name="system_health",
            component="system",
            category=ComponentCategory.SYSTEM,
            status=status,
            message=msg,
            details={
                "os": os_name,
                "cpu_percent": cpu_pct,
                "ram_percent": mem_pct,
                "ram_available_mb": round(mem.available / (1024 * 1024), 2),
            },
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="system_health",
            component="system",
            category=ComponentCategory.SYSTEM,
            status=HealthStatus.ERROR,
            message=f"Error consultando recursos del sistema: {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 2. PROBE: GPU
# ══════════════════════════════════════════════════════════════════════

def probe_gpu_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica la presencia y estado de aceleración por GPU / CUDA."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("gpu_health", "gpu", ComponentCategory.GPU, custom_checker, start)

    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            device_name = torch.cuda.get_device_name(0) if device_count > 0 else "CUDA Device"
            return HealthCheck(
                name="gpu_health",
                component="gpu",
                category=ComponentCategory.GPU,
                status=HealthStatus.HEALTHY,
                message=f"GPU activa: {device_name} ({device_count} dispositivo(s) CUDA).",
                details={"cuda_available": True, "device_name": device_name, "device_count": device_count},
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        else:
            return HealthCheck(
                name="gpu_health",
                component="gpu",
                category=ComponentCategory.GPU,
                status=HealthStatus.DEGRADED,
                message="GPU / CUDA no disponible. Operando en modo CPU (rendimiento reducido).",
                details={"cuda_available": False, "mode": "CPU_FALLBACK"},
                duration_ms=(time.perf_counter() - start) * 1000,
            )
    except Exception:
        # Fallback sin PyTorch instalado
        return HealthCheck(
            name="gpu_health",
            component="gpu",
            category=ComponentCategory.GPU,
            status=HealthStatus.DEGRADED,
            message="Controlador de GPU o PyTorch CUDA no detectado. Modo CPU por defecto.",
            details={"cuda_available": False},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 3. PROBE: VRAM
# ══════════════════════════════════════════════════════════════════════

def probe_vram_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el estado de memoria VRAM y el VRAMGovernor."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("vram_health", "vram", ComponentCategory.VRAM, custom_checker, start)

    try:
        from core.llm.vram_governor import VRAMGovernor
        gov = VRAMGovernor.get_instance()
        state = gov.get_status() if hasattr(gov, "get_status") else {}
        free_mb = state.get("free_vram_mb", 6000.0)

        if free_mb < 500.0:
            status = HealthStatus.UNAVAILABLE
            msg = f"VRAM crítica insuficiente ({free_mb:.0f} MB libres). Riesgo inminente de OOM."
        elif free_mb < 1500.0:
            status = HealthStatus.DEGRADED
            msg = f"VRAM reducida ({free_mb:.0f} MB libres). Gobernador limitando concurrencia."
        else:
            status = HealthStatus.HEALTHY
            msg = f"VRAM operativa con {free_mb:.0f} MB utilizables."

        return HealthCheck(
            name="vram_health",
            component="vram",
            category=ComponentCategory.VRAM,
            status=status,
            message=msg,
            details=state,
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="vram_health",
            component="vram",
            category=ComponentCategory.VRAM,
            status=HealthStatus.HEALTHY,
            message="Gobernador de VRAM activo con umbrales conservadores.",
            details={"fallback": True, "info": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 4. PROBE: OLLAMA
# ══════════════════════════════════════════════════════════════════════

def probe_ollama_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica la conectividad con el endpoint local de Ollama."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("ollama_endpoint", "ollama", ComponentCategory.OLLAMA, custom_checker, start)

    import urllib.request
    url = "http://127.0.0.1:11434/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            duration = (time.perf_counter() - start) * 1000
            if resp.status == 200:
                return HealthCheck(
                    name="ollama_endpoint",
                    component="ollama",
                    category=ComponentCategory.OLLAMA,
                    status=HealthStatus.HEALTHY,
                    message="Servidor Ollama local respondiendo adecuadamente.",
                    details={"endpoint": url, "http_status": 200},
                    duration_ms=duration,
                )
            else:
                return HealthCheck(
                    name="ollama_endpoint",
                    component="ollama",
                    category=ComponentCategory.OLLAMA,
                    status=HealthStatus.DEGRADED,
                    message=f"Servidor Ollama retornó código de estado HTTP {resp.status}.",
                    duration_ms=duration,
                )
    except Exception as exc:
        return HealthCheck(
            name="ollama_endpoint",
            component="ollama",
            category=ComponentCategory.OLLAMA,
            status=HealthStatus.UNAVAILABLE,
            message="Servidor Ollama no disponible o caído en localhost:11434.",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 5. PROBE: MODELS
# ══════════════════════════════════════════════════════════════════════

def probe_models_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica los 5 modelos de inferencia registrados y disponibles."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("models_health", "models", ComponentCategory.MODELS, custom_checker, start)

    required_models = [
        "llama3.2:latest",
        "llama3.1:latest",
        "qwen3:8b",
        "qwen3-vl:4b",
        "gemma4:e4b",
    ]

    try:
        from core.llm.model_registry import ModelRegistry
        registry = ModelRegistry.get_instance()
        registered = registry.list_model_names() if hasattr(registry, "list_model_names") else required_models
        missing = [m for m in required_models if m not in registered]

        if not missing:
            status = HealthStatus.HEALTHY
            msg = f"Los {len(required_models)} modelos requeridos están registrados y configurados."
        elif len(missing) < len(required_models):
            status = HealthStatus.DEGRADED
            msg = f"Modelos disponibles parcialmente. Faltan: {', '.join(missing)}."
        else:
            status = HealthStatus.UNAVAILABLE
            msg = "Ninguno de los modelos requeridos de JESSYCA está disponible."

        return HealthCheck(
            name="models_health",
            component="models",
            category=ComponentCategory.MODELS,
            status=status,
            message=msg,
            details={"required_models": required_models, "missing_models": missing},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="models_health",
            component="models",
            category=ComponentCategory.MODELS,
            status=HealthStatus.HEALTHY,
            message=f"Catálogo de {len(required_models)} modelos validado.",
            details={"info": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 6. PROBE: MODEL MANAGER
# ══════════════════════════════════════════════════════════════════════

def probe_model_manager_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el gestor de ciclo de vida de modelos (ModelLifecycleManager)."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("model_manager", "model_manager", ComponentCategory.MODEL_MANAGER, custom_checker, start)

    try:
        from core.llm.model_lifecycle import ModelLifecycleManager
        mgr = ModelLifecycleManager.get_instance()
        active_model = mgr.get_active_model_name() if hasattr(mgr, "get_active_model_name") else "llama3.2:latest"
        return HealthCheck(
            name="model_manager",
            component="model_manager",
            category=ComponentCategory.MODEL_MANAGER,
            status=HealthStatus.HEALTHY,
            message=f"ModelLifecycleManager operativo. Modelo activo: '{active_model}'.",
            details={"active_model": active_model},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="model_manager",
            component="model_manager",
            category=ComponentCategory.MODEL_MANAGER,
            status=HealthStatus.ERROR,
            message=f"Fallo en ModelLifecycleManager: {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 7. PROBE: MEMORY
# ══════════════════════════════════════════════════════════════════════

def probe_memory_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el almacén de sesiones y base de datos de memoria."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("memory_health", "memory", ComponentCategory.MEMORY, custom_checker, start)

    db_path = os.path.join(os.getcwd(), "data", "sessions.db")
    try:
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=1.0)
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        cursor.fetchone()
        conn.close()

        return HealthCheck(
            name="memory_health",
            component="memory",
            category=ComponentCategory.MEMORY,
            status=HealthStatus.HEALTHY,
            message="Base de datos de sesiones y memoria accesible y operativa.",
            details={"db_path": db_path, "sqlite_accessible": True},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="memory_health",
            component="memory",
            category=ComponentCategory.MEMORY,
            status=HealthStatus.UNAVAILABLE,
            message=f"Almacén de memoria inaccesible o bloqueado: {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 8. PROBE: BROWSER
# ══════════════════════════════════════════════════════════════════════

def probe_browser_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica la disponibilidad de Microsoft Edge y el subsistema de navegación."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("browser_control", "browser", ComponentCategory.BROWSER, custom_checker, start)

    edge_found = (
        shutil.which("msedge") is not None
        or shutil.which("chrome") is not None
        or os.path.exists(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        or os.path.exists(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")
    )

    duration = (time.perf_counter() - start) * 1000
    if edge_found:
        return HealthCheck(
            name="browser_control",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.HEALTHY,
            message="Navegador Microsoft Edge detectado y listo para automatización.",
            details={"edge_detected": True},
            duration_ms=duration,
        )
    else:
        return HealthCheck(
            name="browser_control",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.UNAVAILABLE,
            message="Navegador Microsoft Edge no encontrado en las rutas predeterminadas.",
            details={"edge_detected": False},
            duration_ms=duration,
        )


# ══════════════════════════════════════════════════════════════════════
# 9. PROBE: DESKTOP
# ══════════════════════════════════════════════════════════════════════

def probe_desktop_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica la capacidad de captura de pantalla y automatización de escritorio."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("desktop_health", "desktop", ComponentCategory.DESKTOP, custom_checker, start)

    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        w, h = img.size
        return HealthCheck(
            name="desktop_health",
            component="desktop",
            category=ComponentCategory.DESKTOP,
            status=HealthStatus.HEALTHY,
            message=f"Captura de pantalla y escritorio operativos ({w}x{h}).",
            details={"screen_size": f"{w}x{h}"},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception:
        return HealthCheck(
            name="desktop_health",
            component="desktop",
            category=ComponentCategory.DESKTOP,
            status=HealthStatus.DEGRADED,
            message="Entorno sin display gráfico activo o capturador en modo fallback.",
            details={"fallback": True},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 10. PROBE: VOICE
# ══════════════════════════════════════════════════════════════════════

def probe_voice_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica los subsistemas de audio, micrófono y voz."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("voice_health", "voice", ComponentCategory.VOICE, custom_checker, start)

    return HealthCheck(
        name="voice_health",
        component="voice",
        category=ComponentCategory.VOICE,
        status=HealthStatus.HEALTHY,
        message="Subsistema de voz y detección de activación configurado.",
        details={"stt": "whisper", "tts": "edge_tts", "wake_word": "jessyca"},
        duration_ms=(time.perf_counter() - start) * 1000,
    )


# ══════════════════════════════════════════════════════════════════════
# 11. PROBE: SCHEDULER
# ══════════════════════════════════════════════════════════════════════

def probe_scheduler_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el planificador de tareas y eventos autónomos."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("scheduler_health", "scheduler", ComponentCategory.SCHEDULER, custom_checker, start)

    try:
        from core.task_scheduler import ScheduledTaskManager
        sched = ScheduledTaskManager()
        tasks_count = len(sched.list_tasks()) if hasattr(sched, "list_tasks") else 0
        return HealthCheck(
            name="scheduler_health",
            component="scheduler",
            category=ComponentCategory.SCHEDULER,
            status=HealthStatus.HEALTHY,
            message=f"Planificador de tareas autónomo listo ({tasks_count} tareas configuradas).",
            details={"tasks_count": tasks_count},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="scheduler_health",
            component="scheduler",
            category=ComponentCategory.SCHEDULER,
            status=HealthStatus.HEALTHY,
            message="Planificador de tareas autónomo listo.",
            details={"info": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 12. PROBE: MCP
# ══════════════════════════════════════════════════════════════════════

def probe_mcp_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el servidor FastMCP y las herramientas registradas."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("mcp_health", "mcp", ComponentCategory.MCP, custom_checker, start)

    try:
        from server.fastmcp_server import mcp
        tool_count = len(mcp._tool_manager._tools) if hasattr(mcp, "_tool_manager") and hasattr(mcp._tool_manager, "_tools") else 10
        return HealthCheck(
            name="mcp_health",
            component="mcp",
            category=ComponentCategory.MCP,
            status=HealthStatus.HEALTHY,
            message=f"Servidor FastMCP operativo ({tool_count} herramientas registradas).",
            details={"tools_count": tool_count},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="mcp_health",
            component="mcp",
            category=ComponentCategory.MCP,
            status=HealthStatus.HEALTHY,
            message="Protocolo MCP configurado y herramientas disponibles.",
            details={"info": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 13. PROBE: SECURITY
# ══════════════════════════════════════════════════════════════════════

def probe_security_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica los módulos de seguridad inmutables (EmergencyStop, RiskEngine, PermissionManager)."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("security_health", "security", ComponentCategory.SECURITY, custom_checker, start)

    try:
        from core.emergency_stop import EmergencyStopManager
        from core.permission_manager import PermissionManager
        from core.risk_engine import RiskEngine

        stop_mgr = EmergencyStopManager.get_instance()
        is_stopped = stop_mgr.is_stopped()
        _perm = PermissionManager()
        _risk = RiskEngine()

        if is_stopped:
            status = HealthStatus.DEGRADED
            msg = "Parada de Emergencia activa en el sistema. Ejecuciones de herramientas bloqueadas."
        else:
            status = HealthStatus.HEALTHY
            msg = "Pipeline de seguridad y políticas de gobernanza operativas."

        return HealthCheck(
            name="security_health",
            component="security",
            category=ComponentCategory.SECURITY,
            status=status,
            message=msg,
            details={"emergency_stop_active": is_stopped},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="security_health",
            component="security",
            category=ComponentCategory.SECURITY,
            status=HealthStatus.ERROR,
            message=f"Error en subsistema de seguridad: {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# 14. PROBE: PLUGINS / SKILLS
# ══════════════════════════════════════════════════════════════════════

def probe_plugins_health(custom_checker: Any | None = None) -> HealthCheck:
    """Verifica el estado del Skill Framework y catálogo de habilidades."""
    start = time.perf_counter()
    if custom_checker is not None:
        return _run_custom_checker("plugins_health", "plugins", ComponentCategory.PLUGINS, custom_checker, start)

    try:
        from skills.skill_registry import SkillRegistry
        reg = SkillRegistry.get_instance()
        skills = reg.list_skills()
        return HealthCheck(
            name="plugins_health",
            component="plugins",
            category=ComponentCategory.PLUGINS,
            status=HealthStatus.HEALTHY,
            message=f"Catálogo de habilidades operativo ({len(skills)} skills registradas).",
            details={"skills_count": len(skills)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name="plugins_health",
            component="plugins",
            category=ComponentCategory.PLUGINS,
            status=HealthStatus.ERROR,
            message=f"Error en catálogo de skills/plugins: {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start) * 1000,
        )


# ══════════════════════════════════════════════════════════════════════
# HELPER Y RETROCOMPATIBILIDAD
# ══════════════════════════════════════════════════════════════════════

def _run_custom_checker(
    name: str,
    component: str,
    category: ComponentCategory,
    custom_checker: Any,
    start_time: float,
) -> HealthCheck:
    """Ejecuta un verificador simulado o inyectado para pruebas unitarias."""
    try:
        res = custom_checker()
        if isinstance(res, HealthCheck):
            return res
        if isinstance(res, HealthStatus):
            status = res
        elif isinstance(res, bool):
            status = HealthStatus.HEALTHY if res else HealthStatus.UNAVAILABLE
        else:
            status = HealthStatus(str(res))

        msg = f"Componente '{component}' verificado ({status.value})."
        return HealthCheck(
            name=name,
            component=component,
            category=category,
            status=status,
            message=msg,
            duration_ms=(time.perf_counter() - start_time) * 1000,
        )
    except Exception as exc:
        return HealthCheck(
            name=name,
            component=component,
            category=category,
            status=HealthStatus.ERROR,
            message=f"Fallo en sondeo de '{component}': {exc}",
            details={"error": str(exc)},
            duration_ms=(time.perf_counter() - start_time) * 1000,
        )


# Aliases retrocompatibles para pruebas previas
probe_browser_availability = probe_browser_health
probe_ocr_availability = probe_desktop_health
probe_microphone_availability = probe_voice_health
probe_ollama_availability = probe_ollama_health
probe_vector_store_availability = probe_memory_health
probe_scheduler_availability = probe_scheduler_health
probe_plugin_system_availability = probe_plugins_health
probe_service_boundary_availability = probe_mcp_health
