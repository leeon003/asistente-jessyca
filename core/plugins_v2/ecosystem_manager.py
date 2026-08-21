"""Gestor central del Ecosistema de Plugins 2.0 (ecosystem_manager.py - Fase 28).

Gestiona el registro, validación previa, aislamiento y ciclo de vida de los plugins.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. AISLAMIENTO TOTAL: Ningún plugin puede modificar las clases y módulos del Bloque de Seguridad Inmutable.
2. VALIDACIÓN PREVIA ESTRICTA: Ningún plugin no validado puede ser registrado o activado.
3. FAIL-SAFE / DENY-BY-DEFAULT.
"""

from __future__ import annotations

import threading
from typing import ClassVar

from core.logger import get_logger
from core.plugins_v2.ecosystem_models import (
    PluginManifest2,
    PluginStatus,
    PluginValidationReport,
)
from core.plugins_v2.ecosystem_validator import (
    PluginEcosystemValidator,
)

logger = get_logger("jessyca.plugins_v2.manager")


class PluginEcosystemManager:
    """Administrador thread-safe del ciclo de vida y ecosistema de plugins 2.0."""

    _instance: ClassVar[PluginEcosystemManager | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, validator: PluginEcosystemValidator | None = None) -> None:
        self._lock = threading.RLock()
        self.validator = validator or PluginEcosystemValidator()
        self._manifests: dict[str, PluginManifest2] = {}
        self._statuses: dict[str, PluginStatus] = {}

    @classmethod
    def get_instance(cls) -> PluginEcosystemManager:
        """Obtiene la instancia singleton global del gestor de plugins."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = PluginEcosystemManager()
            return cls._instance

    def install_plugin(self, manifest: PluginManifest2) -> PluginValidationReport:
        """Valida e instala un plugin en el ecosistema tras superar las 5 etapas de validación."""
        with self._lock:
            report = self.validator.validate_manifest(
                manifest=manifest,
                available_plugins=self.get_installed_versions(),
            )

            if not report.is_valid:
                logger.warning(
                    f"[PLUGIN INSTALLATION REJECTED] Plugin '{manifest.name}' rechazado: {report.overall_error}"
                )
                self._statuses[manifest.name] = PluginStatus.FAILED
                return report

            self._manifests[manifest.name] = manifest
            self._statuses[manifest.name] = PluginStatus.VALIDATED
            logger.info(f"[PLUGIN INSTALLED] Plugin '{manifest.name}' v{manifest.version} instalado y validado.")
            return report

    def activate_plugin(self, name: str) -> bool:
        """Activa un plugin instalado y validado."""
        with self._lock:
            if name not in self._manifests:
                logger.error(f"[PLUGIN ACTIVATION ERROR] Plugin '{name}' no está instalado.")
                return False

            if self._statuses.get(name) == PluginStatus.QUARANTINED:
                logger.error(f"[PLUGIN ACTIVATION BLOCKED] Plugin '{name}' se encuentra en cuarentena.")
                return False

            self._statuses[name] = PluginStatus.ACTIVE
            logger.info(f"[PLUGIN ACTIVATED] Plugin '{name}' activado.")
            return True

    def disable_plugin(self, name: str) -> bool:
        """Desactiva un plugin en ejecución."""
        with self._lock:
            if name in self._manifests:
                self._statuses[name] = PluginStatus.DISABLED
                logger.info(f"[PLUGIN DISABLED] Plugin '{name}' desactivado.")
                return True
            return False

    def quarantine_plugin(self, name: str, reason: str = "Comportamiento anómalo o sospechoso") -> bool:
        """Pone en cuarentena un plugin tras detectar una anomalía de seguridad."""
        with self._lock:
            if name in self._manifests:
                self._statuses[name] = PluginStatus.QUARANTINED
                logger.critical(f"[PLUGIN QUARANTINED] Plugin '{name}' en cuarentena: {reason}")
                return True
            return False

    def get_plugin(self, name: str) -> PluginManifest2 | None:
        """Obtiene el manifiesto del plugin si está instalado."""
        with self._lock:
            return self._manifests.get(name)

    def get_status(self, name: str) -> PluginStatus:
        """Obtiene el estado actual del plugin."""
        with self._lock:
            return self._statuses.get(name, PluginStatus.UNVALIDATED)

    def list_plugins(self) -> list[PluginManifest2]:
        """Lista todos los plugins instalados."""
        with self._lock:
            return list(self._manifests.values())

    def get_installed_versions(self) -> dict[str, str]:
        """Retorna un mapeo de nombres de plugins a versiones instaladas."""
        with self._lock:
            return {p.name: p.version for p in self._manifests.values()}

    def reset(self) -> None:
        """Limpia el estado del gestor para pruebas."""
        with self._lock:
            self._manifests.clear()
            self._statuses.clear()


def get_plugin_ecosystem_manager() -> PluginEcosystemManager:
    """Acceso helper al singleton global de PluginEcosystemManager."""
    return PluginEcosystemManager.get_instance()
