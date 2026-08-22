"""Módulo de Sanitización de Datos para Experience Logger (sanitization.py - Fase 57).

Garantiza la regla fundamental de seguridad:
    NO SENSITIVE DATA IN EXPERIENCE LOGS

Elimina de forma recursiva y determinista:
- Contraseñas, tokens de autenticación, JWTs, API Keys, cookies de sesión.
- Claves privadas, certificados, credenciales del sistema.
- Trunca textos excesivamente largos para prevenir desbordamientos o polución.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

SENSITIVE_KEY_PATTERNS: frozenset[str] = frozenset({
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "credential",
    "credentials",
    "authorization",
    "auth_header",
    "cookie",
    "session_cookie",
    "set_cookie",
    "private_key",
    "privkey",
    "certificate_private_key",
    "credit_card",
    "cvv",
    "cvc",
    "ssn",
    "pin",
})

# Patrones regex para detección de secretos en cadenas de texto
SECRET_VALUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{15,}"),
    re.compile(r"(?i)(?:api[_\-]?key|token|secret|password|passwd)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}\b"),  # GitHub tokens
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),  # Google API Keys
    re.compile(r"\bsk-[a-zA-Z0-9]{32,}\b"),  # OpenAI-like API keys
]


def is_sensitive_key(key: str) -> bool:
    """Evalúa si el nombre de una clave indica contenido confidencial."""
    k = str(key).lower().strip()
    if k in SENSITIVE_KEY_PATTERNS:
        return True
    words = set(re.split(r"[_\-\s\.]+", k))
    return bool(words & SENSITIVE_KEY_PATTERNS)


def sanitize_string_value(text: str, max_str_len: int = 2000) -> str:
    """Sanitiza cadenas de texto enmascarando patrones de secretos conocidos y truncando."""
    if not text:
        return text

    sanitized = text
    for pattern in SECRET_VALUE_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)

    if len(sanitized) > max_str_len:
        return sanitized[:max_str_len] + " [TRUNCATED]"

    return sanitized


def sanitize_experience_data(data: Any, max_str_len: int = 2000) -> Any:
    """Sanitiza recursivamente cualquier estructura de datos antes de persistir la experiencia.

    - Reemplaza valores de claves confidenciales con '[REDACTED]'.
    - Enmascara patrones de secretos en strings con '[REDACTED_SECRET]'.
    - Trunca cadenas largas con '[TRUNCATED]'.
    - Maneja de forma segura diccionarios, listas, tuplas, conjuntos, objetos Pydantic y tipos primitivos.
    """
    if data is None:
        return None

    if isinstance(data, dict):
        sanitized_dict: dict[str, Any] = {}
        for k, v in data.items():
            key_str = str(k)
            if is_sensitive_key(key_str):
                sanitized_dict[key_str] = "[REDACTED]"
            else:
                sanitized_dict[key_str] = sanitize_experience_data(v, max_str_len)
        return sanitized_dict

    if isinstance(data, (list, tuple, set)):
        items = [sanitize_experience_data(item, max_str_len) for item in data]
        if isinstance(data, tuple):
            return tuple(items)
        if isinstance(data, set):
            return set(items)
        return items

    if isinstance(data, str):
        return sanitize_string_value(data, max_str_len)

    if isinstance(data, BaseModel):
        dumped = data.model_dump(mode="python")
        sanitized_dump = sanitize_experience_data(dumped, max_str_len)
        return type(data).model_validate(sanitized_dump)

    if hasattr(data, "__dict__"):
        try:
            return sanitize_experience_data(vars(data), max_str_len)
        except Exception:
            return sanitize_string_value(str(data), max_str_len)

    return data
