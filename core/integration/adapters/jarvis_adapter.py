"""Adapter de Integración de Jarvis-py para JESSYCA 4.0.

Implementa la integración controlada del recurso externo Shaan-alpha/jarvis-py (v3.5.2)
a través de la arquitectura del Integration Hub.

Principios Obligatorios:
1. IDENTIDAD: Jarvis-py NO es un asistente independiente; es un proveedor de capacidades para JESSYCA.
2. SEGURIDAD: Toda acción está sujeta a la Security Layer de JESSYCA.
3. EXECUTE -> VERIFY -> REPORT: El adapter nunca auto-certifica éxito comprobable (verified=False por defecto).
4. AISLAMIENTO: Dependencias externas opcionales y controladas sin acoplar el Core de JESSYCA.
5. FALLBACK: Si Jarvis falla o está deshabilitado, JESSYCA recurre a sus capacidades nativas.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.security import RiskLevel

logger = get_logger("jessyca.integration.adapters.jarvis")

CLIPBOARD_PREVIEW_LIMIT = 200
FILE_PREVIEW_LIMIT = 200
FILE_LIST_LIMIT = 20

_APP_ALIASES = {
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "paint": "mspaint",
    "explorer": "explorer",
    "files": "explorer",
    "cmd": "cmd",
    "command prompt": "cmd",
    "terminal": "cmd",
    "spotify": "spotify:",
    "chrome": "chrome",
    "edge": "microsoft-edge:",
    "browser": "microsoft-edge:",
}

_CLOSE_IMAGES = {
    "calculator": "CalculatorApp.exe",
    "calc": "CalculatorApp.exe",
    "notepad": "notepad.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
}


class JarvisAdapter(IntegrationAdapter):
    """Adapter oficial para la integración controlada de capacidades de Shaan-alpha/jarvis-py."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        super().__init__(
            name="jarvis-py",
            version="3.5.2",
            dependencies=["psutil", "pyperclip"],
        )
        self._workspace_root = workspace_root or (Path(os.environ.get("LOCALAPPDATA", ".")) / "jarvis" / "workspace")
        self._register_audited_capabilities()

    def _register_audited_capabilities(self) -> None:
        """Registra exclusivamente las capacidades reales y auditadas de jarvis-py."""
        # 1. Telemetría y estado del sistema (CPU, Batería)
        self.register_capability(
            IntegrationCapability(
                name="jarvis.system_status",
                description="Reporte de telemetría de CPU y batería del sistema vía psutil",
                required_risk_level=RiskLevel.READ_ONLY,
                required_permissions=[],
                parameters_schema={},
            )
        )

        # 2. Control de volumen y audio
        self.register_capability(
            IntegrationCapability(
                name="jarvis.volume_control",
                description="Control de volumen (subir, bajar, mutear) mediante atajos multimedia de Windows",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["audio.control"],
                parameters_schema={
                    "action": {"type": "str", "enum": ["increase", "decrease", "mute"], "required": True},
                },
            )
        )

        # 3. Portapapeles
        self.register_capability(
            IntegrationCapability(
                name="jarvis.clipboard",
                description="Lectura y escritura en el portapapeles del sistema",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=["clipboard.read", "clipboard.write"],
                parameters_schema={
                    "action": {"type": "str", "enum": ["read", "write"], "required": True},
                    "text": {"type": "str", "required": False},
                },
            )
        )

        # 4. Gestión de archivos en workspace aislado
        self.register_capability(
            IntegrationCapability(
                name="jarvis.workspace_files",
                description="Listado, lectura, escritura y búsqueda de archivos en el workspace aislado de Jarvis",
                required_risk_level=RiskLevel.WARNING,
                required_permissions=["filesystem.workspace"],
                parameters_schema={
                    "operation": {"type": "str", "enum": ["list", "read", "write", "search"], "required": True},
                    "filename": {"type": "str", "required": False},
                    "content": {"type": "str", "required": False},
                    "query": {"type": "str", "required": False},
                },
            )
        )

        # 5. Control básico de aplicaciones Windows
        self.register_capability(
            IntegrationCapability(
                name="jarvis.app_control",
                description="Apertura y cierre de aplicaciones estándar de Windows",
                required_risk_level=RiskLevel.WARNING,
                required_permissions=["apps.launch", "apps.close"],
                parameters_schema={
                    "action": {"type": "str", "enum": ["open", "close"], "required": True},
                    "app_name": {"type": "str", "required": True},
                },
            )
        )

    async def initialize(self) -> bool:
        """Inicializa el adapter verificando el entorno y dependencias."""
        has_deps, missing = self.check_dependencies()
        if not has_deps:
            logger.warning(f"[JARVIS_ADAPTER] Dependencias ausentes para jarvis-py: {missing}")
            self.status = IntegrationStatus.UNAVAILABLE
            return False

        try:
            # Asegurar directorio de workspace aislado
            self._workspace_root.mkdir(parents=True, exist_ok=True)
            self.status = IntegrationStatus.READY
            logger.info("[JARVIS_ADAPTER] JarvisAdapter v3.5.2 inicializado exitosamente en estado READY.")
            return True
        except Exception as exc:
            logger.error(f"[JARVIS_ADAPTER] Error durante inicialización: {exc}", exc_info=True)
            self.status = IntegrationStatus.ERROR
            return False

    async def health_check(self) -> IntegrationHealth:
        """Verifica la salud operacional del adapter de Jarvis."""
        start = time.perf_counter()
        has_deps, missing = self.check_dependencies()
        if not has_deps:
            return IntegrationHealth(
                status=IntegrationStatus.UNAVAILABLE,
                is_healthy=False,
                message=f"Dependencias faltantes: {missing}",
            )

        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            lat = (time.perf_counter() - start) * 1000.0
            return IntegrationHealth(
                status=self.status,
                is_healthy=(self.status == IntegrationStatus.READY),
                latency_ms=lat,
                message="JarvisAdapter operativo",
                details={"cpu_probe": cpu, "workspace": str(self._workspace_root)},
            )
        except Exception as exc:
            return IntegrationHealth(
                status=IntegrationStatus.ERROR,
                is_healthy=False,
                message=f"Excepción en health_check: {exc}",
            )

    async def shutdown(self) -> None:
        """Apaga el adapter y limpia recursos."""
        logger.info("[JARVIS_ADAPTER] Apagando JarvisAdapter.")
        self.status = IntegrationStatus.AVAILABLE

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad declarada respetando el principio EXECUTE -> VERIFY -> REPORT.

        NOTA: El adapter ejecuta la acción técnica, pero devuelve verified=False con
        verification_required=True para que el sistema de verificación de JESSYCA sea quien
        certifique el éxito.
        """
        start_time = time.perf_counter()
        cap_name = capability.strip()

        try:
            if cap_name == "jarvis.system_status":
                return self._execute_system_status(context, start_time)

            elif cap_name == "jarvis.volume_control":
                return self._execute_volume_control(context, start_time)

            elif cap_name == "jarvis.clipboard":
                return self._execute_clipboard(context, start_time)

            elif cap_name == "jarvis.workspace_files":
                return self._execute_workspace_files(context, start_time)

            elif cap_name == "jarvis.app_control":
                return self._execute_app_control(context, start_time)

            else:
                dur = (time.perf_counter() - start_time) * 1000.0
                return IntegrationExecutionResult(
                    executed=False,
                    verified=False,
                    verification_required=False,
                    status=ExecutionStatus.FAILED,
                    error=f"Capacidad desconocida: '{cap_name}'",
                    duration_ms=dur,
                )

        except Exception as exc:
            dur = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"[JARVIS_ADAPTER] Error en ejecución de '{cap_name}': {exc}", exc_info=True)
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.FAILED,
                error=f"Fallo de ejecución en jarvis-py: {exc}",
                duration_ms=dur,
            )

    # --- Métodos de Ejecución Específicos ---

    def _execute_system_status(self, context: IntegrationContext, start_time: float) -> IntegrationExecutionResult:
        # Fuente: jarvis-py (core/agent/builtins.py:system_status)
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        battery = psutil.sensors_battery()

        if battery is None:
            text = f"CPU al {cpu:.0f} por ciento."
            data = {"cpu_percent": cpu, "battery": None}
        else:
            pct = battery.percent
            charging = "cargando" if battery.power_plugged else "con batería"
            text = f"CPU al {cpu:.0f} por ciento, batería al {pct:.0f} por ciento, {charging}."
            data = {"cpu_percent": cpu, "battery_percent": pct, "power_plugged": battery.power_plugged}

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=True,
            verified=False,  # Datos técnicos leídos; no auto-certifica
            verification_required=False,
            status=ExecutionStatus.SUCCEEDED,
            output={"message": text, "telemetry": data},
            duration_ms=dur,
            metadata={"adapter": "jarvis-py", "capability": "jarvis.system_status", "source": "jarvis-py:builtins.system_status"},
        )

    def _execute_volume_control(self, context: IntegrationContext, start_time: float) -> IntegrationExecutionResult:
        # Fuente: jarvis-py (core/agent/builtins.py:increase_volume, decrease_volume, mute_volume)
        action = str(context.parameters.get("action", "")).lower()
        try:
            import pyautogui
        except ImportError:
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                status=ExecutionStatus.FAILED,
                error="pyautogui no disponible para volume_control",
                duration_ms=dur,
            )

        if action == "increase":
            for _ in range(5):
                pyautogui.press("volumeup")
            msg = "Volumen incrementado."
        elif action == "decrease":
            for _ in range(5):
                pyautogui.press("volumedown")
            msg = "Volumen reducido."
        elif action == "mute":
            pyautogui.press("volumemute")
            msg = "Volumen silenciado / alternado."
        else:
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                status=ExecutionStatus.FAILED,
                error=f"Acción de volumen inválida: '{action}'",
                duration_ms=dur,
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=True,
            verified=False,  # Requiere verificación externa de audio si aplica
            verification_required=True,
            status=ExecutionStatus.SUCCEEDED,
            output={"message": msg, "action": action},
            duration_ms=dur,
            metadata={"adapter": "jarvis-py", "capability": "jarvis.volume_control", "source": "jarvis-py:builtins.volume"},
        )

    def _execute_clipboard(self, context: IntegrationContext, start_time: float) -> IntegrationExecutionResult:
        # Fuente: jarvis-py (core/agent/builtins.py:read_clipboard, write_clipboard)
        try:
            import pyperclip
        except ImportError:
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                status=ExecutionStatus.FAILED,
                error="pyperclip no disponible para clipboard",
                duration_ms=dur,
            )

        action = str(context.parameters.get("action", "read")).lower()
        if action == "read":
            content = pyperclip.paste()
            if not content or not content.strip():
                out = "El portapapeles está vacío."
            elif len(content) <= CLIPBOARD_PREVIEW_LIMIT:
                out = content
            else:
                out = f"El portapapeles contiene {len(content)} caracteres: {content[:CLIPBOARD_PREVIEW_LIMIT]}..."

            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.SUCCEEDED,
                output={"text": out, "length": len(content) if content else 0},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.clipboard", "source": "jarvis-py:builtins.read_clipboard"},
            )

        elif action == "write":
            text_to_write = str(context.parameters.get("text", ""))
            pyperclip.copy(text_to_write)
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,
                verification_required=True,
                status=ExecutionStatus.SUCCEEDED,
                output={"message": "Texto copiado al portapapeles.", "length": len(text_to_write)},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.clipboard", "source": "jarvis-py:builtins.write_clipboard"},
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=False,
            verified=False,
            status=ExecutionStatus.FAILED,
            error=f"Acción de portapapeles desconocida: '{action}'",
            duration_ms=dur,
        )

    def _execute_workspace_files(self, context: IntegrationContext, start_time: float) -> IntegrationExecutionResult:
        # Fuente: jarvis-py (core/agent/fs_tools.py:list_files, read_file, write_file, search_files)
        op = str(context.parameters.get("operation", "list")).lower()
        root = self._workspace_root.resolve()

        if op == "list":
            files = sorted(p.name for p in root.iterdir() if p.is_file())
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.SUCCEEDED,
                output={"files": files, "count": len(files)},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.workspace_files", "source": "jarvis-py:fs_tools.list_files"},
            )

        elif op == "read":
            fname = str(context.parameters.get("filename", "")).strip()
            path = self._resolve_safe_path(fname)
            if not path or not path.is_file():
                dur = (time.perf_counter() - start_time) * 1000.0
                return IntegrationExecutionResult(
                    executed=False,
                    verified=False,
                    status=ExecutionStatus.FAILED,
                    error=f"Archivo '{fname}' no encontrado en el workspace.",
                    duration_ms=dur,
                )

            content = path.read_text(encoding="utf-8", errors="replace")
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.SUCCEEDED,
                output={"content": content, "filename": fname},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.workspace_files", "source": "jarvis-py:fs_tools.read_file"},
            )

        elif op == "write":
            fname = str(context.parameters.get("filename", "")).strip()
            content = str(context.parameters.get("content", ""))
            path = self._resolve_safe_path(fname)
            if not path:
                dur = (time.perf_counter() - start_time) * 1000.0
                return IntegrationExecutionResult(
                    executed=False,
                    verified=False,
                    status=ExecutionStatus.FAILED,
                    error="Ruta insegura o fuera del workspace.",
                    duration_ms=dur,
                )

            path.write_text(content, encoding="utf-8")
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,  # Separación EXECUTE -> VERIFY
                verification_required=True,
                status=ExecutionStatus.SUCCEEDED,
                output={"message": f"Guardado {fname}.", "filename": fname, "bytes": len(content.encode("utf-8"))},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.workspace_files", "source": "jarvis-py:fs_tools.write_file"},
            )

        elif op == "search":
            query = str(context.parameters.get("query", "")).strip().lower()
            matches = sorted(p.name for p in root.iterdir() if p.is_file() and query in p.name.lower())
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.SUCCEEDED,
                output={"matches": matches, "count": len(matches)},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.workspace_files", "source": "jarvis-py:fs_tools.search_files"},
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=False,
            verified=False,
            status=ExecutionStatus.FAILED,
            error=f"Operación de workspace inválida: '{op}'",
            duration_ms=dur,
        )

    def _execute_app_control(self, context: IntegrationContext, start_time: float) -> IntegrationExecutionResult:
        # Fuente: jarvis-py (core/agent/builtins.py:open_app, close_app, resolve_app, resolve_close_image)
        action = str(context.parameters.get("action", "")).lower()
        app_name = str(context.parameters.get("app_name", "")).strip()

        if not app_name:
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                status=ExecutionStatus.FAILED,
                error="Debe especificar 'app_name' para app_control.",
                duration_ms=dur,
            )

        if action == "open":
            target = _APP_ALIASES.get(app_name.lower(), app_name)
            try:
                os.startfile(target)
            except OSError:
                subprocess.Popen(["cmd", "/c", "start", "", target])

            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,  # OBLIGATORIO: no auto-certificar que abrió
                verification_required=True,
                status=ExecutionStatus.SUCCEEDED,
                output={"message": f"Se solicitó abrir {app_name}.", "target": target},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.app_control", "action": "open", "source": "jarvis-py:builtins.open_app"},
            )

        elif action == "close":
            image = _CLOSE_IMAGES.get(app_name.lower(), f"{app_name}.exe" if not app_name.endswith(".exe") else app_name)
            proc = subprocess.run(
                ["taskkill", "/f", "/im", image],
                check=False,
                capture_output=True,
            )
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=True,
                verified=False,  # OBLIGATORIO: no auto-certificar que cerró
                verification_required=True,
                status=ExecutionStatus.SUCCEEDED,
                output={"message": f"Se envió señal de cierre para {app_name}.", "image": image, "returncode": proc.returncode},
                duration_ms=dur,
                metadata={"adapter": "jarvis-py", "capability": "jarvis.app_control", "action": "close", "source": "jarvis-py:builtins.close_app"},
            )

        dur = (time.perf_counter() - start_time) * 1000.0
        return IntegrationExecutionResult(
            executed=False,
            verified=False,
            status=ExecutionStatus.FAILED,
            error=f"Acción de app_control inválida: '{action}'",
            duration_ms=dur,
        )

    def _resolve_safe_path(self, name: str) -> Path | None:
        """Resuelve de forma segura una ruta para evitar path traversal fuera del workspace."""
        if not name or not name.strip():
            return None

        stripped = name.strip()
        win = PureWindowsPath(stripped)
        if win.is_absolute() or win.drive:
            return None

        candidate = Path(stripped)
        if candidate.is_absolute() or candidate.drive:
            return None

        root = self._workspace_root.resolve()
        resolved = (root / candidate).resolve()
        if resolved == root or root not in resolved.parents:
            return None

        return resolved
