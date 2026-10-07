"""core/mobile/__init__.py

Módulo de Control y Automatización Móvil de JESSYCA subordinado a JDE (Need A & Need B).
Exporta modelos de identidad, emparejamiento, driver determinista (Mobilewright),
verificador físico y adaptador de integración canónico.
"""

from __future__ import annotations

from core.mobile.adapter import MobileControlAdapter
from core.mobile.driver import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    MobileDriverError,
    MobilewrightDriver,
    OperationCancelledError,
    TimeoutExceededError,
)
from core.mobile.models import (
    AuthorizationStatus,
    MobileActionEvidence,
    MobileDeviceIdentity,
    MobileDeviceState,
    MobileTransportType,
    PairingStatus,
)
from core.mobile.orchestrator import (
    DeviceNotAuthorizedError,
    MobileOrchestrator,
    MobileSecurityError,
)
from core.mobile.pairing import (
    DevicePairingError,
    DevicePairingManager,
    InsecureTokenError,
    InvalidCertificateError,
)
from core.mobile.verifier import MobileAppForegroundVerifier

__all__ = [
    # Modelos y Enums
    "PairingStatus",
    "AuthorizationStatus",
    "MobileTransportType",
    "MobileDeviceIdentity",
    "MobileDeviceState",
    "MobileActionEvidence",
    # Emparejamiento y Seguridad
    "DevicePairingManager",
    "DevicePairingError",
    "InsecureTokenError",
    "InvalidCertificateError",
    # Driver de Automatización
    "MobilewrightDriver",
    "MobileDriverError",
    "DeviceNotFoundError",
    "DeviceDisconnectedError",
    "OperationCancelledError",
    "TimeoutExceededError",
    # Verificación Física
    "MobileAppForegroundVerifier",
    # Orquestador y Adaptador
    "MobileOrchestrator",
    "MobileControlAdapter",
    "MobileSecurityError",
    "DeviceNotAuthorizedError",
]
