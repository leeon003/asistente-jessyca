"""core/mobile/models.py

Modelos formales para la capacidad Mobile Control de JESSYCA.
Define identidades de dispositivo, emparejamiento, estados de ejecución y evidencias verificadas.
"""

from __future__ import annotations

import enum
import time
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class PairingStatus(str, enum.Enum):
    """Estado del emparejamiento explícito del dispositivo."""
    UNPAIRED = "UNPAIRED"
    PAIRING_REQUESTED = "PAIRING_REQUESTED"
    PAIRED = "PAIRED"
    REVOKED = "REVOKED"


class AuthorizationStatus(str, enum.Enum):
    """Estado de autorización de seguridad del dispositivo móvil."""
    UNAUTHORIZED = "UNAUTHORIZED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"


class MobileTransportType(str, enum.Enum):
    """Tipo de transporte físico o de red hacia el dispositivo."""
    USB = "usb"
    WIFI_TLS = "wifi_tls"
    EMULATOR = "emulator"
    VIRTUAL_TEST = "virtual_test"


class MobileDeviceIdentity(BaseModel):
    """Identidad formally auditada de un dispositivo móvil en JESSYCA."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(..., description="Identificador único del dispositivo (ej. android-pixel-8)")
    device_name: str = Field(..., description="Nombre amigable del dispositivo (ej. Google Pixel 8 Pro)")
    platform: str = Field("android", description="Plataforma del SO móvil")
    transport: MobileTransportType = Field(MobileTransportType.USB, description="Tipo de transporte de conexión")
    pairing_status: PairingStatus = Field(PairingStatus.UNPAIRED, description="Estado de emparejamiento explícito")
    authorization_status: AuthorizationStatus = Field(
        AuthorizationStatus.UNAUTHORIZED, description="Estado de autorización"
    )
    pairing_secret_hash: str = Field(..., description="Hash SHA-256 del secreto/token de emparejamiento")
    host: str | None = Field(default=None, description="Host de red para conexión Wi-Fi TLS")
    port: int | None = Field(default=None, description="Puerto de red para conexión Wi-Fi TLS")
    authorized_at: float | None = Field(default=None, description="Marca temporal de autorización")
    declared_capabilities: tuple[str, ...] = Field(
        default_factory=tuple, description="Capacidades explícitamente permitidas"
    )


class MobileDeviceState(BaseModel):
    """Estado en vivo del dispositivo móvil."""

    model_config = ConfigDict(extra="ignore")

    device_id: str
    is_connected: bool = True
    battery_level: int | None = Field(default=None, ge=0, le=100)
    foreground_package: str | None = None
    foreground_activity: str | None = None
    screen_on: bool = True
    is_locked: bool = False
    last_seen: float = Field(default_factory=time.time)
    details: dict[str, Any] = Field(default_factory=dict)


class MobileActionEvidence(BaseModel):
    """Evidencia forense inmutable de una acción física ejecutada en el dispositivo móvil."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str
    action_name: str
    target_package: str
    is_verified: bool
    observed_foreground_package: str | None
    observed_foreground_activity: str | None
    evidence_hash: str
    timestamp: float = Field(default_factory=time.time)
    duration_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class MobileExecutionResult(BaseModel):
    """Resultado formal de una operación móvil gobernada por JDE.

    Tipo propio del orquestador móvil — no reutiliza DecisionResult de JDE
    porque este tiene campos y validadores rígidos incompatibles con la
    semántica de control remoto de dispositivos.
    """

    model_config = ConfigDict(extra="forbid")

    final_status: str  # SUCCESS, FAILED, DENIED, VERIFICATION_FAILED
    action_name: str = "mobile.launch_app"
    receipt: Any = None  # ActionReceipt cuando esté disponible
    evidence: Any = None  # JDEEvidence cuando esté disponible
    reason: str = ""
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convierte el resultado a diccionario serializable."""
        return self.model_dump()

