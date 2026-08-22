"""Motor Anti-Spam y Gobernanza de Frecuencia Proactiva (anti_spam_engine.py - Fase 44).

Implementa los 4 pilares anti-saturación:
1. Cooldown (Periodos de enfriamiento por huella, herramienta o fuente).
2. Deduplicación (Detección de eventos idénticos o redundantes vía fingerprint criptográfico).
3. Prioridad (Ponderación y gestión de ventanas de emisión según urgencia/relevancia).
4. Supresión (Contención estricta de ráfagas, límites horarios y supresión de ruido).

INVARIANTE: JESSYCA jamás satura al usuario con notificaciones repetitivas o invasivas.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from core.logger import get_logger
from core.proactive.proactive_models import (
    AntiSpamDecision,
    ProactiveEvent,
    RelevanceAssessment,
    UserControlSettings,
)

logger = get_logger("jessyca.proactive.antispam")


class AntiSpamEngine:
    """Motor de filtrado, enfriamiento, deduplicación y control de ráfagas proactivas."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # fingerprint -> timestamp del último envío
        self._last_emitted_by_fingerprint: dict[str, float] = {}
        # Historial de timestamps para control de ratio horario
        self._emission_timestamps: deque[float] = deque()
        # Conteo de eventos duplicados suprimidos
        self._suppressed_counts: dict[str, int] = {}

    def check_spam(
        self,
        event: ProactiveEvent,
        relevance: RelevanceAssessment,
        settings: UserControlSettings | None = None,
    ) -> AntiSpamDecision:
        """Evalúa si un evento califica para ser emitido o si debe ser suprimido por spam."""
        cfg = settings or UserControlSettings()
        now = time.time()
        fp = event.compute_fingerprint()

        with self._lock:
            # 1. Limpieza de ventana de 1 hora para control de ratio
            one_hour_ago = now - 3600.0
            while self._emission_timestamps and self._emission_timestamps[0] < one_hour_ago:
                self._emission_timestamps.popleft()

            # 2. Control de Tasa Máxima por Hora
            if len(self._emission_timestamps) >= cfg.max_suggestions_per_hour and relevance.urgency < 0.90:
                logger.warning(
                    f"[ANTI-SPAM SUPPRESSION] Límite horario alcanzado ({len(self._emission_timestamps)}/{cfg.max_suggestions_per_hour}). "
                    f"Evento '{event.event_id}' suprimido."
                )
                return AntiSpamDecision(
                    allowed=False,
                    reason=f"Límite máximo de sugerencias por hora alcanzado ({cfg.max_suggestions_per_hour}/hora).",
                    fingerprint=fp,
                    suppressed=True,
                )

            # 3. Deduplicación y Cooldown por Fingerprint
            last_time = self._last_emitted_by_fingerprint.get(fp)
            if last_time is not None:
                elapsed = now - last_time
                cooldown_needed = cfg.cooldown_seconds

                # Si es alta urgencia (> 0.85), reducir cooldown a la mitad
                if relevance.urgency >= 0.85:
                    cooldown_needed = cooldown_needed / 2.0

                if elapsed < cooldown_needed:
                    remaining = cooldown_needed - elapsed
                    self._suppressed_counts[fp] = self._suppressed_counts.get(fp, 0) + 1
                    logger.info(
                        f"[ANTI-SPAM COOLDOWN] Evento duplicado/frecuente detectado (fp: {fp}). "
                        f"Cooldown restante: {remaining:.1f}s. Evento '{event.event_id}' suprimido."
                    )
                    return AntiSpamDecision(
                        allowed=False,
                        reason=f"Evento suprimido por periodo de enfriamiento (cooldown restante: {remaining:.1f}s).",
                        fingerprint=fp,
                        cooldown_remaining_seconds=remaining,
                        suppressed=True,
                    )

            # 4. Autorizado por Anti-Spam
            return AntiSpamDecision(
                allowed=True,
                reason="Evento validado por políticas anti-spam (no duplicado, fuera de cooldown, dentro de cuota).",
                fingerprint=fp,
                cooldown_remaining_seconds=0.0,
                suppressed=False,
            )

    def record_emission(self, event: ProactiveEvent, fingerprint: str | None = None) -> None:
        """Registra la emisión exitosa de una sugerencia o acción para actualizar contadores y cooldowns."""
        fp = fingerprint or event.compute_fingerprint()
        now = time.time()
        with self._lock:
            self._last_emitted_by_fingerprint[fp] = now
            self._emission_timestamps.append(now)

    def get_metrics(self) -> dict[str, Any]:
        """Obtiene métricas del motor anti-spam para observabilidad."""
        with self._lock:
            return {
                "recent_emissions_last_hour": len(self._emission_timestamps),
                "tracked_fingerprints": len(self._last_emitted_by_fingerprint),
                "suppressed_duplicates_count": sum(self._suppressed_counts.values()),
            }

    def reset(self) -> None:
        """Restablece el estado para aislamiento de pruebas unitarias."""
        with self._lock:
            self._last_emitted_by_fingerprint.clear()
            self._emission_timestamps.clear()
            self._suppressed_counts.clear()
