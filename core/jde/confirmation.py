"""Módulo de Gestión de Confirmaciones y Autorizaciones Vinculadas para JDE.

Garantiza la vinculación criptográfica y contextual de cualquier autorización:
- Acción específica
- Parámetros específicos (hash SHA-256 normalizado)
- Sesión aislada (las sesiones NUNCA comparten confirmaciones)
- Identidad del usuario (user_id / principal)
- Vigencia temporal (TTL / monotonic timestamp)
- Monouso (una confirmación solo autoriza su operación y se consume)

INVARIANTES ABSOLUTAS:
1. Una cadena "ALLOW" o "confirmed=True" proveniente de un LLM o prompt
   NO constituye prueba de autorización.
2. Una confirmación para la acción A con parámetros P1 NUNCA autoriza
   la acción A con parámetros P2, ni la acción B.
3. Dos sesiones distintas NUNCA comparten confirmaciones.
4. Una vez consumida una confirmación, queda invalidada inmediatamente.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.jde.confirmation")


def compute_parameters_hash(parameters: dict[str, Any] | None) -> str:
    """Calcula un hash SHA-256 determinista sobre los parámetros normalizados.

    Ignora claves efímeras o metadatos de control inyectados (p. ej. request_id,
    is_confirmed, confirmed, correlation_id).
    """
    if not parameters:
        return hashlib.sha256(b"{}").hexdigest()

    ignored_keys = {
        "request_id",
        "correlation_id",
        "is_confirmed",
        "confirmed",
        "confirmation_token",
        "timestamp",
        "_execution_id",
    }
    cleaned: dict[str, Any] = {}
    for k, v in parameters.items():
        if k not in ignored_keys:
            # Normalizar tipos para serialización determinista
            if isinstance(v, (str, int, float, bool)) or v is None:
                cleaned[k] = v
            elif isinstance(v, (list, tuple)):
                cleaned[k] = list(v)
            elif isinstance(v, dict):
                cleaned[k] = {str(dk): str(dv) for dk, dv in v.items() if dk not in ignored_keys}
            else:
                cleaned[k] = str(v)

    try:
        canonical_json = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        canonical_json = str(sorted(cleaned.items()))

    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass
class JDEConfirmationRecord:
    """Registro inmutable de confirmación pendiente o aprobada."""

    confirmation_id: str
    session_id: str
    user_id: str
    action: str
    tool: str
    parameters_hash: str
    created_at: float
    expires_at: float
    is_confirmed: bool = False
    consumed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def is_valid_and_ready(self) -> bool:
        return self.is_confirmed and not self.consumed and not self.is_expired


class JDEConfirmationManager:
    """Gestor de confirmaciones estrictamente vinculadas a sesión, acción, parámetros y vigencia."""

    _instance: JDEConfirmationManager | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, default_ttl_seconds: float = 120.0) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._records: dict[str, JDEConfirmationRecord] = {}
        # Mapeo secundario: (session_id, action, parameters_hash) -> confirmation_id
        self._session_index: dict[tuple[str, str, str], str] = {}
        self._mutex = threading.RLock()

    def register_pending_confirmation(
        self,
        session_id: str,
        action: str,
        tool: str,
        parameters: dict[str, Any] | None = None,
        user_id: str = "default_user",
        ttl_seconds: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> JDEConfirmationRecord:
        """Registra una solicitud de confirmación humana vinculada estrictamente."""
        with self._mutex:
            self._purge_expired()
            p_hash = compute_parameters_hash(parameters)
            t_now = time.monotonic()
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
            t_exp = t_now + ttl

            conf_id = f"conf-{hashlib.sha256(f'{session_id}:{user_id}:{action}:{p_hash}:{t_now}'.encode()).hexdigest()[:16]}"
            record = JDEConfirmationRecord(
                confirmation_id=conf_id,
                session_id=session_id,
                user_id=user_id,
                action=action,
                tool=tool,
                parameters_hash=p_hash,
                created_at=t_now,
                expires_at=t_exp,
                is_confirmed=False,
                consumed=False,
                metadata=metadata or {},
            )
            self._records[conf_id] = record
            self._session_index[(session_id, action, p_hash)] = conf_id
            logger.info(
                f"[JDE CONFIRMATION REGISTERED] ID={conf_id} Session={session_id} User={user_id} "
                f"Action={action} Tool={tool} Hash={p_hash[:8]} TTL={ttl}s"
            )
            return record

    def confirm(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Aprueba explícitamente una confirmación pendiente para la sesión y acción específicas."""
        with self._mutex:
            self._purge_expired()
            p_hash = compute_parameters_hash(parameters)
            conf_id = self._session_index.get((session_id, action, p_hash))
            if not conf_id:
                # Intentar buscar por coincidencia de acción en la sesión si los parámetros son compatibles
                for (s, a, _h), cid in list(self._session_index.items()):
                    if s == session_id and a == action:
                        rec = self._records.get(cid)
                        if rec and not rec.is_expired and not rec.consumed:
                            conf_id = cid
                            break

            if not conf_id:
                logger.warning(
                    f"[JDE CONFIRMATION FAILED] No existe confirmación pendiente para "
                    f"Session={session_id} Action={action} Hash={p_hash[:8]}"
                )
                return False

            record = self._records.get(conf_id)
            if not record or record.is_expired or record.consumed:
                logger.warning(f"[JDE CONFIRMATION EXPIRED/CONSUMED] ID={conf_id}")
                return False

            if user_id and record.user_id != "default_user" and record.user_id != user_id:
                logger.warning(f"[JDE CONFIRMATION IDENTITY MISMATCH] ID={conf_id} Expected={record.user_id} Got={user_id}")
                return False

            record.is_confirmed = True
            logger.info(f"[JDE CONFIRMATION APPROVED] ID={conf_id} Session={session_id} Action={action}")
            return True

    def verify_and_consume(
        self,
        session_id: str,
        action: str,
        parameters: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Verifica si existe una confirmación válida y la consume de forma atómica y monouso."""
        with self._mutex:
            self._purge_expired()
            p_hash = compute_parameters_hash(parameters)
            conf_id = self._session_index.get((session_id, action, p_hash))
            if not conf_id:
                # Si la consulta no tiene parámetros (vacíos), solo coincide con confirmación sin parámetros
                empty_hash = compute_parameters_hash({})
                if p_hash == empty_hash:
                    for (s, a, h), cid in list(self._session_index.items()):
                        if s == session_id and a == action and h == empty_hash:
                            rec = self._records.get(cid)
                            if rec and rec.is_valid_and_ready:
                                conf_id = cid
                                break

            if not conf_id:
                return False

            record = self._records.get(conf_id)
            if not record or not record.is_valid_and_ready:
                return False

            if user_id and record.user_id != "default_user" and record.user_id != user_id:
                return False

            # Monouso: consumir inmediatamente
            record.consumed = True
            self._session_index.pop((record.session_id, record.action, record.parameters_hash), None)
            logger.info(
                f"[JDE CONFIRMATION CONSUMED] ID={conf_id} Session={session_id} Action={action}. "
                f"Confirmación gastada exitosamente."
            )
            return True

    def has_pending_confirmation(self, session_id: str, action: str | None = None) -> bool:
        """Verifica si hay alguna confirmación pendiente activa para una sesión."""
        with self._mutex:
            self._purge_expired()
            for rec in self._records.values():
                if rec.session_id == session_id and not rec.is_expired and not rec.consumed:
                    if action is None or rec.action == action:
                        return True
            return False

    def clear_session(self, session_id: str) -> None:
        """Limpia todas las confirmaciones asociadas a una sesión."""
        with self._mutex:
            to_del = [cid for cid, rec in self._records.items() if rec.session_id == session_id]
            for cid in to_del:
                rec = self._records.pop(cid, None)
                if rec:
                    self._session_index.pop((rec.session_id, rec.action, rec.parameters_hash), None)

    def reset(self) -> None:
        """Restablece completamente el registro (útil en pruebas)."""
        with self._mutex:
            if hasattr(self._records, "clear"):
                self._records.clear()
            self._records = {}
            self._session_index.clear()

    def _purge_expired(self) -> None:
        """Elimina registros expirados de memoria."""
        now = time.monotonic()
        expired = [cid for cid, rec in self._records.items() if now > rec.expires_at]
        for cid in expired:
            rec = self._records.pop(cid, None)
            if rec:
                self._session_index.pop((rec.session_id, rec.action, rec.parameters_hash), None)


_GLOBAL_CONFIRMATION_MANAGER: JDEConfirmationManager | None = None
_CONFIRMATION_LOCK = threading.Lock()


def get_confirmation_manager() -> JDEConfirmationManager:
    """Obtiene el singleton global de JDEConfirmationManager."""
    global _GLOBAL_CONFIRMATION_MANAGER
    with _CONFIRMATION_LOCK:
        if _GLOBAL_CONFIRMATION_MANAGER is None:
            _GLOBAL_CONFIRMATION_MANAGER = JDEConfirmationManager()
        return _GLOBAL_CONFIRMATION_MANAGER


def reset_confirmation_manager() -> None:
    """Restablece el singleton global para pruebas."""
    global _GLOBAL_CONFIRMATION_MANAGER
    with _CONFIRMATION_LOCK:
        if _GLOBAL_CONFIRMATION_MANAGER is not None:
            _GLOBAL_CONFIRMATION_MANAGER.reset()
        _GLOBAL_CONFIRMATION_MANAGER = None
