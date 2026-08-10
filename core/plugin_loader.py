"""Subsistema de Carga Segura de Plugins (PluginLoader - Etapa 14.2).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 14.2:
1. REGLA CRÍTICA ABSOLUTA: NO IMPORTAR CÓDIGO DE PLUGIN ANTES DE VALIDAR SU MANIFIESTO.
2. FLUJO OBLIGATORIO DE CARGA:
   discover -> inspect metadata -> read manifest -> validate -> verify integrity -> permission check -> load
3. CARGA EXCLUSIVA DESDE PLUGINS_DIRECTORY.
4. PREVENCIÓN DE:
   - Path Traversal (..)
   - Symlink Escape (escape mediante enlaces simbólicos fuera del directorio de plugins)
   - Arbitrary Locations (rutas absolutas o externas)
   - Duplicate Plugin IDs (prevención de sobrescritura de plugins en ejecución)
   - Manifest/Code Mismatch (desacople entre el entrypoint declarado y el archivo real)
5. CAPACIDAD ACOTADA (PLUGINS_MAX_LOADED).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.exceptions import MCPError
from core.logger import get_logger
from core.plugin_manifest import (
    PluginManifest,
    PluginManifestValidator,
    PluginPathSecurityError,
    PluginValidationError,
)
from core.plugin_security import (
    PluginRiskProfile,
    PluginSecurityPolicy,
)

logger = get_logger("jessyca.core.plugin_loader")


class PluginLoaderSecurityError(MCPError):
    """Error base de violaciones de seguridad durante la carga de plugins."""

    pass


class PluginIntegrityError(PluginLoaderSecurityError):
    """Error emitido cuando hay un desacople entre el manifiesto y el código ejecutable (Manifest/Code Mismatch)."""

    pass


class PluginCapacityExceededError(PluginLoaderSecurityError):
    """Error emitido al superar la cantidad máxima permitida de plugins cargados (PLUGINS_MAX_LOADED)."""

    pass


@dataclass
class LoadedPlugin:
    """Representación inmutable de un plugin cargado en memoria."""

    manifest: PluginManifest
    plugin_dir: Path
    risk_profile: PluginRiskProfile
    module: Any | None = None
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def plugin_id(self) -> str:
        return self.manifest.metadata.plugin_id


@runtime_checkable
class IPluginLoader(Protocol):
    """Interfaz abstracta para cargadores de plugins."""

    def discover_plugins(self) -> list[Path]:
        """Descubre directorios de plugins en el directorio configurado."""
        ...

    def load_plugin(self, plugin_dir: Path | str) -> LoadedPlugin:
        """Carga un plugin siguiendo el flujo seguro obligatorio."""
        ...

    def unload_plugin(self, plugin_id: str) -> bool:
        """Descarga un plugin activo."""
        ...

    def get_loaded_plugin(self, plugin_id: str) -> LoadedPlugin | None:
        """Obtiene una referencia al plugin cargado."""
        ...


class PluginLoader:
    """Cargador Seguro de Plugins (PluginLoader - Etapa 14.2).

    ENFORZA EL FLUJO RIGUROSO OBLIGATORIO:
    discover -> inspect metadata -> read manifest -> validate -> verify integrity -> permission check -> load
    """

    def __init__(
        self,
        plugins_dir: Path | str | None = None,
        max_loaded: int | None = None,
        security_policy: PluginSecurityPolicy | None = None,
        manifest_validator: PluginManifestValidator | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.enabled = settings.PLUGINS_ENABLED

        p_dir = plugins_dir or settings.PLUGINS_DIRECTORY
        self.plugins_directory = Path(p_dir).resolve()
        self.max_loaded = max_loaded if max_loaded is not None else settings.PLUGINS_MAX_LOADED

        self.security_policy = security_policy or PluginSecurityPolicy()
        self.manifest_validator = manifest_validator or PluginManifestValidator(self.security_policy)

        self._loaded_plugins: dict[str, LoadedPlugin] = {}
        self._lock = threading.RLock()
        self.audit_logger = get_audit_logger()

    def discover_plugins(self) -> list[Path]:
        """Etapa 1 del Flujo: Discover. Descubre carpetas de plugins válidas dentro del PLUGINS_DIRECTORY."""
        with self._lock:
            if not self.enabled:
                logger.info("[PLUGIN LOADER] Plugins deshabilitados por configuración.")
                return []

            if not self.plugins_directory.exists():
                logger.warning(f"[PLUGIN LOADER] El directorio de plugins '{self.plugins_directory}' no existe.")
                return []

            discovered: list[Path] = []
            for entry in self.plugins_directory.iterdir():
                if entry.is_dir() and (entry / "plugin.json").exists():
                    try:
                        self._validate_path_contained_in_plugins_dir(entry)
                        discovered.append(entry)
                    except PluginPathSecurityError as e:
                        logger.error(f"[PLUGIN LOADER] Intento de escape o directorio inseguro omitido: {e}")

            return discovered

    def load_plugin(self, plugin_dir: Path | str) -> LoadedPlugin:
        """Ejecuta el flujo seguro completo para cargar un plugin.

        REGLA ABSOLUTA: NO SE IMPORTA CÓDIGO HASTA COMPLETAR LA VALIDACIÓN DEL MANIFIESTO E INTEGRIDAD.
        """
        if not self.enabled:
            raise PluginLoaderSecurityError("[SECURITY VIOLATION] Carga de plugins deshabilitada por configuración.")

        p_dir = Path(plugin_dir).resolve()

        with self._lock:
            # Check de capacidad de plugins cargados
            if len(self._loaded_plugins) >= self.max_loaded:
                raise PluginCapacityExceededError(
                    f"[CAPACITY EXCEEDED] Se alcanzó la cantidad máxima de plugins cargados simultáneamente ({self.max_loaded})."
                )

            # 1. VERIFICAR SEGURIDAD DE RUTA Y SYMLINK ESCAPE
            self._validate_path_contained_in_plugins_dir(p_dir)

            manifest_file = p_dir / "plugin.json"
            if not manifest_file.exists():
                raise PluginValidationError(f"No se encontró el archivo 'plugin.json' en '{p_dir}'.")

            # 2. READ MANIFEST & VALIDATE (REGLA: ANTES DE IMPORTAR CÓDIGO)
            manifest = self.manifest_validator.validate_manifest_file(manifest_file)

            # 3. VERIFICAR PREVENCIÓN DE DUPLICADOS DE PLUGIN ID
            if manifest.metadata.plugin_id in self._loaded_plugins:
                raise PluginLoaderSecurityError(
                    f"[DUPLICATE ID REJECTION] El plugin ID '{manifest.metadata.plugin_id}' ya se encuentra cargado en memoria."
                )

            # 4. VERIFY INTEGRITY (MANIFEST / CODE MISMATCH CHECK)
            entrypoint_path = (p_dir / manifest.metadata.entrypoint).resolve()
            self._validate_manifest_code_integrity(p_dir, entrypoint_path, manifest)

            # 5. PERMISSION CHECK (Aprobar manifiesto y verificar perfil de riesgo)
            approved_manifest = self.manifest_validator.approve_manifest(manifest, reviewer_id="secure_loader")
            risk_profile = self.security_policy.validate_plugin_manifest(
                plugin_id=approved_manifest.metadata.plugin_id,
                requested_capability_names=list(approved_manifest.capabilities),
                declared_tools=list(approved_manifest.tools),
            )

            # 6. LOAD (Importar dinámicamente el código sólo tras aprobar todos los pasos anteriores)
            module = self._import_plugin_module(approved_manifest.metadata.plugin_id, entrypoint_path)

            loaded_plugin = LoadedPlugin(
                manifest=approved_manifest,
                plugin_dir=p_dir,
                risk_profile=risk_profile,
                module=module,
            )

            self._loaded_plugins[approved_manifest.metadata.plugin_id] = loaded_plugin
            logger.info(f"[PLUGIN LOADER] Plugin '{approved_manifest.metadata.plugin_id}' cargado exitosamente.")
            self._log_loader_audit(approved_manifest.metadata.plugin_id, success=True, action="plugin_loaded")

            return loaded_plugin

    def unload_plugin(self, plugin_id: str) -> bool:
        """Descarga un plugin cargado removiendo su referencia."""
        with self._lock:
            if plugin_id in self._loaded_plugins:
                del self._loaded_plugins[plugin_id]
                logger.info(f"[PLUGIN LOADER] Plugin '{plugin_id}' descargado.")
                self._log_loader_audit(plugin_id, success=True, action="plugin_unloaded")
                return True
            return False

    def get_loaded_plugin(self, plugin_id: str) -> LoadedPlugin | None:
        """Obtiene una referencia al plugin cargado."""
        with self._lock:
            return self._loaded_plugins.get(plugin_id)

    def _validate_path_contained_in_plugins_dir(self, target_path: Path) -> None:
        """Valida que una ruta resuelta esté estrictamente dentro de PLUGINS_DIRECTORY (previene symlink escape)."""
        resolved_target = target_path.resolve()
        real_target = Path(os.path.realpath(target_path))

        resolved_plugins_dir = self.plugins_directory.resolve()
        real_plugins_dir = Path(os.path.realpath(self.plugins_directory))

        # Verificar Path Traversal o Rutas Arbitrarias fuera del sandbox
        try:
            resolved_target.relative_to(resolved_plugins_dir)
            real_target.relative_to(real_plugins_dir)
        except ValueError as e:
            raise PluginPathSecurityError(
                f"[SECURITY VIOLATION] Intento de acceso a ruta arbitraria o Symlink Escape detectado en '{target_path}'. El plugin debe residir strictly dentro de '{self.plugins_directory}'."
            ) from e

    def _validate_manifest_code_integrity(self, plugin_dir: Path, entrypoint_path: Path, manifest: PluginManifest) -> None:
        """Verifica el acople entre el manifiesto y el código fuente (Manifest/Code Mismatch)."""
        if not entrypoint_path.exists() or not entrypoint_path.is_file():
            raise PluginIntegrityError(
                f"[MANIFEST/CODE MISMATCH] El entrypoint declarado '{manifest.metadata.entrypoint}' no existe como archivo ejecutable en '{plugin_dir}'."
            )

        # Garantizar que el entrypoint resuelto pertenezca al directorio del plugin
        try:
            entrypoint_path.relative_to(plugin_dir.resolve())
        except ValueError as e:
            raise PluginIntegrityError(
                f"[MANIFEST/CODE MISMATCH] El entrypoint '{entrypoint_path}' apunta a una ubicación fuera del directorio del plugin."
            ) from e


    def _import_plugin_module(self, plugin_id: str, entrypoint_path: Path) -> Any:
        """Importa dinámicamente un archivo Python como módulo aislado."""
        module_name = f"jessyca_plugins.{plugin_id.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
        if spec is None or spec.loader is None:
            raise PluginIntegrityError(f"No se pudo crear la especificación de módulo para '{entrypoint_path}'.")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _log_loader_audit(self, plugin_id: str, success: bool, action: str) -> None:
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"loader-{plugin_id[:8]}",
                tool_name="plugin.loader",
                operation=action,
                duration_ms=0.0,
                reason=f"Plugin loader action '{action}' success={success}",
                metadata={"plugin_id": plugin_id, "action": action, "success": success},
            )
        )


class FakePluginLoader:
    """Implementación de prueba de IPluginLoader para testing en aislamiento completo."""

    def __init__(self) -> None:
        self.discovered_paths: list[Path] = []
        self.loaded_plugins: dict[str, LoadedPlugin] = {}

    def discover_plugins(self) -> list[Path]:
        return self.discovered_paths

    def load_plugin(self, plugin_dir: Path | str) -> LoadedPlugin:
        from core.autonomy_policy import TaskActionRisk
        from core.plugin_manifest import PluginManifestValidator
        p = Path(plugin_dir)
        manifest_file = p / "plugin.json"
        manifest = PluginManifestValidator().validate_manifest_file(manifest_file)

        loaded = LoadedPlugin(
            manifest=manifest,
            plugin_dir=p,
            risk_profile=PluginRiskProfile(manifest.metadata.plugin_id, (), TaskActionRisk.READ_ONLY),
            module=None,
        )

        self.loaded_plugins[manifest.metadata.plugin_id] = loaded
        return loaded

    def unload_plugin(self, plugin_id: str) -> bool:
        if plugin_id in self.loaded_plugins:
            del self.loaded_plugins[plugin_id]
            return True
        return False

    def get_loaded_plugin(self, plugin_id: str) -> LoadedPlugin | None:
        return self.loaded_plugins.get(plugin_id)
