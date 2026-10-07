"""Servicio de Detección de Palabra de Activación (wake_word_service.py - Fase 13 / Prompt 08).

Gestiona la activación de la ventana de escucha conversacional ("Jessyca").

GARANTÍA DE SEGURIDAD ABSOLUTA E INVARIANTE INQUEBRANTABLE:
- WAKE WORD != AUTHORIZATION.
- La detección de la palabra de activación ÚNICAMENTE abre la ventana de escucha o turno
  conversacional. NUNCA concede autorización, permisos ni facultades para ejecutar acciones.
- Cualquier acción sensible o privilegiada requiere evaluación por el SecurityPipeline y permisos de usuario.

Detección Acústica vs Activación Manual (Push-to-Talk):
- Si no hay un detector acústico instalado/configurado (ej. openWakeWord o Porcupine),
  la capacidad acústica se declara formalmente NO DISPONIBLE (is_acoustic_model_available = False).
- No se inventa detección acústica falsa: se utiliza modo push-to-talk (manual) para pruebas, demo o CLI.
- Se preserva el protocolo IWakeWordService para la futura integración acústica del prompt I5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from core.logger import get_logger
from services.voice.audio_input import AudioChunk

logger = get_logger("jessyca.voice.wake_word")


@dataclass(frozen=True)
class WakeWordResult:
    """Resultado formal inmutable de la evaluación de palabra de activación.

    Invariante: detected=True NUNCA otorga autorización para ejecutar acciones.
    """

    detected: bool
    keyword: str
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    authorizes_action: bool = False  # Garantía de seguridad estricta

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "keyword": self.keyword,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
            "authorizes_action": False,
        }


@runtime_checkable
class IWakeWordService(Protocol):
    """Protocolo formal para servicios de detección de palabra de activación."""

    def process_audio(self, chunk: AudioChunk) -> WakeWordResult: ...
    def reset(self) -> None: ...
    def is_acoustic_model_available(self) -> bool: ...


class KeywordWakeWordService:
    """Detector de palabra de activación con soporte de Push-to-Talk y declaración acústica.

    En ausencia de un modelo acústico compilado/instalado en esta fase, declara
    explícitamente su indisponibilidad acústica y opera en modo manual (push-to-talk)
    para tests, demos y control interactivo sin generar falsas detecciones sintéticas.
    """

    authorizes_action: bool = False  # Wake word NEVER grants execution rights

    def __init__(
        self,
        keyword: str = "jessyca",
        confidence_threshold: float = 0.75,
        enabled: bool = True,
        mode: str = "manual",
    ) -> None:
        self.keyword = keyword.lower()
        self.confidence_threshold = confidence_threshold
        self.enabled = enabled
        self.mode = mode.lower()  # "manual" / "push_to_talk" o "acoustic"
        self._triggered = False

    def is_acoustic_model_available(self) -> bool:
        """Declara si existe un modelo acústico real (ej. openWakeWord) disponible.

        En esta fase sin motor acústico instalado, devuelve False de manera honesta.
        """
        return False

    def reset(self) -> None:
        """Restablece el estado interno del detector."""
        self._triggered = False

    def trigger_manually(self) -> None:
        """Activa manualmente el detector (modo Push-to-Talk / test / demo)."""
        self._triggered = True

    def process_audio(self, chunk: AudioChunk) -> WakeWordResult:
        """Evalúa un fragmento de audio efímero respetando el modo de operación."""
        if not self.enabled:
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={"enabled": False, "authorizes_action": False},
                authorizes_action=False,
            )

        # Si se solicita modo acústico pero no hay detector acústico disponible
        if self.mode == "acoustic" and not self.is_acoustic_model_available():
            logger.debug(
                "[WAKE WORD] Detector acústico no disponible en esta fase. "
                "Operando en push-to-talk sin inventar detección."
            )
            return WakeWordResult(
                detected=False,
                keyword=self.keyword,
                confidence=0.0,
                metadata={
                    "acoustic_available": False,
                    "mode": "acoustic",
                    "reason": "acoustic_engine_not_installed",
                    "authorizes_action": False,
                },
                authorizes_action=False,
            )

        # Modo manual / Push-to-talk (para tests, benchmarks y activación por interfaz)
        if self._triggered:
            self._triggered = False
            logger.info(f"[WAKE WORD] Activación manual/Push-to-Talk para '{self.keyword}' recibida.")
            return WakeWordResult(
                detected=True,
                keyword=self.keyword,
                confidence=1.0,
                metadata={
                    "trigger": "manual_push_to_talk",
                    "authorizes_action": False,
                },
                authorizes_action=False,
            )

        # En operación regular sin activación previa
        return WakeWordResult(
            detected=False,
            keyword=self.keyword,
            confidence=0.0,
            metadata={"trigger": "manual_push_to_talk", "authorizes_action": False},
            authorizes_action=False,
        )


def get_wake_word_service(
    backend: str | None = None,
    keyword: str = "jessyca",
    model_path: Any | None = None,
    confidence_threshold: float | None = None,
    cooldown_seconds: float | None = None,
    fallback_to_manual: bool = True,
    **kwargs: Any,
) -> IWakeWordService:
    """Fábrica gobernada para instanciar el servicio de detección de palabra de activación.

    Respeta:
    1. Si backend es None: lee WAKE_WORD_BACKEND / OPENWAKEWORD_ENABLED de AppSettings (default: 'manual').
    2. Si backend == 'openwakeword': importa e inicializa OpenWakeWordAcousticService de forma perezosa.
       Si la inicialización falla o no hay modelo configurado y fallback_to_manual=True,
       registra advertencia y recurre a KeywordWakeWordService.
    3. Si backend == 'manual': retorna KeywordWakeWordService(**kwargs).

    INVARIANTE DE SEGURIDAD ABSOLUTA:
    detected=True NUNCA concede autorización para ejecutar acciones.
    """
    selected_backend = backend
    threshold = confidence_threshold
    cooldown = cooldown_seconds
    target_model_path = model_path

    if not selected_backend:
        try:
            from config.manager import get_settings

            settings = get_settings()
            if getattr(settings, "OPENWAKEWORD_ENABLED", False):
                selected_backend = "openwakeword"
            else:
                selected_backend = getattr(settings, "WAKE_WORD_BACKEND", "manual").lower()

            if threshold is None:
                threshold = getattr(settings, "OPENWAKEWORD_THRESHOLD", 0.60)
            if cooldown is None:
                cooldown = getattr(settings, "OPENWAKEWORD_COOLDOWN_SECONDS", 2.0)
            if target_model_path is None:
                target_model_path = getattr(settings, "OPENWAKEWORD_MODEL_PATH", None)
        except Exception:
            selected_backend = "manual"

    if threshold is None:
        threshold = 0.60
    if cooldown is None:
        cooldown = 2.0

    if selected_backend == "openwakeword":
        try:
            from services.voice.openwakeword_service import OpenWakeWordAcousticService

            return OpenWakeWordAcousticService(
                keyword=keyword,
                model_path=target_model_path,
                confidence_threshold=threshold,
                cooldown_seconds=cooldown,
                fallback_to_manual=fallback_to_manual,
                **kwargs,
            )
        except Exception as e:
            logger.warning(
                f"[WAKE WORD FACTORY] Fallo al inicializar OpenWakeWordAcousticService: {e}. "
                f"Fallback a KeywordWakeWordService={fallback_to_manual}."
            )
            if not fallback_to_manual:
                raise
            return KeywordWakeWordService(
                keyword=keyword,
                confidence_threshold=threshold,
                mode="manual",
                **kwargs,
            )

    return KeywordWakeWordService(
        keyword=keyword,
        confidence_threshold=threshold if threshold is not None else 0.75,
        mode="manual",
        **kwargs,
    )

