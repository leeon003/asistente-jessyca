"""Clasificador Determinista de Naturaleza de Fallos (FailureClassifier - Etapa 17.3).

Clasifica excepciones y códigos de error en:
  - TRANSIENT: Errores transitorios de I/O, red o concurrencia. Elegibles para retry acotado.
  - RECOVERABLE: Errores que requieren reinicialización o fallback de sesión.
  - PERMANENT: Errores deterministas de lógica, sintaxis, permisos o violación de seguridad. CERO RETRY.
  - UNKNOWN: Errores genéricos no catalogados.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.exceptions import MCPError
from core.recovery.models import FailureClassification


class FailureClassifier:
    """Clasificador de excepciones y respuestas de error para la toma de decisiones de recuperación."""

    # Tipos explícitos de fallos transitorios
    TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
        TimeoutError,
        asyncio.TimeoutError,
        ConnectionError,
        ConnectionResetError,
        ConnectionRefusedError,
        ConnectionAbortedError,
        BlockingIOError,
        InterruptedError,
    )

    # Tipos explícitos de fallos permanentes
    PERMANENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
        FileNotFoundError,
        FileExistsError,
        IsADirectoryError,
        NotADirectoryError,
        PermissionError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        SyntaxError,
        ZeroDivisionError,
        NotImplementedError,
    )

    @classmethod
    def classify(cls, error: BaseException | str | None) -> FailureClassification:
        """Determina la clasificación formal del fallo."""
        if error is None:
            return FailureClassification.UNKNOWN

        # Si se pasa una instancia de excepción
        if isinstance(error, BaseException):
            # 1. Chequeo de violaciones de seguridad y permisos (siempre PERMANENT)
            err_name = type(error).__name__.lower()
            if any(term in err_name for term in ("security", "permission", "escalation", "forbidden", "unauthorized", "boundary")):
                return FailureClassification.PERMANENT

            # 2. Excepciones transitorias estándar
            if isinstance(error, cls.TRANSIENT_EXCEPTIONS):
                return FailureClassification.TRANSIENT

            # 3. Excepciones permanentes estándar
            if isinstance(error, cls.PERMANENT_EXCEPTIONS):
                return FailureClassification.PERMANENT

            # 4. Análisis por mensaje de error
            msg = str(error).lower()
            if any(term in msg for term in ("timeout", "timed out", "temporarily unavailable", "connection refused", "econnreset", "try again")):
                return FailureClassification.TRANSIENT

            if any(term in msg for term in ("not found", "no such file", "invalid argument", "syntax error", "permission denied", "access denied")):
                return FailureClassification.PERMANENT

            return FailureClassification.UNKNOWN

        # Si se pasa un mensaje en formato string
        msg_str = str(error).lower()
        if any(term in msg_str for term in ("timeout", "connection reset", "temporarily unavailable", "retry")):
            return FailureClassification.TRANSIENT
        if any(term in msg_str for term in ("permission", "denied", "not found", "invalid", "syntax", "security")):
            return FailureClassification.PERMANENT

        return FailureClassification.UNKNOWN

    @classmethod
    def is_retryable(cls, error: BaseException | str | None) -> bool:
        """Indica si la naturaleza del error permite un reintento técnico (sujeto además a la política de riesgo)."""
        classification = cls.classify(error)
        return classification in (FailureClassification.TRANSIENT, FailureClassification.RECOVERABLE)
