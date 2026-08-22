"""Experience Logger para JESSYCA (experience_logger.py - Fase 57).

Registrador central de experiencias estructuradas.
Garantiza:
1. DESACOPLAMIENTO DEL AUDIT LOGGER: Destinado exclusivamente a comportamiento y rendimiento.
2. ZERO LEAKAGE: Sanitización automática y determinista previa a la persistencia.
3. FAIL-SAFE ISOLATION: Ninguna falla en el logging interrumpe la ejecución principal del agente.
4. THREAD-SAFETY: Acceso seguro en entornos multi-hilo concurrentes.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from core.experience.experience_store import IExperienceStore, SQLiteExperienceStore
from core.experience.models import (
    CorrectionInfo,
    ErrorInfo,
    ExecutionResult,
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    ExperienceInput,
    ExperienceMetadata,
    InputSource,
    IntentResult,
    LatencyInfo,
    ResponseResult,
    STTResult,
    TargetInfo,
    VerificationResult,
    VerificationStatus,
)
from core.experience.repository import ExperienceRepository, IExperienceRepository
from core.experience.sanitization import sanitize_experience_data
from core.logger import get_logger

logger = get_logger("jessyca.experience.logger")


class ExperienceLogger:
    """Registrador central estructurado y no bloqueante de experiencias."""

    _instance: ClassVar[ExperienceLogger | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        repository: IExperienceRepository | None = None,
        store: IExperienceStore | None = None,
        enabled: bool | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self._enabled = enabled if enabled is not None else getattr(settings, "EXPERIENCE_LOGGING_ENABLED", True)
        if repository is not None:
            self._repository = repository
        else:
            active_store = store or SQLiteExperienceStore()
            self._repository = ExperienceRepository(store=active_store)

        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> ExperienceLogger:
        """Obtiene la instancia singleton de ExperienceLogger."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ExperienceLogger()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Restablece el singleton para aislamiento en pruebas."""
        with cls._class_lock:
            cls._instance = None

    @property
    def repository(self) -> IExperienceRepository:
        return self._repository

    def set_repository(self, repository: IExperienceRepository) -> None:
        """Configura un repositorio personalizado (e.g. en tests con InMemoryExperienceStore)."""
        with self._lock:
            self._repository = repository

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    # ── MÉTODO PRINCIPAL DE REGISTRO FAIL-SAFE ──

    def log_experience(self, experience: Experience) -> str | None:
        """Registra una experiencia sanitizada de forma fail-safe.

        Retorna el experience_id si fue persistida exitosamente, o None si está deshabilitada o hubo un error.
        Garantía: NUNCA lanza excepciones que interrumpan el flujo de ejecución principal.
        """
        if not self._enabled:
            return None

        try:
            # 1. Sanitización de seguridad profunda
            sanitized_data = sanitize_experience_data(experience.to_dict())
            clean_experience = Experience.from_dict(sanitized_data)

            # 2. Persistencia en repositorio
            with self._lock:
                self._repository.save_experience(clean_experience)

            logger.debug(f"[EXPERIENCE LOGGED] {clean_experience.category.value} -> ID: {clean_experience.experience_id}")
            return clean_experience.experience_id
        except Exception as ex:
            # Aislamiento estricto de fallos
            logger.error(f"[EXPERIENCE LOGGER FAIL-SAFE] Error no fatal al registrar experiencia: {ex}")
            return None

    # ── MÉTODOS HELPER DE CONVENIENCIA ──

    def log_interaction(
        self,
        user_input: str,
        response_text: str,
        session_id: str | None = None,
        correlation_id: str | None = None,
        source: InputSource = InputSource.TEXT,
        category: ExperienceCategory = ExperienceCategory.GENERAL,
        stt_text: str | None = None,
        stt_confidence: float = 1.0,
        intent_name: str = "general_query",
        intent_confidence: float = 1.0,
        target_type: str | None = None,
        target_value: str | None = None,
        execution_status: ExecutionStatus = ExecutionStatus.SUCCESS,
        tool_name: str | None = None,
        action: str | None = None,
        verification_status: VerificationStatus = VerificationStatus.NOT_PERFORMED,
        is_verified: bool = False,
        total_latency_ms: float = 0.0,
        error_message: str | None = None,
        error_code: str | None = None,
        is_correction: bool = False,
        model_used: str | None = None,
        agent_used: str | None = None,
        skill_used: str | None = None,
        metadata_extra: dict[str, Any] | None = None,
    ) -> str | None:
        """Construye y registra una experiencia completa a partir de parámetros individuales."""
        try:
            exp_input = ExperienceInput(
                source=source,
                raw_text=user_input,
                normalized_text=user_input.strip(),
            )

            stt_res = None
            if stt_text is not None or source == InputSource.VOICE:
                stt_res = STTResult(
                    text=stt_text or user_input,
                    confidence=stt_confidence,
                    is_low_confidence=stt_confidence < 0.60,
                )

            intent_res = IntentResult(
                name=intent_name,
                confidence=intent_confidence,
                is_ambiguous=category == ExperienceCategory.AMBIGUOUS_INTENT,
            )

            target_res = None
            if target_type or target_value:
                target_res = TargetInfo(
                    target_type=target_type or "general",
                    value=target_value or "",
                )

            exec_res = ExecutionResult(
                status=execution_status,
                tool_name=tool_name,
                action=action,
            )

            verif_res = VerificationResult(
                status=verification_status,
                is_verified=is_verified,
            )

            resp_res = ResponseResult(
                text=response_text,
                spoken_text=response_text if source == InputSource.VOICE else None,
                modality=source.value,
            )

            lat_info = LatencyInfo(total_ms=total_latency_ms)

            err_info = None
            if error_message or execution_status == ExecutionStatus.FAILED:
                err_info = ErrorInfo(
                    error_type="ExecutionError",
                    error_code=error_code,
                    message=error_message or "Fallo en la ejecución de la acción",
                )

            corr_info = None
            if is_correction or category == ExperienceCategory.USER_CORRECTION:
                corr_info = CorrectionInfo(
                    is_correction=True,
                    corrected_target=target_value,
                )

            meta_info = ExperienceMetadata(
                version="3.0.0",
                model_used=model_used,
                agent_used=agent_used,
                skill_used=skill_used,
                extra=metadata_extra or {},
            )

            exp = Experience(
                category=category,
                session_id=session_id,
                correlation_id=correlation_id,
                input=exp_input,
                stt=stt_res,
                intent=intent_res,
                target=target_res,
                execution=exec_res,
                verification=verif_res,
                response=resp_res,
                latency=lat_info,
                error=err_info,
                correction=corr_info,
                metadata=meta_info,
            )

            return self.log_experience(exp)
        except Exception as ex:
            logger.error(f"[EXPERIENCE LOGGER HELPER ERROR] {ex}")
            return None


# Helper global singleton
_default_experience_logger: ExperienceLogger | None = None


def get_experience_logger() -> ExperienceLogger:
    """Obtiene el registrador de experiencias global configurado."""
    return ExperienceLogger.get_instance()
