"""Representación formal y empaquetado de Skills (skill_package.py - Fase 32: Skill Installer).

Proporciona la estructura y utilidades para empaquetar, desempaquetar, inspeccionar y validar
paquetes de Skills en formatos comprimidos (.skpkg, .zip, .tar.gz) o directorios fuente.

INVARIANTES DE SEGURIDAD:
1. Prevención estricta de Zip-Slip / Path Traversal en descompresión.
2. Contención en memoria y límite máximo de tamaño de paquete (MAX_PACKAGE_SIZE = 50 MB).
3. Todo paquete debe contener un manifest formal ('manifest.json' o 'manifest.yaml').
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.exceptions import MCPError
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_models import SkillManifest

logger = get_logger("jessyca.skills.package")

MAX_PACKAGE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
MAX_FILES_COUNT: int = 500


class PackageFormat(StrEnum):
    """Formatos soportados para paquetes de Skills."""

    SKPKG = "skpkg"
    ZIP = "zip"
    TAR_GZ = "tar.gz"
    DIRECTORY = "directory"


class SkillPackageError(MCPError):
    """Error emitido ante anomalías o corrupción en un paquete de Skill."""

    pass


class SkillPackageSecurityError(SkillPackageError):
    """Error emitido ante intentos de path traversal, zip slip o descompresión maliciosa."""

    pass


@dataclass(frozen=True)
class SkillPackageMetadata:
    """Metadatos descriptivos e inmutables del paquete empaquetado."""

    package_name: str
    package_version: str
    archive_format: PackageFormat
    sha256_hash: str
    files_count: int
    total_size_bytes: int
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_name": self.package_name,
            "package_version": self.package_version,
            "archive_format": str(self.archive_format),
            "sha256_hash": self.sha256_hash,
            "files_count": self.files_count,
            "total_size_bytes": self.total_size_bytes,
            "created_at": self.created_at,
        }


class SkillPackage:
    """Representación formal en runtime de un paquete de Skill instalable."""

    def __init__(
        self,
        manifest: SkillManifest,
        source_path: Path,
        package_format: PackageFormat,
        metadata: SkillPackageMetadata,
        integrity_map: dict[str, str],
        signature_bytes: bytes | None = None,
        signer_id: str | None = None,
    ) -> None:
        self.manifest = manifest
        self.source_path = source_path
        self.package_format = package_format
        self.metadata = metadata
        self.integrity_map = integrity_map  # relative_path -> sha256
        self.signature_bytes = signature_bytes
        self.signer_id = signer_id

    @property
    def skill_id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def package_path(self) -> Path:
        return self.source_path

    # ── MÉTODOS DE CONSTRUCCIÓN / LECTURA ──

    @classmethod
    def from_archive(cls, archive_path: str | Path) -> SkillPackage:
        """Carga e inspecciona un paquete de Skill desde un archivo comprimido (.zip, .skpkg, .tar.gz)."""
        path = Path(archive_path).resolve()
        if not path.exists():
            raise SkillPackageError(f"El archivo del paquete no existe: '{path}'.")

        file_size = path.stat().st_size
        if file_size > MAX_PACKAGE_SIZE_BYTES:
            raise SkillPackageSecurityError(
                f"El paquete excede el tamaño máximo permitido ({file_size} > {MAX_PACKAGE_SIZE_BYTES} bytes)."
            )

        # Detectar formato
        suffix = path.name.lower()
        if suffix.endswith(".tar.gz") or suffix.endswith(".tgz"):
            pkg_format = PackageFormat.TAR_GZ
        elif suffix.endswith(".skpkg"):
            pkg_format = PackageFormat.SKPKG
        elif suffix.endswith(".zip"):
            pkg_format = PackageFormat.ZIP
        else:
            raise SkillPackageError(f"Formato de archivo no reconocido o no soportado: '{path.name}'.")

        # Calcular hash global del archivo
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        global_hash = sha256.hexdigest()

        # Inspeccionar contenido de forma segura en un directorio temporal de lectura
        try:
            with tempfile.TemporaryDirectory(prefix="jessyca_inspect_pkg_") as temp_inspect_dir:
                temp_path = Path(temp_inspect_dir)
                cls._safe_extract(path, temp_path, pkg_format)

                manifest, integrity_map, sig_bytes, signer_id, files_count, total_bytes = cls._inspect_extracted_directory(temp_path)
        except Exception as exc:
            if not isinstance(exc, (SkillPackageError, SkillPackageSecurityError)):
                raise SkillPackageError(f"Error al procesar el archivo del paquete '{path.name}': {exc}") from exc
            raise

        metadata = SkillPackageMetadata(
            package_name=manifest.name,
            package_version=manifest.version,
            archive_format=pkg_format,
            sha256_hash=global_hash,
            files_count=files_count,
            total_size_bytes=total_bytes,
        )

        return cls(
            manifest=manifest,
            source_path=path,
            package_format=pkg_format,
            metadata=metadata,
            integrity_map=integrity_map,
            signature_bytes=sig_bytes,
            signer_id=signer_id,
        )

    @classmethod
    def from_directory(cls, dir_path: str | Path) -> SkillPackage:
        """Carga e inspecciona un paquete de Skill desde un directorio fuente descomprimido."""
        path = Path(dir_path).resolve()
        if not path.exists() or not path.is_dir():
            raise SkillPackageError(f"La ruta del directorio de skill no existe o no es un directorio: '{path}'.")

        manifest, integrity_map, sig_bytes, signer_id, files_count, total_bytes = cls._inspect_extracted_directory(path)

        # Hash sintético del directorio
        h = hashlib.sha256()
        for rel_file in sorted(integrity_map.keys()):
            h.update(f"{rel_file}:{integrity_map[rel_file]}".encode())
        dir_hash = h.hexdigest()

        metadata = SkillPackageMetadata(
            package_name=manifest.name,
            package_version=manifest.version,
            archive_format=PackageFormat.DIRECTORY,
            sha256_hash=dir_hash,
            files_count=files_count,
            total_size_bytes=total_bytes,
        )

        return cls(
            manifest=manifest,
            source_path=path,
            package_format=PackageFormat.DIRECTORY,
            metadata=metadata,
            integrity_map=integrity_map,
            signature_bytes=sig_bytes,
            signer_id=signer_id,
        )

    @classmethod
    def create_bundle(
        cls,
        source_dir: str | Path,
        output_file: str | Path,
        manifest: SkillManifest,
        bundle_format: PackageFormat = PackageFormat.SKPKG,
        signature_bytes: bytes | None = None,
        signer_id: str | None = None,
    ) -> SkillPackage:
        """Crea y empaqueta formalmente un bundle de Skill comprimido (.skpkg o .zip) con mapa de integridad."""
        src = Path(source_dir).resolve()
        out = Path(output_file).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        if not src.exists() or not src.is_dir():
            raise SkillPackageError(f"El directorio fuente '{src}' no existe.")

        with tempfile.TemporaryDirectory(prefix="jessyca_bundle_stage_") as stage_temp:
            stage_dir = Path(stage_temp)

            # Copiar archivos fuente omitiendo temporales
            for root, _dirs, files in os.walk(src):
                for f in files:
                    if f.endswith((".pyc", ".pyo", ".git")) or "__pycache__" in root:
                        continue
                    full_src_file = Path(root) / f
                    rel_p = full_src_file.relative_to(src)
                    dest_f = stage_dir / rel_p
                    dest_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full_src_file, dest_f)

            # Generar/actualizar manifest.json con el manifest provisto
            manifest_file = stage_dir / "manifest.json"
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(manifest.to_dict(), mf, indent=2, ensure_ascii=False)

            # Generar integrity.json (hash SHA-256 de todos los archivos del bundle)
            integrity_map: dict[str, str] = {}
            for root, _dirs, files in os.walk(stage_dir):
                for f in files:
                    if f == "integrity.json" or f == "signature.sig":
                        continue
                    file_path = Path(root) / f
                    rel_name = file_path.relative_to(stage_dir).as_posix()
                    file_hash = cls._compute_file_sha256(file_path)
                    integrity_map[rel_name] = file_hash

            with open(stage_dir / "integrity.json", "w", encoding="utf-8") as itf:
                json.dump(integrity_map, itf, indent=2, ensure_ascii=False)

            # Escribir signature.sig si se proporciona
            if signature_bytes is not None:
                sig_data = {
                    "signer_id": signer_id or "unknown",
                    "signature_hex": signature_bytes.hex(),
                    "algorithm": "HMAC-SHA256",
                    "signed_at": datetime.now(UTC).isoformat(),
                }
                with open(stage_dir / "signature.sig", "w", encoding="utf-8") as sf:
                    json.dump(sig_data, sf, indent=2)

            # Empaquetar archivo comprimido
            if bundle_format in (PackageFormat.SKPKG, PackageFormat.ZIP):
                with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, files in os.walk(stage_dir):
                        for f in files:
                            p = Path(root) / f
                            zf.write(p, p.relative_to(stage_dir).as_posix())
            elif bundle_format == PackageFormat.TAR_GZ:
                with tarfile.open(out, "w:gz") as tf:
                    for root, _dirs, files in os.walk(stage_dir):
                        for f in files:
                            p = Path(root) / f
                            tf.add(p, arcname=p.relative_to(stage_dir).as_posix())
            else:
                raise SkillPackageError(f"Formato de bundle no soportado: '{bundle_format}'.")

        return cls.from_archive(out)

    load_bundle = from_archive

    def extract_to(self, target_directory: str | Path) -> Path:
        """Extrae de forma segura el paquete en el directorio objetivo."""
        dest = Path(target_directory).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        if self.package_format == PackageFormat.DIRECTORY:
            # Copiar contenido del directorio
            for item in self.source_path.iterdir():
                dest_item = dest / item.name
                if item.is_dir():
                    shutil.copytree(item, dest_item, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest_item)
            return dest

        self._safe_extract(self.source_path, dest, self.package_format)
        return dest

    # ── MÉTODOS PRIVADOS DE SEGURIDAD Y EXTRACCIÓN ──

    @classmethod
    def _safe_extract(cls, archive_path: Path, target_dir: Path, pkg_format: PackageFormat) -> None:
        """Extrae el archivo comprimido garantizando que ningún archivo escape del target_dir (Anti Zip-Slip)."""
        target_dir = target_dir.resolve()
        files_extracted = 0

        if pkg_format in (PackageFormat.ZIP, PackageFormat.SKPKG):
            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.infolist():
                    files_extracted += 1
                    if files_extracted > MAX_FILES_COUNT:
                        raise SkillPackageSecurityError(f"El paquete contiene demasiados archivos (> {MAX_FILES_COUNT}).")

                    member_path = (target_dir / member.filename).resolve()
                    # Comprobación de contención de ruta (Anti Path Traversal)
                    if not str(member_path).startswith(str(target_dir)):
                        raise SkillPackageSecurityError(
                            f"Intento de Path Traversal / Zip Slip detectado en miembro '{member.filename}'."
                        )
                zf.extractall(target_dir)

        elif pkg_format == PackageFormat.TAR_GZ:
            with tarfile.open(archive_path, "r:gz") as tf:
                for tar_info in tf.getmembers():
                    files_extracted += 1
                    if files_extracted > MAX_FILES_COUNT:
                        raise SkillPackageSecurityError(f"El paquete contiene demasiados archivos (> {MAX_FILES_COUNT}).")

                    member_path = (target_dir / tar_info.name).resolve()
                    if not str(member_path).startswith(str(target_dir)):
                        raise SkillPackageSecurityError(
                            f"Intento de Path Traversal / Tar Slip detectado en miembro '{tar_info.name}'."
                        )
                tf.extractall(target_dir)

    @classmethod
    def _inspect_extracted_directory(
        cls, dir_path: Path
    ) -> tuple[SkillManifest, dict[str, str], bytes | None, str | None, int, int]:
        """Inspecciona los archivos desempaquetados y construye el manifiesto y mapa de integridad."""
        manifest_path = dir_path / "manifest.json"
        if not manifest_path.exists():
            manifest_path = dir_path / "manifest.yaml"

        if not manifest_path.exists():
            raise SkillPackageError("El paquete no contiene el archivo de manifiesto obligatorio 'manifest.json'.")

        try:
            with open(manifest_path, encoding="utf-8") as mf:
                raw_data = json.load(mf)
        except Exception as exc:
            raise SkillPackageError(f"Error al parsear manifest de la skill: {exc}") from exc

        manifest = cls._parse_manifest_data(raw_data)

        # Mapa de integridad existente o generado
        integrity_map: dict[str, str] = {}
        integrity_file = dir_path / "integrity.json"
        if integrity_file.exists():
            try:
                with open(integrity_file, encoding="utf-8") as itf:
                    integrity_map = json.load(itf)
            except Exception:
                pass

        # Signature
        sig_bytes: bytes | None = None
        signer_id: str | None = None
        sig_file = dir_path / "signature.sig"
        if sig_file.exists():
            try:
                with open(sig_file, encoding="utf-8") as sf:
                    sig_info = json.load(sf)
                    sig_hex = sig_info.get("signature_hex", "")
                    if sig_hex:
                        sig_bytes = bytes.fromhex(sig_hex)
                    signer_id = sig_info.get("signer_id")
            except Exception:
                pass

        # Calcular archivos y tamaño total
        files_count = 0
        total_bytes = 0
        for root, _dirs, files in os.walk(dir_path):
            for f in files:
                files_count += 1
                fp = Path(root) / f
                total_bytes += fp.stat().st_size
                rel = fp.relative_to(dir_path).as_posix()
                if rel not in integrity_map and rel not in ("integrity.json", "signature.sig"):
                    integrity_map[rel] = cls._compute_file_sha256(fp)

        return manifest, integrity_map, sig_bytes, signer_id, files_count, total_bytes

    @classmethod
    def _parse_manifest_data(cls, raw: dict[str, Any]) -> SkillManifest:
        """Construye un SkillManifest fuertemente tipado a partir de los datos crudos."""
        risk_str = str(raw.get("risk_level", "SAFE")).upper()
        try:
            risk_level = SecurityLevel[risk_str]
        except KeyError:
            risk_level = SecurityLevel.SAFE

        return SkillManifest(
            id=str(raw.get("id") or raw.get("skill_id") or "").strip(),
            name=str(raw.get("name") or "").strip(),
            version=str(raw.get("version") or "1.0.0").strip(),
            description=str(raw.get("description") or "").strip(),
            author=str(raw.get("author") or "Community").strip(),
            capabilities=tuple(str(c) for c in raw.get("capabilities", ())),
            required_tools=tuple(str(t) for t in raw.get("required_tools", ())),
            required_agents=tuple(str(a) for a in raw.get("required_agents", ())),
            required_models=tuple(str(m) for m in raw.get("required_models", ())),
            permissions=tuple(str(p) for p in raw.get("permissions", ())),
            risk_level=risk_level,
            dependencies=dict(raw.get("dependencies", {})),
            configuration=dict(raw.get("configuration", {})),
            entrypoint=str(raw.get("entrypoint") or "main.py").strip(),
            min_system_version=str(raw.get("min_system_version") or "3.0.0").strip(),
            max_system_version=str(raw.get("max_system_version")).strip() if raw.get("max_system_version") else None,
            framework_version=str(raw.get("framework_version") or "1.0.0").strip(),
            min_framework_version=str(raw.get("min_framework_version") or "1.0.0").strip(),
            max_framework_version=str(raw.get("max_framework_version")).strip() if raw.get("max_framework_version") else None,
        )

    @staticmethod
    def _compute_file_sha256(file_path: Path) -> str:
        """Calcula el hash SHA-256 de un archivo en disco."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
