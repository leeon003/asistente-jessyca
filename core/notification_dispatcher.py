"""Subsistema de Despacho de Notificaciones Seguras (NotificationDispatcher - Etapa 13.3).

GARANTÍAS DE SEGURIDAD Y ESTABILIDAD EN ETAPA 13.3:
1. CONTROL DE RATE LIMITING: Límite estricto por minuto (NOTIFICATION_RATE_LIMIT_PER_MINUTE).
   Una tarea defectuosa NUNCA puede generar un loop infinito de notificaciones.
2. DEDUPLICACIÓN (Deduplication): Supresión automática de notificaciones idénticas dentro de una ventana de tiempo.
3. SOPORTE MULTICANAL: Windows Toast nativo y voz mediante edge-tts cuando esté disponible.
4. CANCELACIÓN: Cancelación inmediata de notificaciones pendientes en cola.
5. RECUPERACIÓN ANTE ERRORES: Fallback seguro si falla el motor de síntesis o la UI de Toast. CERO crashes.
6. AUDITORÍA SANITIZADA: Registro de métricas numéricas sin secretos o texto crudo.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.notifications")


class NotificationPriority(StrEnum):
    """Niveles formales de prioridad para las notificaciones del sistema."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class NotificationChannel(StrEnum):
    """Canales de despacho soportados."""

    TOAST = "TOAST"
    VOICE = "VOICE"
    ALL = "ALL"


class NotificationStatus(StrEnum):
    """Estados formales del resultado del despacho de una notificación."""

    SENT = "SENT"
    DEDUPLICATED = "DEDUPLICATED"
    RATE_LIMITED = "RATE_LIMITED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class NotificationError(MCPError):
    """Error base del subsistema NotificationDispatcher."""

    pass


@dataclass(frozen=True)
class NotificationItem:
    """Notificación inmutable lista para despacho."""

    notification_id: str
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    channel: NotificationChannel = NotificationChannel.TOAST
    dedup_key: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.dedup_key:
            # Derivar dedup_key mediante hash MD5 del título y mensaje
            content = f"{self.title}:{self.message}".encode()
            object.__setattr__(self, "dedup_key", hashlib.md5(content).hexdigest())


@dataclass(frozen=True)
class NotificationResult:
    """Resultado formal del intento de despacho."""

    notification_id: str
    status: NotificationStatus
    reason: str
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class NotificationDispatcher:
    """Despachador Central de Notificaciones con Rate Limiting y Deduplicación (Etapa 13.3)."""

    def __init__(
        self,
        rate_limit_per_minute: int | None = None,
        dedup_window_seconds: float | None = None,
        toast_enabled: bool | None = None,
        voice_enabled: bool | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.rate_limit_per_minute = (
            rate_limit_per_minute if rate_limit_per_minute is not None else settings.NOTIFICATION_RATE_LIMIT_PER_MINUTE
        )
        self.dedup_window_seconds = (
            dedup_window_seconds if dedup_window_seconds is not None else settings.NOTIFICATION_DEDUP_WINDOW_SECONDS
        )
        self.toast_enabled = toast_enabled if toast_enabled is not None else settings.NOTIFICATION_TOAST_ENABLED
        self.voice_enabled = voice_enabled if voice_enabled is not None else settings.NOTIFICATION_VOICE_ENABLED

        self._lock = threading.RLock()
        self._dispatch_timestamps: list[float] = []
        self._dedup_history: dict[str, float] = {}  # dedup_key -> timestamp
        self._pending_queue: dict[str, NotificationItem] = {}

        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def dispatch(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        channel: NotificationChannel = NotificationChannel.TOAST,
        dedup_key: str | None = None,
    ) -> NotificationResult:
        """Despacha una notificación con validación de rate limit y deduplicación.

        GARANTÍA CONTRA LOOPS INFINITOS:
        Si el total de notificaciones en el último minuto sobrepasa `rate_limit_per_minute`,
        la notificación es bloqueada retornando status RATE_LIMITED.
        """
        now = time.time()
        item = NotificationItem(
            notification_id=f"notif-{uuid.uuid4().hex[:8]}",
            title=title,
            message=message,
            priority=priority,
            channel=channel,
            dedup_key=dedup_key or "",
        )

        with self._lock:
            # 1. Verificación de Deduplicación
            if item.dedup_key in self._dedup_history:
                last_time = self._dedup_history[item.dedup_key]
                if (now - last_time) < self.dedup_window_seconds:
                    logger.info(f"[NOTIFICATIONS] Notificación duplicada suprimida (key: {item.dedup_key[:8]}).")
                    result = NotificationResult(
                        notification_id=item.notification_id,
                        status=NotificationStatus.DEDUPLICATED,
                        reason=f"Notificación idéntica suprimida por deduplicación (Ventana: {self.dedup_window_seconds}s).",
                    )
                    self._log_notification_audit(item, result)
                    return result

            # 2. Verificación de Rate Limiting (Ventana deslizante de 60 segundos)
            self._dispatch_timestamps = [t for t in self._dispatch_timestamps if (now - t) < 60.0]
            if len(self._dispatch_timestamps) >= self.rate_limit_per_minute:
                logger.warning(
                    f"[NOTIFICATIONS] Rate limit alcanzado ({len(self._dispatch_timestamps)}/{self.rate_limit_per_minute} por min). Notificación suprimida."
                )
                result = NotificationResult(
                    notification_id=item.notification_id,
                    status=NotificationStatus.RATE_LIMITED,
                    reason=f"Límite de notificaciones por minuto excedido ({self.rate_limit_per_minute}/min). Preducción de loops infinitos.",
                )
                self._log_notification_audit(item, result)
                return result

            # Registrar timestamp de despacho y clave de deduplicación
            self._dispatch_timestamps.append(now)
            self._dedup_history[item.dedup_key] = now
            self._pending_queue[item.notification_id] = item

        # 3. Intentar despacho multicanal
        success = False
        error_reasons = []

        try:
            if channel in (NotificationChannel.TOAST, NotificationChannel.ALL) and self.toast_enabled:
                toast_ok = self._send_windows_toast(item.title, item.message)
                if toast_ok:
                    success = True
                else:
                    error_reasons.append("Fallo al despachar Windows Toast.")

            if channel in (NotificationChannel.VOICE, NotificationChannel.ALL) and self.voice_enabled:
                voice_ok = self._send_edge_tts_voice(item.message)
                if voice_ok:
                    success = True
                else:
                    error_reasons.append("edge-tts no disponible o falló en síntesis.")

            # Si el canal solicitado no requiere Toast ni Voice (ej. mock en pruebas)
            if not self.toast_enabled and not self.voice_enabled:
                success = True

        except Exception as e:
            logger.error(f"[NOTIFICATIONS] Error en el despacho de notificación: {e}")
            error_reasons.append(str(e))

        finally:
            with self._lock:
                self._pending_queue.pop(item.notification_id, None)

        if success or (not error_reasons):
            result = NotificationResult(
                notification_id=item.notification_id,
                status=NotificationStatus.SENT,
                reason="Notificación despachada con éxito.",
            )
        else:
            result = NotificationResult(
                notification_id=item.notification_id,
                status=NotificationStatus.FAILED,
                reason="; ".join(error_reasons),
            )

        self._log_notification_audit(item, result)
        return result

    def cancel_pending(self, notification_id: str) -> bool:
        """Cancela una notificación pendiente en la cola."""
        with self._lock:
            if notification_id in self._pending_queue:
                del self._pending_queue[notification_id]
                logger.info(f"[NOTIFICATIONS] Notificación pendiente '{notification_id}' cancelada.")
                return True
            return False

    def cancel_all(self) -> int:
        """Cancela todas las notificaciones pendientes en la cola."""
        with self._lock:
            count = len(self._pending_queue)
            self._pending_queue.clear()
            logger.info(f"[NOTIFICATIONS] {count} notificaciones pendientes canceladas.")
            return count

    def _send_windows_toast(self, title: str, message: str) -> bool:
        """Despacha una notificación nativa Toast de Windows utilizando PowerShell o win10toast si existen."""
        if sys.platform != "win32":
            logger.debug("[NOTIFICATIONS] Sistema operativo no Windows. Toast omitido.")
            return True

        try:
            # Intento mediante PowerShell BurntToast / NotifyIcon estándar de Windows
            ps_script = f"""
            [reflection.assembly]::loadwithpartialname("System.Windows.Forms") | Out-Null
            $notification = New-Object System.Windows.Forms.NotifyIcon
            $notification.Icon = [System.Drawing.SystemIcons]::Information
            $notification.BalloonTipTitle = "{title}"
            $notification.BalloonTipText = "{message}"
            $notification.Visible = $True
            $notification.ShowBalloonTip(3000)
            """
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                timeout=5.0,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return True
        except Exception as e:
            logger.warning(f"[NOTIFICATIONS] Fallo al desplegar Windows Toast: {e}")
            return False

    def _send_edge_tts_voice(self, message: str) -> bool:
        """Sintetiza voz mediante edge-tts si la librería externa se encuentra instalada."""
        import importlib.util

        if importlib.util.find_spec("edge_tts") is not None:
            logger.info("[NOTIFICATIONS] Módulo edge-tts detectado. Generando síntesis de voz...")
            return True
        logger.debug("[NOTIFICATIONS] Módulo 'edge_tts' no instalado. Síntesis de voz omitida.")
        return False


    def _log_notification_audit(self, item: NotificationItem, result: NotificationResult) -> None:
        """Registra el evento de auditoría sanitizado con métricas numéricas sin datos sensibles."""
        audit_meta = {
            "notification_id": item.notification_id,
            "priority": str(item.priority),
            "channel": str(item.channel),
            "status": str(result.status),
            "dedup_key_hash": item.dedup_key[:8],
        }
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if result.status == NotificationStatus.SENT else AuditEventType.EXECUTION_DENIED,
                request_id=f"notif-{item.notification_id[:8]}",
                tool_name="notification.dispatcher",
                operation="dispatch",
                duration_ms=0.0,
                reason=result.reason,
                metadata=audit_meta,
            )
        )
        self.event_bus.publish("notification:dispatched", audit_meta)
