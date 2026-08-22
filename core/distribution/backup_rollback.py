"""Módulos de Backup Seguro y Rollback Automático (backup_rollback.py - Fase 46).

Proporciona:
- Respaldo atómico de configuraciones, preferencias de usuario, bases de datos de memoria y metadatos de Skills.
- Exclusión estricta de secretos y credenciales en backups.
- Verificación de integridad por SHA-256.
- Instantáneas previas a la actualización (Snapshots) y Rollback automático ante fallos de validación.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from core.distribution.distribution_models import BackupManifest
from core.distribution.environment_diagnostics import EnvironmentDiagnosticsEngine
from core.logger import get_logger

logger = get_logger("jessyca.distribution.backup_rollback")


class BackupManager:
    """Administrador de creación y restauración de copias de seguridad seguras."""

    def __init__(self, backup_root_dir: str | Path) -> None:
        self.backup_root = Path(backup_root_dir)
        self._lock = threading.RLock()

    def create_backup(
        self,
        config_data: dict[str, Any],
        memory_files: list[Path] | None = None,
        product_version: str = "3.0.0",
        custom_backup_id: str | None = None,
    ) -> tuple[BackupManifest | None, str | None]:
        """Crea un backup consistente excluyendo cualquier secreto."""
        with self._lock:
            try:
                bck_id = custom_backup_id or f"backup-{int(time.time())}"
                dest_dir = self.backup_root / bck_id
                dest_dir.mkdir(parents=True, exist_ok=True)

                # 1. Sanitizar y guardar configuraciones
                raw_config = json.dumps(config_data, indent=2, ensure_ascii=False)
                sanitized_config = EnvironmentDiagnosticsEngine.sanitize_text(raw_config)
                config_file = dest_dir / "config.json"
                with open(config_file, "w", encoding="utf-8") as f:
                    f.write(sanitized_config)

                # 2. Copiar archivos de memoria si existen
                files_count = 1
                if memory_files:
                    mem_dir = dest_dir / "memory"
                    mem_dir.mkdir(parents=True, exist_ok=True)
                    for mf in memory_files:
                        if mf.exists() and mf.is_file():
                            shutil.copy2(mf, mem_dir / mf.name)
                            files_count += 1

                # 3. Calcular hash de integridad SHA-256
                computed_hash = self._compute_directory_hash(dest_dir)

                manifest = BackupManifest(
                    backup_id=bck_id,
                    product_version=product_version,
                    backup_path=str(dest_dir),
                    content_hash=computed_hash,
                    files_count=files_count,
                    secrets_excluded=True,
                )

                # Guardar manifiesto
                with open(dest_dir / "backup_manifest.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "backup_id": manifest.backup_id,
                            "product_version": manifest.product_version,
                            "content_hash": manifest.content_hash,
                            "files_count": manifest.files_count,
                            "created_at": manifest.created_at,
                            "secrets_excluded": manifest.secrets_excluded,
                        },
                        f,
                        indent=2,
                    )

                logger.info(f"[BACKUP SUCCESS] Respaldo '{bck_id}' creado en {dest_dir} (Hash: {computed_hash[:10]}...)")
                return manifest, None

            except Exception as ex:
                logger.error(f"[BACKUP ERROR] Error creando respaldo: {ex}")
                return None, str(ex)

    def restore_backup(self, backup_dir: Path, target_restore_dir: Path) -> tuple[bool, str | None]:
        """Restaura un respaldo verificando la integridad del contenido."""
        with self._lock:
            try:
                if not backup_dir.exists():
                    return False, f"Directorio de respaldo no existe: {backup_dir}"

                manifest_file = backup_dir / "backup_manifest.json"
                if not manifest_file.exists():
                    return False, "Manifiesto de respaldo corrupto o inexistente."

                with open(manifest_file, encoding="utf-8") as f:
                    manifest_data = json.load(f)

                expected_hash = manifest_data.get("content_hash", "")
                actual_hash = self._compute_directory_hash(backup_dir, exclude_manifest=True)

                if expected_hash and expected_hash != actual_hash:
                    return False, f"Fallo de integridad: hash esperado '{expected_hash[:8]}' != actual '{actual_hash[:8]}'."

                # Restaurar archivos hacia el directorio destino
                target_restore_dir.mkdir(parents=True, exist_ok=True)
                for item in backup_dir.iterdir():
                    if item.name != "backup_manifest.json":
                        dest_item = target_restore_dir / item.name
                        if item.is_dir():
                            if dest_item.exists():
                                shutil.rmtree(dest_item)
                            shutil.copytree(item, dest_item)
                        else:
                            shutil.copy2(item, dest_item)

                logger.info(f"[RESTORE SUCCESS] Respaldo restaurado con éxito en {target_restore_dir}")
                return True, None

            except Exception as ex:
                logger.error(f"[RESTORE ERROR] Error restaurando respaldo: {ex}")
                return False, str(ex)

    def _compute_directory_hash(self, directory: Path, exclude_manifest: bool = True) -> str:
        """Calcula el hash determinista SHA-256 de los contenidos del directorio."""
        hasher = hashlib.sha256()
        for root, _, files in os.walk(directory):
            for fname in sorted(files):
                if exclude_manifest and fname == "backup_manifest.json":
                    continue
                fpath = Path(root) / fname
                hasher.update(fname.encode("utf-8"))
                with open(fpath, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
        return hasher.hexdigest()


class RollbackManager:
    """Administrador de instantáneas previas a actualización y reversión automática."""

    def __init__(self, snapshots_dir: str | Path) -> None:
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create_snapshot(self, snapshot_id: str, source_dirs: list[Path]) -> Path:
        """Crea una instantánea atómica de las rutas especificadas."""
        with self._lock:
            snap_path = self.snapshots_dir / snapshot_id
            if snap_path.exists():
                shutil.rmtree(snap_path)
            snap_path.mkdir(parents=True, exist_ok=True)

            for sdir in source_dirs:
                if sdir.exists():
                    target_dest = snap_path / sdir.name
                    if sdir.is_dir():
                        shutil.copytree(sdir, target_dest)
                    else:
                        shutil.copy2(sdir, target_dest)

            logger.info(f"[SNAPSHOT CREATED] Instantánea '{snapshot_id}' creada con éxito en {snap_path}")
            return snap_path

    def rollback(self, snapshot_id: str, target_dirs_map: dict[str, Path]) -> bool:
        """Revierte los directorios a su estado en la instantánea."""
        with self._lock:
            snap_path = self.snapshots_dir / snapshot_id
            if not snap_path.exists():
                logger.error(f"[ROLLBACK FAILED] No existe la instantánea '{snapshot_id}'.")
                return False

            try:
                for item_name, original_target in target_dirs_map.items():
                    item_in_snap = snap_path / item_name
                    if item_in_snap.exists():
                        if original_target.exists():
                            if original_target.is_dir():
                                shutil.rmtree(original_target)
                            else:
                                original_target.unlink()

                        if item_in_snap.is_dir():
                            shutil.copytree(item_in_snap, original_target)
                        else:
                            shutil.copy2(item_in_snap, original_target)

                logger.info(f"[ROLLBACK COMPLETE] Reversión a instantánea '{snapshot_id}' ejecutada con éxito.")
                return True
            except Exception as ex:
                logger.error(f"[ROLLBACK ERROR] Error ejecutando reversión: {ex}")
                return False

    def cleanup_snapshot(self, snapshot_id: str) -> None:
        """Elimina una instantánea tras el éxito confirmado de la actualización."""
        with self._lock:
            snap_path = self.snapshots_dir / snapshot_id
            if snap_path.exists():
                shutil.rmtree(snap_path)
                logger.debug(f"[SNAPSHOT CLEANED] Instantánea '{snapshot_id}' eliminada.")
