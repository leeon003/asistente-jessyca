"""Verificación y gobernanza de firmas criptográficas de Skills (skill_signature.py - Fase 32).

Proporciona la infraestructura y abstracciones necesarias para verificar la autoría y autenticidad
de paquetes de Skills antes de su instalación.

Estados formales:
- SIGNED: Paquete firmado con clave válida por un firmante de confianza registrado.
- UNSIGNED: Paquete no contiene firma digital (permitido según política de seguridad configurable).
- INVALID_SIGNATURE: Paquete firmado pero la firma no coincide con el payload (Firma corrupta/manipulada).
- UNKNOWN_SIGNER: Paquete firmado con clave válida pero el firmante no figura en la lista de confianza.

INVARIANTE DE SEGURIDAD:
Bajo ninguna circunstancia una firma inválida será tratada como válida.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.logger import get_logger
from skills.skill_package import SkillPackage

logger = get_logger("jessyca.skills.signature")


class SignatureStatus(StrEnum):
    """Estados formales del resultado de verificación de firma digital."""

    SIGNED = "SIGNED"
    UNSIGNED = "UNSIGNED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    UNKNOWN_SIGNER = "UNKNOWN_SIGNER"


@dataclass(frozen=True)
class SignatureVerificationResult:
    """Resultado formal inmutable de la verificación de firma criptográfica."""

    status: SignatureStatus
    is_valid: bool
    signer_id: str | None = None
    reason: str = ""
    algorithm: str = "HMAC-SHA256"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "is_valid": self.is_valid,
            "signer_id": self.signer_id,
            "reason": self.reason,
            "algorithm": self.algorithm,
            "details": self.details,
        }


class SkillSignatureVerifier:
    """Verificador de firmas criptográficas y almacén de firmantes confiables de JESSYCA."""

    def __init__(self, trusted_signers: dict[str, bytes] | None = None) -> None:
        # trusted_signers: {signer_id: secret_or_public_key_bytes}
        self._trusted_signers: dict[str, bytes] = (
            dict(trusted_signers)
            if trusted_signers is not None
            else {
                "jessyca_official": b"jessyca_master_signing_key_secret_2026",
                "verified_partner": b"partner_verified_signing_key_2026",
            }
        )

    def register_trusted_signer(self, signer_id: str, key_bytes: bytes) -> None:
        """Registra un firmante de confianza con su clave criptográfica asociada."""
        self._trusted_signers[signer_id] = key_bytes
        logger.info(f"[SIGNATURE TRUST STORE] Firmante de confianza '{signer_id}' registrado.")

    def revoke_trusted_signer(self, signer_id: str) -> bool:
        """Revoca un firmante de la lista de confianza."""
        if signer_id in self._trusted_signers:
            del self._trusted_signers[signer_id]
            logger.info(f"[SIGNATURE TRUST STORE] Firmante '{signer_id}' revocado.")
            return True
        return False

    def verify_package(self, package: SkillPackage, staged_dir: str | Path | None = None) -> SignatureVerificationResult:
        """Verifica la firma criptográfica del paquete de Skill."""
        sig_data: dict[str, Any] | None = None

        # 1. Intentar leer signature.sig desde staged_dir si existe
        if staged_dir:
            staged_path = Path(staged_dir).resolve()
            sig_file = staged_path / "signature.sig"
            if sig_file.exists():
                try:
                    with open(sig_file, encoding="utf-8") as sf:
                        sig_data = json.load(sf)
                except Exception as exc:
                    return SignatureVerificationResult(
                        status=SignatureStatus.INVALID_SIGNATURE,
                        is_valid=False,
                        reason=f"Archivo de firma 'signature.sig' corrupto o ilegible: {exc}",
                    )

        # 2. Si no hay archivo en staged_dir, comprobar si el paquete trae firma en memoria
        if sig_data is None and package.signature_bytes and package.signer_id:
            sig_data = {
                "signer_id": package.signer_id,
                "signature_hex": package.signature_bytes.hex(),
                "algorithm": "HMAC-SHA256",
            }

        # Si el paquete no está firmado
        if sig_data is None:
            return SignatureVerificationResult(
                status=SignatureStatus.UNSIGNED,
                is_valid=True,  # Paquetes unsigned son válidos a nivel de firma si no se exige enforce_signed
                reason="El paquete no contiene firma digital (UNSIGNED).",
            )

        signer_id = str(sig_data.get("signer_id", "")).strip()
        sig_hex = str(sig_data.get("signature_hex", "")).strip()
        algorithm = str(sig_data.get("algorithm", "HMAC-SHA256")).upper()

        if not signer_id or not sig_hex:
            return SignatureVerificationResult(
                status=SignatureStatus.INVALID_SIGNATURE,
                is_valid=False,
                signer_id=signer_id or None,
                reason="Estructura de firma digital incompleta (falta signer_id o signature_hex).",
            )

        # 3. Comprobar si el firmante está en la lista de confianza
        if signer_id not in self._trusted_signers:
            logger.warning(f"[SIGNATURE UNKNOWN SIGNER] Firmante '{signer_id}' no figura en el almacén de confianza.")
            return SignatureVerificationResult(
                status=SignatureStatus.UNKNOWN_SIGNER,
                is_valid=False,
                signer_id=signer_id,
                reason=f"El firmante '{signer_id}' no está registrado en el almacén de firmantes de confianza de JESSYCA.",
            )

        trusted_key = self._trusted_signers[signer_id]

        # 4. Calcular el payload canónico firmado (Hash canónico del manifiesto e integridad)
        canonical_payload = self._compute_canonical_payload(package, staged_dir)

        # 5. Verificar firma HMAC-SHA256
        expected_sig = hmac.new(trusted_key, canonical_payload, hashlib.sha256).hexdigest()

        if hmac.compare_digest(expected_sig.lower(), sig_hex.lower()):
            logger.info(f"[SIGNATURE VERIFIED] Firma válida comprobada para '{package.skill_id}' por '{signer_id}'.")
            return SignatureVerificationResult(
                status=SignatureStatus.SIGNED,
                is_valid=True,
                signer_id=signer_id,
                reason=f"Firma digital válida emitida por el firmante de confianza '{signer_id}'.",
                algorithm=algorithm,
            )

        logger.warning(
            f"[SIGNATURE TAMPERED] Firma inválida para '{package.skill_id}'. Esperado={expected_sig}, Obtenido={sig_hex}"
        )
        return SignatureVerificationResult(
            status=SignatureStatus.INVALID_SIGNATURE,
            is_valid=False,
            signer_id=signer_id,
            reason="La firma criptográfica no coincide con el contenido del paquete (Firma manipulada o inválida).",
            algorithm=algorithm,
        )

    @staticmethod
    def sign_payload(signer_id: str, secret_key: bytes, package: SkillPackage, staged_dir: str | Path | None = None) -> dict[str, Any]:
        """Firma criptográficamente el paquete generando el descriptor signature.sig."""
        canonical = SkillSignatureVerifier._compute_canonical_payload(package, staged_dir)
        sig_hex = hmac.new(secret_key, canonical, hashlib.sha256).hexdigest()
        return {
            "signer_id": signer_id,
            "signature_hex": sig_hex,
            "algorithm": "HMAC-SHA256",
        }

    @staticmethod
    def _compute_canonical_payload(package: SkillPackage, staged_dir: str | Path | None = None) -> bytes:
        """Genera una representación canónica y determinista de los hashes y manifiesto del paquete."""
        h = hashlib.sha256()

        # Incluir datos clave del manifiesto
        m = package.manifest
        h.update(f"ID:{m.id}|NAME:{m.name}|VER:{m.version}|AUTH:{m.author}|ENTRY:{m.entrypoint}|RISK:{m.risk_level}".encode())

        # Incluir mapa de integridad ordenado
        for rel_file in sorted(package.integrity_map.keys()):
            if rel_file not in ("signature.sig", "integrity.json"):
                h.update(f"{rel_file}:{package.integrity_map[rel_file]}".encode())

        return h.digest()
