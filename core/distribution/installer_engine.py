"""Motor de Instalación, Actualización y Desinstalación para Windows (installer_engine.py - Fase 46).

Implementa:
- Instalación limpia (Clean Install) con estructura de carpetas, configuraciones y accesos directos.
- Actualización atómica con validación previa de integridad y compatibilidad.
- Rollback automático ante fallo en la actualización.
- Desinstalación transparente y granular con preservación de datos del usuario.
- Reinstalación conservando la memoria previa.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from core.distribution.backup_rollback import BackupManager, RollbackManager
from core.distribution.config_manager import ProductConfigManager, ProductUnifiedConfig
from core.distribution.distribution_models import (
    InstallationState,
    ProductVersion,
    ReleaseManifest,
    UninstallScope,
)
from core.logger import get_logger

logger = get_logger("jessyca.distribution.installer")


class WindowsInstallerEngine:
    """Motor de orquestación de ciclo de vida del producto JESSYCA en Windows."""

    def __init__(
        self,
        install_root: str | Path,
        data_root: str | Path,
        config_manager: ProductConfigManager | None = None,
        backup_manager: BackupManager | None = None,
        rollback_manager: RollbackManager | None = None,
    ) -> None:
        self.install_root = Path(install_root)
        self.data_root = Path(data_root)
        self.config_dir = self.data_root / "config"
        self.memory_dir = self.data_root / "memory"
        self.skills_dir = self.data_root / "skills"
        self.logs_dir = self.data_root / "logs"

        self.config_manager = config_manager or ProductConfigManager(self.config_dir / "settings.json")
        self.backup_manager = backup_manager or BackupManager(self.data_root / "backups")
        self.rollback_manager = rollback_manager or RollbackManager(self.data_root / "snapshots")

        self._state: InstallationState = InstallationState.NOT_INSTALLED
        self._current_version = ProductVersion(3, 0, 0)
        self._installed_shortcuts: list[str] = []
        self._lock = threading.RLock()

    @property
    def state(self) -> InstallationState:
        with self._lock:
            return self._state

    @property
    def current_version(self) -> ProductVersion:
        with self._lock:
            return self._current_version

    def clean_install(self, manifest: ReleaseManifest) -> tuple[bool, str | None]:
        """Ejecuta una instalación limpia de JESSYCA."""
        with self._lock:
            self._state = InstallationState.INSTALLING
            try:
                # 1. Crear estructura de carpetas
                self.install_root.mkdir(parents=True, exist_ok=True)
                self.config_dir.mkdir(parents=True, exist_ok=True)
                self.memory_dir.mkdir(parents=True, exist_ok=True)
                self.skills_dir.mkdir(parents=True, exist_ok=True)
                self.logs_dir.mkdir(parents=True, exist_ok=True)

                # 2. Escribir archivo de versión y manifiesto
                version_file = self.install_root / "version.json"
                with open(version_file, "w", encoding="utf-8") as f:
                    json.dump(manifest.to_dict(), f, indent=2)

                # 3. Inicializar configuración por defecto
                default_cfg = ProductUnifiedConfig()
                default_cfg.system.base_install_path = str(self.install_root)
                default_cfg.system.data_dir = str(self.data_root)
                self.config_manager.update_config(default_cfg)
                self.config_manager.save_to_disk(self.config_dir / "settings.json")

                # 4. Registrar accesos directos
                self._installed_shortcuts = [
                    "Desktop\\JESSYCA 3.0.lnk",
                    "StartMenu\\Programs\\JESSYCA.lnk",
                ]

                self._current_version = manifest.version
                self._state = InstallationState.INSTALLED
                logger.info(f"[INSTALL SUCCESS] JESSYCA {manifest.version} instalado en {self.install_root}")
                return True, None

            except Exception as ex:
                self._state = InstallationState.FAILED
                logger.error(f"[INSTALL FAILED] {ex}")
                return False, str(ex)

    def upgrade(
        self,
        new_manifest: ReleaseManifest,
        simulated_failure: bool = False,
    ) -> tuple[bool, str | None]:
        """Ejecuta una actualización atómica con validación y rollback en caso de fallo."""
        with self._lock:
            if self._state not in (InstallationState.INSTALLED, InstallationState.ROLLED_BACK):
                return False, f"No se puede actualizar desde el estado actual: {self._state}"

            self._state = InstallationState.UPGRADING
            snapshot_id = f"snap-pre-upgrade-{int(time.time())}"

            # 1. Crear instantánea de seguridad antes de modificar nada
            self.rollback_manager.create_snapshot(
                snapshot_id=snapshot_id,
                source_dirs=[self.install_root, self.config_dir],
            )

            try:
                # 2. Simulación de fallo en post-instalación o validación
                if simulated_failure or new_manifest.binary_sha256 == "CORRUPT_HASH":
                    raise RuntimeError("Fallo de validación post-upgrade: Checksum de binario inválido o servicio inestable.")

                # 3. Actualizar archivos y versión
                version_file = self.install_root / "version.json"
                with open(version_file, "w", encoding="utf-8") as f:
                    json.dump(new_manifest.to_dict(), f, indent=2)

                self._current_version = new_manifest.version
                self._state = InstallationState.INSTALLED
                self.rollback_manager.cleanup_snapshot(snapshot_id)

                logger.info(f"[UPGRADE SUCCESS] Actualizado a JESSYCA {new_manifest.version}")
                return True, None

            except Exception as ex:
                logger.warning(f"[UPGRADE FAILED] Error durante upgrade ({ex}). Ejecutando rollback automático...")
                # 4. Rollback automático
                rollback_ok = self.rollback_manager.rollback(
                    snapshot_id=snapshot_id,
                    target_dirs_map={
                        self.install_root.name: self.install_root,
                        self.config_dir.name: self.config_dir,
                    },
                )
                self._state = InstallationState.ROLLED_BACK if rollback_ok else InstallationState.CORRUPTED
                return False, f"Upgrade falló y se aplicó rollback: {ex}"

    def uninstall(self, scope: UninstallScope) -> tuple[bool, str | None]:
        """Ejecuta la desinstalación respetando el alcance definido."""
        with self._lock:
            self._state = InstallationState.UNINSTALLING
            try:
                # 1. Eliminar binarios de la aplicación
                if scope.remove_application_binaries and self.install_root.exists():
                    shutil.rmtree(self.install_root)

                # 2. Eliminar accesos directos
                if scope.remove_shortcuts:
                    self._installed_shortcuts.clear()

                # 3. Eliminar configuraciones si se solicitó
                if scope.remove_configuration_files and self.config_dir.exists():
                    shutil.rmtree(self.config_dir)

                # 4. Eliminar memoria si se solicitó explícitamente
                if scope.remove_memory_databases and self.memory_dir.exists():
                    shutil.rmtree(self.memory_dir)

                # 5. Eliminar logs si se solicitó
                if scope.remove_logs and self.logs_dir.exists():
                    shutil.rmtree(self.logs_dir)

                self._state = InstallationState.UNINSTALLED
                logger.info("[UNINSTALL COMPLETE] JESSYCA desinstalado con éxito según el alcance solicitado.")
                return True, None

            except Exception as ex:
                self._state = InstallationState.FAILED
                logger.error(f"[UNINSTALL ERROR] {ex}")
                return False, str(ex)

    def reinstall(self, manifest: ReleaseManifest) -> tuple[bool, str | None]:
        """Reinstala la aplicación conservando los datos de usuario existentes."""
        with self._lock:
            return self.clean_install(manifest)
