"""Validador y Filtro de Seguridad de Preferencias (preference_validator.py - Fase 62).

Implementa:
1. SEPARACIÓN ABSOLUTA ENTRE PREFERENCIA Y AUTORIZACIÓN: Rechazo tajante de preferencias
   que intenten modificar permisos, saltarse confirmaciones o alterar la política de seguridad.
2. SANITIZACIÓN DE SECRETOS: Prohíbe almacenar contraseñas, tokens o claves API como preferencias.
3. NORMALIZACIÓN DE CLAVES: Garantiza consistencia en aliases y términos.
"""

from __future__ import annotations

import re

from core.personalization.preference_models import UserPreference

# Términos prohibidos para evitar almacenar secretos o bypassear seguridad
FORBIDDEN_PREFERENCE_TERMS: frozenset[str] = frozenset({
    "password",
    "token",
    "secret",
    "api_key",
    "credential",
    "auth_token",
    "private_key",
    "bypass_security",
    "grant_permission",
    "disable_confirmation",
    "disable_audit",
    "security_override",
})


def normalize_preference_key(key: str) -> str:
    """Normaliza una clave de preferencia eliminando espacios redundantes y convirtiendo a minúsculas."""
    return re.sub(r"\s+", " ", key.strip().lower())


class PreferenceValidator:
    """Validador central de seguridad y consistencia para preferencias del usuario."""

    @staticmethod
    def validate_preference(preference: UserPreference) -> tuple[bool, list[str]]:
        """Valida que la preferencia cumpla los requisitos de seguridad e integridad."""
        errors: list[str] = []

        norm_key = normalize_preference_key(preference.key)
        val_str = str(preference.value).lower().strip()

        # 1. VERIFICACIÓN DE SEGURIDAD ABSOLUTA (Regla Fundamental)
        for term in FORBIDDEN_PREFERENCE_TERMS:
            if term in norm_key or term in val_str:
                errors.append(
                    f"CRITICAL SECURITY VIOLATION: La preferencia contiene el término protegido o sensible '{term}'. "
                    "Las preferencias NO pueden almacenar secretos ni modificar políticas de seguridad o autorización."
                )

        # 2. Validación de clave y valor
        if not norm_key:
            errors.append("La clave de preferencia ('key') no puede estar vacía.")

        if preference.value is None or preference.value == "":
            errors.append("El valor de la preferencia ('value') no puede ser nulo o vacío.")

        # 3. Rango de confianza
        if not (0.0 <= preference.confidence <= 1.0):
            errors.append(f"La confianza ({preference.confidence}) debe estar comprendida entre 0.0 y 1.0.")

        return (len(errors) == 0, errors)
