"""Distribución e Instalación Segura de Skills (skill_distribution.py - Fase 46).

Implementa la cadena de confianza para extensiones y habilidades:
Source -> Version Compatibility -> Integrity (SHA-256) -> Permissions Review -> Static Security Analysis -> Install.

PRINCIPIO DE SEGURIDAD INMUTABLE:
Marketplace != Trust. Toda Skill externa es tratada como código no confiable hasta su validación criptográfica y de sandbox.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from core.logger import get_logger

logger = get_logger("jessyca.distribution.skills")

# Patrones de código peligroso para análisis estático
SUSPICIOUS_PATTERNS = [
    re.compile(r"\b(eval|exec)\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.system\s*\(", re.IGNORECASE),
    re.compile(r"\bsubprocess\.(Popen|call|run)\s*\(", re.IGNORECASE),
    re.compile(r"__import__\s*\(", re.IGNORECASE),
    re.compile(r"ctypes\.windll", re.IGNORECASE),
]


@dataclass(frozen=True)
class SkillPackageMetadata:
    """Metadatos de empaquetado de una Skill."""

    skill_id: str
    version: str
    author: str
    description: str
    required_permissions: tuple[str, ...]
    checksum_sha256: str
    min_jessyca_version: str = "3.0.0"
    source_url: str = ""
    is_signed: bool = True


@dataclass
class SkillVerificationResult:
    """Resultado de la verificación de seguridad e integridad de una Skill."""

    skill_id: str
    is_approved: bool
    integrity_valid: bool
    compatibility_valid: bool
    permissions_approved: bool
    security_clean: bool
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class SkillDistributionManager:
    """Administrador de distribución, validación e instalación de Skills."""

    def __init__(self, skills_install_dir: str | Path) -> None:
        self.install_dir = Path(skills_install_dir)
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self._installed_manifests: dict[str, SkillPackageMetadata] = {}
        self._lock = threading.RLock()

    def verify_skill_package(
        self,
        package_file: Path,
        metadata: SkillPackageMetadata,
        jessyca_version: str = "3.0.0",
    ) -> SkillVerificationResult:
        """Aplica la cadena completa de validación de seguridad a un paquete de Skill."""
        # 1. Integridad SHA-256
        if not package_file.exists():
            return SkillVerificationResult(
                skill_id=metadata.skill_id,
                is_approved=False,
                integrity_valid=False,
                compatibility_valid=False,
                permissions_approved=False,
                security_clean=False,
                rejection_reason="Archivo de paquete no encontrado.",
            )

        computed_sha = self._compute_file_sha256(package_file)
        if computed_sha != metadata.checksum_sha256:
            return SkillVerificationResult(
                skill_id=metadata.skill_id,
                is_approved=False,
                integrity_valid=False,
                compatibility_valid=False,
                permissions_approved=False,
                security_clean=False,
                rejection_reason=f"Integridad comprometida: SHA-256 '{computed_sha[:8]}' != '{metadata.checksum_sha256[:8]}'.",
            )

        # 2. Compatibilidad de versión
        # Si min_jessyca_version > jessyca_version -> Incompatible
        if metadata.min_jessyca_version > jessyca_version:
            return SkillVerificationResult(
                skill_id=metadata.skill_id,
                is_approved=False,
                integrity_valid=True,
                compatibility_valid=False,
                permissions_approved=False,
                security_clean=False,
                rejection_reason=f"Skill requiere JESSYCA >= {metadata.min_jessyca_version} (actual: {jessyca_version}).",
            )

        # 3. Revisión de Permisos
        # Prohibir permisos comodín o peligrosos no declarados
        if "*" in metadata.required_permissions or "system.admin" in metadata.required_permissions:
            return SkillVerificationResult(
                skill_id=metadata.skill_id,
                is_approved=False,
                integrity_valid=True,
                compatibility_valid=True,
                permissions_approved=False,
                security_clean=False,
                rejection_reason="Permisos solicitados excesivos o prohibidos (* o system.admin).",
            )

        # 4. Análisis estático de seguridad sobre el código fuente
        is_clean, issues = self._static_security_scan(package_file)
        if not is_clean:
            return SkillVerificationResult(
                skill_id=metadata.skill_id,
                is_approved=False,
                integrity_valid=True,
                compatibility_valid=True,
                permissions_approved=True,
                security_clean=False,
                rejection_reason=f"Amenazas de seguridad detectadas: {'; '.join(issues)}",
            )

        return SkillVerificationResult(
            skill_id=metadata.skill_id,
            is_approved=True,
            integrity_valid=True,
            compatibility_valid=True,
            permissions_approved=True,
            security_clean=True,
        )

    def install_skill(
        self,
        package_file: Path,
        metadata: SkillPackageMetadata,
        jessyca_version: str = "3.0.0",
    ) -> tuple[bool, str | None]:
        """Instala la Skill tras superar la verificación estricta de seguridad."""
        with self._lock:
            verif = self.verify_skill_package(package_file, metadata, jessyca_version)
            if not verif.is_approved:
                logger.warning(f"[SKILL INSTALL REJECTED] {metadata.skill_id}: {verif.rejection_reason}")
                return False, verif.rejection_reason

            try:
                dest = self.install_dir / f"{metadata.skill_id}_{metadata.version}.py"
                with open(package_file, "rb") as sf, open(dest, "wb") as df:
                    df.write(sf.read())

                self._installed_manifests[metadata.skill_id] = metadata
                logger.info(f"[SKILL INSTALLED] Skill '{metadata.skill_id}@{metadata.version}' instalada con éxito.")
                return True, None
            except Exception as ex:
                logger.error(f"[SKILL INSTALL ERROR] {ex}")
                return False, str(ex)

    def _compute_file_sha256(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _static_security_scan(self, file_path: Path) -> tuple[bool, list[str]]:
        """Escanea el archivo en busca de patrones maliciosos o llamadas peligrosas."""
        issues = []
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            for pattern in SUSPICIOUS_PATTERNS:
                if pattern.search(content):
                    issues.append(f"Patrón de ejecución no permitido detectado: '{pattern.pattern}'")

            return len(issues) == 0, issues
        except Exception as ex:
            return False, [f"Error leyendo archivo para análisis estático: {ex}"]
