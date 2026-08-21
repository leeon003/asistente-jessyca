"""Verificador de integridad criptográfica de paquetes de Skills (skill_integrity.py - Fase 32).

Verifica que el contenido del paquete desempaquetado coincida con los hashes SHA-256 declarados,
detectando archivos modificados, corruptos, incompletos, manifiestos alterados o archivos no autorizados.

INVARIANTES DE SEGURIDAD:
1. No se confía únicamente en nombres o tamaños de archivo; se verifica el hash SHA-256 íntegro.
2. Archivos adicionales no declarados en el mapa de integridad causan rechazo inmediato (ANTI-PAYLOAD-INJECTION).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import get_logger
from skills.skill_package import SkillPackage

logger = get_logger("jessyca.skills.integrity")


@dataclass(frozen=True)
class IntegrityVerificationResult:
    """Resultado formal inmutable de la verificación de integridad de un paquete."""

    is_valid: bool
    reason: str
    verified_files: tuple[str, ...] = ()
    corrupted_files: tuple[str, ...] = ()
    missing_files: tuple[str, ...] = ()
    unexpected_files: tuple[str, ...] = ()
    manifest_tampered: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "reason": self.reason,
            "verified_files": list(self.verified_files),
            "corrupted_files": list(self.corrupted_files),
            "missing_files": list(self.missing_files),
            "unexpected_files": list(self.unexpected_files),
            "manifest_tampered": self.manifest_tampered,
            "details": self.details,
        }


class SkillIntegrityVerifier:
    """Verificador estricto de integridad para paquetes de Skills."""

    @classmethod
    def verify_package(cls, package: SkillPackage, staged_dir: str | Path | None = None) -> IntegrityVerificationResult:
        """Verifica la integridad del paquete contra su mapa de integridad SHA-256."""
        target_dir = Path(staged_dir).resolve() if staged_dir else None

        if target_dir is None:
            # Si no hay staged_dir, verificar el mapa de integridad interno del paquete
            if not package.integrity_map:
                return IntegrityVerificationResult(
                    is_valid=False,
                    reason="El paquete no contiene un mapa de integridad (integrity.json ausente o vacío).",
                )
            return IntegrityVerificationResult(
                is_valid=True,
                reason="Mapa de integridad interno válido.",
                verified_files=tuple(package.integrity_map.keys()),
            )

        # 1. Verificar existencia del directorio staged
        if not target_dir.exists() or not target_dir.is_dir():
            return IntegrityVerificationResult(
                is_valid=False,
                reason=f"El directorio staged '{target_dir}' no existe o no es accesible.",
            )

        declared_map = dict(package.integrity_map)

        # Si el staged_dir contiene un integrity.json explícito, cargarlo para contrastar
        staged_integrity_file = target_dir / "integrity.json"
        if staged_integrity_file.exists():
            try:
                with open(staged_integrity_file, encoding="utf-8") as integrity_fh:
                    file_decl = json.load(integrity_fh)
                    if isinstance(file_decl, dict):
                        # Merge o verificación cruzada
                        if declared_map and file_decl != declared_map:
                            return IntegrityVerificationResult(
                                is_valid=False,
                                reason="Discrepancia crítica entre el mapa de integridad del paquete y el archivo integrity.json en disco.",
                                manifest_tampered=True,
                            )
                        declared_map = file_decl
            except Exception as exc:
                return IntegrityVerificationResult(
                    is_valid=False,
                    reason=f"Error al leer integrity.json en directorio staged: {exc}",
                )

        if not declared_map:
            return IntegrityVerificationResult(
                is_valid=False,
                reason="El paquete carece de mapa de integridad declarado.",
            )

        # 2. Escanear todos los archivos presentes en el staging
        actual_files_map: dict[str, str] = {}
        for root, _dirs, file_names in os.walk(target_dir):
            for fname in file_names:
                if fname in ("integrity.json", "signature.sig"):
                    continue
                fp = Path(root) / fname
                rel_path = fp.relative_to(target_dir).as_posix()
                actual_files_map[rel_path] = cls._compute_file_hash(fp)

        # 3. Comprobar archivos faltantes y corruptos
        verified: list[str] = []
        corrupted: list[str] = []
        missing: list[str] = []
        unexpected: list[str] = []

        for expected_rel, expected_hash in declared_map.items():
            if expected_rel in ("integrity.json", "signature.sig"):
                continue
            if expected_rel not in actual_files_map:
                missing.append(expected_rel)
            else:
                actual_hash = actual_files_map[expected_rel]
                if actual_hash.lower() == expected_hash.lower():
                    verified.append(expected_rel)
                else:
                    corrupted.append(expected_rel)
                    logger.warning(
                        f"[INTEGRITY CORRUPTED FILE] '{expected_rel}': esperado={expected_hash}, obtenido={actual_hash}"
                    )

        # 4. Comprobar archivos adicionales inesperados (Anti-Trojan / Payload Injection)
        for actual_rel in actual_files_map:
            if actual_rel not in declared_map and actual_rel not in ("integrity.json", "signature.sig"):
                unexpected.append(actual_rel)
                logger.warning(f"[INTEGRITY UNEXPECTED FILE] Archivo no declarado detectado: '{actual_rel}'")

        # 5. Comprobar alteración específica de manifest.json
        manifest_tampered = "manifest.json" in corrupted or "manifest.json" in missing

        if corrupted:
            return IntegrityVerificationResult(
                is_valid=False,
                reason=f"Se detectaron archivos corruptos o modificados: {corrupted}.",
                verified_files=tuple(verified),
                corrupted_files=tuple(corrupted),
                missing_files=tuple(missing),
                unexpected_files=tuple(unexpected),
                manifest_tampered=manifest_tampered,
            )

        if missing:
            return IntegrityVerificationResult(
                is_valid=False,
                reason=f"Paquete incompleto. Faltan archivos requeridos: {missing}.",
                verified_files=tuple(verified),
                corrupted_files=tuple(corrupted),
                missing_files=tuple(missing),
                unexpected_files=tuple(unexpected),
                manifest_tampered=manifest_tampered,
            )

        if unexpected:
            return IntegrityVerificationResult(
                is_valid=False,
                reason=f"Se detectaron archivos adicionales inesperados no declarados: {unexpected}.",
                verified_files=tuple(verified),
                corrupted_files=tuple(corrupted),
                missing_files=tuple(missing),
                unexpected_files=tuple(unexpected),
                manifest_tampered=manifest_tampered,
            )

        return IntegrityVerificationResult(
            is_valid=True,
            reason="Verificación de integridad criptográfica superada con éxito (100% hashes coincidentes).",
            verified_files=tuple(verified),
        )

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """Calcula el hash SHA-256 del archivo especificado."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
