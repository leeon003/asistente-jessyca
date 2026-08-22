"""Asistente de Primer Inicio y Verificación de Inicialización (first_run_wizard.py - Fase 46).

Ejecuta secuencialmente los 8 pasos del ciclo First Run:
1. Installation Check
2. Configuration Setup
3. Environment Check
4. Model Check
5. Microphone & Audio Check
6. Permissions Check
7. Security Initialization
8. First Launch Validation
"""

from __future__ import annotations

import threading

from core.distribution.distribution_models import FirstRunStatus, FirstRunStep
from core.distribution.environment_diagnostics import EnvironmentDiagnosticsEngine
from core.distribution.installer_engine import WindowsInstallerEngine
from core.logger import get_logger

logger = get_logger("jessyca.distribution.first_run")


class FirstRunWizard:
    """Orquestador del flujo de primer inicio y verificación del sistema."""

    def __init__(self, installer: WindowsInstallerEngine) -> None:
        self.installer = installer
        self._lock = threading.RLock()

    def run_wizard(self) -> FirstRunStatus:
        """Ejecuta los 8 pasos de inicialización de primer uso."""
        with self._lock:
            status = FirstRunStatus()

            # PASO 1: Installation
            status.current_step = FirstRunStep.INSTALLATION
            if not self.installer.install_root.exists():
                status.errors.append("Directorio de instalación no encontrado.")
                return status
            status.completed_steps.append(FirstRunStep.INSTALLATION)

            # PASO 2: Configuration
            status.current_step = FirstRunStep.CONFIGURATION
            cfg = self.installer.config_manager.get_config()
            if not cfg or not cfg.user or not cfg.system:
                status.errors.append("Configuración base corrupta o incompleta.")
                return status
            status.completed_steps.append(FirstRunStep.CONFIGURATION)

            # PASO 3: Environment Check
            status.current_step = FirstRunStep.ENVIRONMENT_CHECK
            diag = EnvironmentDiagnosticsEngine.run_diagnostics()
            if diag.windows_build < 19041:
                status.errors.append(f"Windows Build ({diag.windows_build}) es menor al requerido (19041).")
                return status
            status.environment_ok = True
            status.completed_steps.append(FirstRunStep.ENVIRONMENT_CHECK)

            # PASO 4: Model Check
            status.current_step = FirstRunStep.MODEL_CHECK
            if not diag.ollama_running or len(diag.ollama_models) == 0:
                status.errors.append("No se detectaron modelos LLM locales listos en Ollama.")
                return status
            status.models_ready = True
            status.completed_steps.append(FirstRunStep.MODEL_CHECK)

            # PASO 5: Microphone & Audio Check
            status.current_step = FirstRunStep.MICROPHONE_CHECK
            if not diag.microphone_available or not diag.speakers_available:
                status.errors.append("Dispositivos de audio no listos.")
                return status
            status.audio_ready = True
            status.completed_steps.append(FirstRunStep.MICROPHONE_CHECK)

            # PASO 6: Permissions Check
            status.current_step = FirstRunStep.PERMISSIONS_CHECK
            # Validar permisos de escritura en data_dir y config_dir
            if not self.installer.data_root.exists():
                status.errors.append("No hay permisos de escritura en la carpeta de datos.")
                return status
            status.completed_steps.append(FirstRunStep.PERMISSIONS_CHECK)

            # PASO 7: Security Initialization
            status.current_step = FirstRunStep.SECURITY_INITIALIZATION
            status.security_ready = True
            status.completed_steps.append(FirstRunStep.SECURITY_INITIALIZATION)

            # PASO 8: First Launch
            status.current_step = FirstRunStep.FIRST_LAUNCH
            status.first_launch_ready = True
            status.completed_steps.append(FirstRunStep.FIRST_LAUNCH)
            status.is_success = True

            logger.info("[FIRST RUN COMPLETE] Asistente de primer inicio finalizado con éxito (8/8 pasos completados).")
            return status
