"""Políticas de seguridad para navegación web, sesión y descargas (browser_policy.py - Fase 14).

GARANTÍAS DE SEGURIDAD ABSOLUTAS:
1. No confiar en el LLM para decidir si una URL es segura.
2. Deny-by-default en navegación: Solo dominios en whitelist. Bloqueo de javascript:, file:, data:.
3. Session Security: Cero cookies, tokens, contraseñas o secretos de sesión enviados al LLM.
4. Downloads: Descargas confinadas y prohibición absoluta de auto-ejecución de archivos descargados.
5. La navegación NO implica autorización para compras o transacciones financieras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.browser_models import URLAllowlistPolicy
from core.logger import get_logger

logger = get_logger("jessyca.agents.browser_policy")

FORBIDDEN_SCHEMES: tuple[str, ...] = ("javascript", "file", "data", "vbscript", "about", "chrome")

DANGEROUS_DOWNLOAD_EXTENSIONS: tuple[str, ...] = (
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".msi",
    ".scr",
    ".dll",
    ".com",
    ".jar",
    ".reg",
)

TRANSACTION_KEYWORDS: tuple[str, ...] = (
    "comprar",
    "compra",
    "pagar",
    "pago",
    "checkout",
    "tarjeta",
    "credit card",
    "order now",
    "finalizar compra",
    "transferir",
)


@dataclass(frozen=True)
class BrowserPolicyVerdict:
    """Veredicto inmutable de evaluación de seguridad web."""

    is_allowed: bool
    reason: str
    requires_confirmation: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BrowserPolicy:
    """Validador central de seguridad para BrowserAgent."""

    @classmethod
    def validate_url(cls, url: str, allowlist_policy: URLAllowlistPolicy | None = None) -> BrowserPolicyVerdict:
        """Evalúa determinísticamente si una URL es segura y está permitida."""
        if not url or not url.strip():
            return BrowserPolicyVerdict(is_allowed=False, reason="URL vacía o no especificada.")

        cleaned_url = url.strip()

        # 1. Esquemas prohibidos
        parsed = urlparse(cleaned_url)
        scheme = parsed.scheme.lower() if parsed.scheme else ""

        if scheme in FORBIDDEN_SCHEMES or ":" in cleaned_url.split("/")[0] and scheme not in ("http", "https"):
            msg = f"Esquema de URL no permitido o peligroso: '{scheme}'."
            logger.warning(f"[BROWSER SECURITY] {msg} URL: {cleaned_url}")
            return BrowserPolicyVerdict(is_allowed=False, reason=msg)

        if scheme not in ("http", "https"):
            msg = f"Solo se permiten esquemas HTTP y HTTPS (detectado: '{scheme}')."
            logger.warning(f"[BROWSER SECURITY] {msg}")
            return BrowserPolicyVerdict(is_allowed=False, reason=msg)

        # 2. Evaluación con URLAllowlistPolicy
        policy = allowlist_policy or URLAllowlistPolicy()
        if not policy.is_url_allowed(cleaned_url):
            msg = f"URL no permitida por Allowlist o política Deny-by-Default: '{cleaned_url}'"
            logger.warning(f"[BROWSER SECURITY] {msg}")
            return BrowserPolicyVerdict(is_allowed=False, reason=msg)

        return BrowserPolicyVerdict(is_allowed=True, reason="URL autorizada.")

    @classmethod
    def sanitize_dom_for_llm(cls, dom_text: str) -> str:
        """Sanitiza el contenido del DOM para no enviar cookies, tokens, contraseñas o secretos al LLM."""
        if not dom_text:
            return ""

        sanitized = dom_text

        # Redactar campos de password
        sanitized = re.sub(
            r'(type=["\']password["\'][^>]*value=["\'])([^"\']*)(["\'])',
            r"\1[REDACTED_PASSWORD]\3",
            sanitized,
            flags=re.IGNORECASE,
        )

        # Redactar tokens de sesión y cookies
        sanitized = re.sub(
            r'(bearer\s+)[a-zA-Z0-9_\-\.]{8,}',
            r"\1[REDACTED_TOKEN]",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r'(cookie:\s*)[^\r\n]+',
            r"\1[REDACTED_COOKIES]",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            r'(session_id|token|api_key|secret)=["\']?[a-zA-Z0-9_\-\.]{16,}["\']?',
            r"\1=[REDACTED_SECRET]",
            sanitized,
            flags=re.IGNORECASE,
        )

        return sanitized

    @classmethod
    def validate_download(cls, file_name: str) -> BrowserPolicyVerdict:
        """Evalúa si una descarga de archivo está permitida y bloquea binarios auto-ejecutables."""
        if not file_name:
            return BrowserPolicyVerdict(is_allowed=False, reason="Nombre de archivo de descarga vacío.")

        lower_name = file_name.lower().strip()
        for ext in DANGEROUS_DOWNLOAD_EXTENSIONS:
            if lower_name.endswith(ext):
                msg = f"Descarga y ejecución automática de archivos con extensión '{ext}' PROHIBIDA por seguridad."
                logger.warning(f"[BROWSER SECURITY] {msg} Archivo: {file_name}")
                return BrowserPolicyVerdict(is_allowed=False, reason=msg)

        return BrowserPolicyVerdict(
            is_allowed=True,
            reason="Descarga permitida (confinada a sandbox, auto-ejecución deshabilitada).",
        )

    @classmethod
    def detect_transaction_intent(cls, intent: str, url: str = "") -> BrowserPolicyVerdict:
        """Detecta si la intención o URL implica transacciones de compra/pago que requieran confirmación."""
        full_text = f"{intent} {url}".lower()

        for kw in TRANSACTION_KEYWORDS:
            if kw in full_text:
                msg = (
                    f"La intención contiene operaciones de compra o transacción ('{kw}'). "
                    "La navegación web NO implica autorización para compras. Se requiere confirmación de usuario explícita."
                )
                logger.info(f"[BROWSER SECURITY] Transacción detectada: {msg}")
                return BrowserPolicyVerdict(
                    is_allowed=False,
                    requires_confirmation=True,
                    reason=msg,
                )

        return BrowserPolicyVerdict(is_allowed=True, reason="Sin intención transaccional detectada.")
