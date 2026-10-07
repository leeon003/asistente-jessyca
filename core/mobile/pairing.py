"""core/mobile/pairing.py

Gestor de Emparejamiento Explícito y Transporte Autenticado para Dispositivos Móviles.
Garantiza:
1. Emparejamiento explícito con handshake y tokens criptográficos.
2. Rechazo categórico de tokens inseguros de desarrollo ("jessyca-dev-token-insecure").
3. Transporte seguro: exige cifrado y validación estricta de certificados TLS para conexiones de red.
4. Persistencia segregada de identidades autorizadas en data_dir.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from core.distribution.paths import get_paths
from core.logger import get_logger
from core.mobile.models import (
    AuthorizationStatus,
    MobileDeviceIdentity,
    MobileTransportType,
    PairingStatus,
)

logger = get_logger("jessyca.mobile.pairing")

INSECURE_DEV_TOKENS = frozenset({
    "jessyca-dev-token-insecure",
    "123456",
    "password",
    "default-token",
})


class DevicePairingError(Exception):
    """Error base de emparejamiento y autenticación de dispositivos móviles."""
    pass


class InsecureTokenError(DevicePairingError):
    """Error emitido cuando se intenta usar un token de desarrollo inseguro o débil."""
    pass


class InvalidCertificateError(DevicePairingError):
    """Error emitido cuando no se valida adecuadamente la seguridad o certificado del transporte."""
    pass


class DevicePairingManager:
    """Administrador thread-safe de emparejamiento explícito de dispositivos móviles."""

    def __init__(self, storage_file: Path | str | None = None) -> None:
        paths = get_paths()
        self.storage_file = Path(storage_file) if storage_file else paths.data_dir / "mobile_paired_devices.json"
        self._devices: dict[str, MobileDeviceIdentity] = {}
        self._lock = threading.RLock()
        self._load_from_disk()

    @staticmethod
    def hash_secret(secret: str) -> str:
        """Calcula el hash SHA-256 de un secreto de emparejamiento."""
        return hashlib.sha256(secret.strip().encode("utf-8")).hexdigest()

    def generate_pairing_token(self) -> str:
        """Genera un token seguro y robusto de 64 caracteres hexadecimales."""
        return secrets.token_hex(32)

    def register_device(
        self,
        device_id: str,
        device_name: str,
        pairing_secret: str,
        transport: MobileTransportType = MobileTransportType.USB,
        host: str | None = None,
        port: int | None = None,
        declared_capabilities: tuple[str, ...] = (
            "mobile.list_authorized_devices",
            "mobile.get_device_status",
            "mobile.launch_app",
            "mobile.verify_foreground",
        ),
        verify_certificates: bool = True,
    ) -> MobileDeviceIdentity:
        """Registra y empareja un dispositivo mediante validación explícita."""
        with self._lock:
            cleaned_id = device_id.strip()
            if not cleaned_id:
                raise DevicePairingError("El device_id no puede estar vacío.")

            cleaned_secret = pairing_secret.strip()
            if not cleaned_secret:
                raise DevicePairingError("El secreto de emparejamiento no puede estar vacío.")

            # Validación de tokens inseguros
            if cleaned_secret.lower() in INSECURE_DEV_TOKENS or len(cleaned_secret) < 16:
                raise InsecureTokenError(
                    f"El token proporcionado ('{cleaned_secret[:8]}...') es un token inseguro o demasiado corto. "
                    "Se requiere un secreto criptográfico de al menos 16 caracteres."
                )

            # Validación de transporte seguro en red
            if transport == MobileTransportType.WIFI_TLS:
                if not host:
                    raise DevicePairingError("El transporte WIFI_TLS requiere un host válido.")
                if not verify_certificates:
                    raise InvalidCertificateError(
                        "Por política de seguridad de JESSYCA, está estrictamente prohibido desactivar la "
                        "validación de certificados TLS en comunicaciones móviles por red."
                    )

            identity = MobileDeviceIdentity(
                device_id=cleaned_id,
                device_name=device_name.strip(),
                platform="android",
                transport=transport,
                pairing_status=PairingStatus.PAIRED,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                pairing_secret_hash=self.hash_secret(cleaned_secret),
                host=host,
                port=port,
                authorized_at=time.time(),
                declared_capabilities=declared_capabilities,
            )

            self._devices[cleaned_id] = identity
            self._save_to_disk()
            logger.info(f"[MOBILE PAIRING] Dispositivo '{cleaned_id}' ({device_name}) emparejado y autorizado.")
            return identity

    def authorize_device(self, device_id: str) -> bool:
        """Autoriza un dispositivo previamente registrado."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return False

            updated = MobileDeviceIdentity(
                device_id=dev.device_id,
                device_name=dev.device_name,
                platform=dev.platform,
                transport=dev.transport,
                pairing_status=PairingStatus.PAIRED,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                pairing_secret_hash=dev.pairing_secret_hash,
                host=dev.host,
                port=dev.port,
                authorized_at=time.time(),
                declared_capabilities=dev.declared_capabilities,
            )
            self._devices[device_id] = updated
            self._save_to_disk()
            return True

    def revoke_device(self, device_id: str) -> bool:
        """Revoca la autorización de un dispositivo."""
        with self._lock:
            dev = self._devices.get(device_id)
            if not dev:
                return False

            updated = MobileDeviceIdentity(
                device_id=dev.device_id,
                device_name=dev.device_name,
                platform=dev.platform,
                transport=dev.transport,
                pairing_status=PairingStatus.REVOKED,
                authorization_status=AuthorizationStatus.BLOCKED,
                pairing_secret_hash=dev.pairing_secret_hash,
                host=dev.host,
                port=dev.port,
                authorized_at=None,
                declared_capabilities=dev.declared_capabilities,
            )
            self._devices[device_id] = updated
            self._save_to_disk()
            logger.warning(f"[MOBILE PAIRING] Dispositivo '{device_id}' revocado.")
            return True

    def get_device(self, device_id: str) -> MobileDeviceIdentity | None:
        """Obtiene la identidad registrada de un dispositivo."""
        with self._lock:
            return self._devices.get(device_id)

    def list_authorized_devices(self) -> list[MobileDeviceIdentity]:
        """Devuelve únicamente los dispositivos debidamente emparejados y autorizados."""
        with self._lock:
            return [
                dev for dev in self._devices.values()
                if dev.pairing_status == PairingStatus.PAIRED
                and dev.authorization_status == AuthorizationStatus.AUTHORIZED
            ]

    def verify_credentials(self, device_id: str, provided_secret: str) -> bool:
        """Verifica criptográficamente el token presentado por el dispositivo."""
        with self._lock:
            dev = self.get_device(device_id)
            if not dev or dev.authorization_status != AuthorizationStatus.AUTHORIZED:
                return False
            expected_hash = dev.pairing_secret_hash
            actual_hash = self.hash_secret(provided_secret)
            return secrets.compare_digest(expected_hash, actual_hash)

    def _save_to_disk(self) -> None:
        try:
            self.storage_file.parent.mkdir(parents=True, exist_ok=True)
            data = {dev_id: dev.model_dump() for dev_id, dev in self._devices.items()}
            self.storage_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[MOBILE PAIRING] Error guardando registro de dispositivos: {e}")

    def _load_from_disk(self) -> None:
        if not self.storage_file.exists():
            return
        try:
            content = self.storage_file.read_text(encoding="utf-8")
            raw_data: dict[str, Any] = json.loads(content)
            for dev_id, dev_dict in raw_data.items():
                self._devices[dev_id] = MobileDeviceIdentity.model_validate(dev_dict)
        except Exception as e:
            logger.warning(f"[MOBILE PAIRING] No se pudo cargar registro previo de dispositivos: {e}")
