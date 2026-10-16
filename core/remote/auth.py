"""Módulo de autenticación, autorización y seguridad para WhatsApp Personal (Fase 6).

Implementa:
- Verificación criptográfica de identidad del propietario y dispositivo.
- Protección estricta contra repeticiones (Anti-Replay con nonce y ventana de tiempo).
- Control de tasa de solicitudes (Rate Limiting).
- Desafíos de confirmación adicional (2FA / OTP de 6 dígitos) para operaciones sensibles.
- Sanitización de registros para prevenir fuga de credenciales o secretos.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger
from core.remote.models import RemoteMessage

logger = get_logger("jessyca.remote.auth")


@dataclass
class PendingChallenge:
    """Desafío de confirmación temporal para acciones sensibles."""

    command_id: str
    command_type: str
    code: str
    expires_at: float
    attempts_remaining: int = 3


class OwnerAuthManager:
    """Administrador soberano de autenticación para el canal remoto del propietario."""

    def __init__(
        self,
        owner_phone_jid: str | None = None,
        authorized_device_ids: set[str] | None = None,
        shared_secret: str | None = None,
        max_age_seconds: float = 60.0,
        rate_limit_per_minute: int = 10,
    ) -> None:
        self.owner_phone_jid = (
            owner_phone_jid
            or os.getenv("JESSYCA_OWNER_PHONE_JID", "51999999999@s.whatsapp.net")
        ).strip().lower()
        
        env_devices = os.getenv("JESSYCA_AUTHORIZED_DEVICES", "owner-primary-phone")
        self.authorized_device_ids = authorized_device_ids or set(
            d.strip() for d in env_devices.split(",") if d.strip()
        )
        
        raw_secret = shared_secret or os.getenv("JESSYCA_REMOTE_SHARED_SECRET", "jessyca-personal-default-secret-2026")
        self._shared_secret = raw_secret.encode("utf-8")

        self.max_age_seconds = max_age_seconds
        self.rate_limit_per_minute = rate_limit_per_minute

        # Cache de nonces con expiración: {nonce: expire_timestamp}
        self._seen_nonces: dict[str, float] = {}

        # Historial de solicitudes para Rate Limiting: {sender: [timestamp, ...]}
        self._request_history: dict[str, list[float]] = collections.defaultdict(list)

        # Desafíos pendientes de confirmación: {command_id: PendingChallenge}
        self._pending_challenges: dict[str, PendingChallenge] = {}

    @staticmethod
    def _normalize_jid(jid: str) -> str:
        """Normaliza el identificador de WhatsApp eliminando caracteres espurios."""
        clean = re.sub(r"[^\w@.-]", "", jid.strip().lower())
        if not clean.endswith("@s.whatsapp.net") and not clean.endswith("@c.us"):
            digits = re.sub(r"\D", "", clean)
            clean = f"{digits}@s.whatsapp.net"
        return clean

    def verify_sender(self, sender_phone_jid: str, device_id: str) -> tuple[bool, str]:
        """Verifica que el remitente y dispositivo correspondan al propietario autorizado."""
        if not sender_phone_jid or not device_id:
            return False, "Remitente o identificador de dispositivo ausente."

        normalized_sender = self._normalize_jid(sender_phone_jid)
        expected_owner = self._normalize_jid(self.owner_phone_jid)

        if normalized_sender != expected_owner:
            logger.warning(
                f"[AUTH_REJECT] Remitente no autorizado intentó acceder: {self.sanitize_log(sender_phone_jid)}"
            )
            return False, "Remitente no autorizado. Acceso denegado."

        if device_id not in self.authorized_device_ids:
            logger.warning(
                f"[AUTH_REJECT] Dispositivo '{device_id}' no registrado en lista blanca."
            )
            return False, "Dispositivo no reconocido o no autorizado."

        return True, "Identidad y dispositivo verificados."

    def verify_anti_replay(self, nonce: str, timestamp: float) -> tuple[bool, str]:
        """Protección estricta contra repeticiones (Anti-Replay)."""
        now = time.time()
        self._cleanup_expired_nonces(now)

        # 1. Comprobación de ventana de expiración
        if abs(now - timestamp) > self.max_age_seconds:
            logger.warning(
                f"[REPLAY_REJECT] Mensaje fuera de ventana temporal: delta={abs(now - timestamp):.2f}s"
            )
            return False, f"Mensaje expirado. Desviación temporal excede {self.max_age_seconds}s."

        # 2. Comprobación de unicidad de Nonce
        if not nonce or len(nonce) < 8:
            return False, "Nonce inválido o insuficiente."

        if nonce in self._seen_nonces:
            logger.error(f"[REPLAY_ATTACK] Nonce duplicado detectado: {nonce}")
            return False, "Ataque de repetición detectado (Nonce ya utilizado)."

        self._seen_nonces[nonce] = now + self.max_age_seconds
        return True, "Nonce y ventana temporal válidos."

    def sign_message(self, message: RemoteMessage) -> str:
        """Calcula la firma HMAC-SHA256 para un mensaje."""
        canonical = message.canonical_bytes_for_signing()
        return hmac.new(self._shared_secret, canonical, hashlib.sha256).hexdigest()

    def verify_signature(self, message: RemoteMessage) -> tuple[bool, str]:
        """Verifica la firma criptográfica HMAC-SHA256 del mensaje."""
        if not message.signature:
            return False, "Firma criptográfica ausente en el mensaje."

        expected_sig = self.sign_message(message)
        if not hmac.compare_digest(message.signature, expected_sig):
            logger.error("[INTEGRITY_FAIL] Firma HMAC-SHA256 inválida o mensaje alterado.")
            return False, "Firma digital inválida. Integridad no garantizada."

        return True, "Firma digital verificada correctamente."

    def check_rate_limit(self, sender_phone_jid: str) -> tuple[bool, str]:
        """Aplica limitación de tasa por ventana deslizante (Rate Limiting)."""
        now = time.time()
        key = self._normalize_jid(sender_phone_jid)
        window = 60.0

        timestamps = self._request_history[key]
        # Filtrar timestamps mayores al umbral
        valid_timestamps = [t for t in timestamps if now - t < window]
        self._request_history[key] = valid_timestamps

        if len(valid_timestamps) >= self.rate_limit_per_minute:
            logger.warning(
                f"[RATE_LIMIT] Tasa excedida para {self.sanitize_log(sender_phone_jid)}: {len(valid_timestamps)} req/min"
            )
            return False, f"Límite de solicitudes alcanzado (máximo {self.rate_limit_per_minute} por minuto). Intenta más tarde."

        self._request_history[key].append(now)
        return True, "Tasa dentro de límites permitidos."

    def create_confirmation_challenge(
        self, command_id: str, command_type: str, ttl_seconds: float = 120.0
    ) -> tuple[str, str]:
        """Genera un desafío criptográfico OTP de 6 dígitos para operaciones sensibles."""
        code = f"{secrets.randbelow(900000) + 100000}"
        now = time.time()
        challenge = PendingChallenge(
            command_id=command_id,
            command_type=command_type,
            code=code,
            expires_at=now + ttl_seconds,
            attempts_remaining=3,
        )
        self._pending_challenges[command_id] = challenge
        prompt = (
            f"⚠️ Confirmación Requerida para: *{command_type}*.\n"
            f"Tu código de autorización es: *{code}* (válido por {int(ttl_seconds)}s).\n"
            f"Responde con: *CONFIRMAR {code}*"
        )
        return code, prompt

    def verify_confirmation_challenge(
        self, command_id: str, provided_code: str
    ) -> tuple[bool, str]:
        """Verifica y consume un código de confirmación temporal."""
        now = time.time()
        challenge = self._pending_challenges.get(command_id)
        if not challenge:
            return False, "No existe un desafío de confirmación pendiente para esta operación."

        if now > challenge.expires_at:
            del self._pending_challenges[command_id]
            return False, "El código de confirmación ha expirado."

        if challenge.attempts_remaining <= 0:
            del self._pending_challenges[command_id]
            return False, "Intentos agotados. La operación ha sido cancelada por seguridad."

        challenge.attempts_remaining -= 1

        if not hmac.compare_digest(challenge.code.strip(), provided_code.strip()):
            return False, f"Código incorrecto. Te quedan {challenge.attempts_remaining} intentos."

        # Código válido: consumir desafío inmediatamente
        del self._pending_challenges[command_id]
        return True, "Operación autorizada y confirmada exitosamente."

    def _cleanup_expired_nonces(self, now: float) -> None:
        """Purga los nonces expirados de la memoria."""
        expired = [nonce for nonce, exp in self._seen_nonces.items() if exp < now]
        for nonce in expired:
            del self._seen_nonces[nonce]

    @staticmethod
    def sanitize_log(value: Any) -> str:
        """Enmascara datos confidenciales (teléfonos, tokens, firmas) para logs."""
        text = str(value)
        # Enmascarar números de teléfono largos
        text = re.sub(r"(\+?\d{2,4})\d{4,6}(\d{3,4})", r"\1***\2", text)
        # Enmascarar firmas y tokens hex
        text = re.sub(r"\b[0-9a-fA-F]{32,64}\b", "[REDACTED_HASH]", text)
        return text
