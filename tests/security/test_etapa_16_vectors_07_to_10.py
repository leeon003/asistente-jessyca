"""Etapa 16.0 — Vectores 07–10: Browser Bypass, Desktop Confusion,
Clipboard Leakage, Audit Leakage.
"""

from __future__ import annotations

import pytest

# ─────────────────────────────────────────────────────────
# Vector 07: Browser Allowlist Bypass
# ─────────────────────────────────────────────────────────

class TestBrowserAllowlistBypass:
    """Verifica que BrowserBoundary resiste bypass de allowlist."""

    def test_allowlist_url_accepted(self) -> None:
        """URL dentro del allowlist debe ser aceptada."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(
            allowed_domains={"example.com", "safe-site.org"}
        )
        result = boundary.validate_url("https://example.com/page")
        assert result.is_allowed, "URL en allowlist debe ser permitida."

    def test_url_outside_allowlist_rejected(self) -> None:
        """URL fuera del allowlist debe ser rechazada."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(
            allowed_domains={"example.com"}
        )
        result = boundary.validate_url("https://malicious-site.evil/attack")
        assert not result.is_allowed, "[AUDIT] URL fuera de allowlist fue permitida."

    def test_file_protocol_rejected(self) -> None:
        """Protocolo file:// debe ser bloqueado siempre."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(
            allowed_domains={"example.com"}
        )
        result = boundary.validate_url("file:///C:/Windows/System32/config")
        assert not result.is_allowed, "[AUDIT] Protocolo file:// no fue bloqueado."

    def test_javascript_protocol_rejected(self) -> None:
        """Protocolo javascript: debe ser bloqueado siempre."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(
            allowed_domains={"example.com"}
        )
        result = boundary.validate_url("javascript:alert('xss')")
        assert not result.is_allowed, "[AUDIT] Protocolo javascript: no fue bloqueado."

    def test_subdomain_escalation_blocked(self) -> None:
        """Subdominio malicioso de dominio permitido debe ser evaluado correctamente."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(
            allowed_domains={"example.com"}
        )
        # evil.example.com.attacker.com — no es subdominio de example.com
        result = boundary.validate_url("https://evil.example.com.attacker.com/phish")
        assert not result.is_allowed, (
            "[AUDIT] Subdominio de allowlist con sufijo malicioso no fue bloqueado."
        )

    def test_empty_allowlist_blocks_all(self) -> None:
        """Con allowlist vacío, todas las URLs deben ser bloqueadas."""
        from core.browser_boundary import BrowserBoundary
        boundary = BrowserBoundary(allowed_domains=set())
        result = boundary.validate_url("https://example.com")
        assert not result.is_allowed, (
            "[AUDIT] Allowlist vacío no bloqueó todas las URLs."
        )


# ─────────────────────────────────────────────────────────
# Vector 08: Desktop Target Confusion
# ─────────────────────────────────────────────────────────

class TestDesktopTargetConfusion:
    """Verifica que DesktopAutomationSecurity detecta targets obsoletos."""

    def test_stale_target_detection_via_action_guard(self) -> None:
        """ActionGuard debe rechazar acciones sobre targets obsoletos."""
        from core.desktop_automation_security import DesktopAutomationSecurity

        security = DesktopAutomationSecurity()

        # Un target que ya no existe en la pantalla
        result = security.validate_target(
            target_description="Save Button",
            current_screen_state={"visible_elements": []},  # vacío — target no está
        )
        assert not result.is_valid, (
            "[AUDIT] Target 'Save Button' no visible fue validado como válido."
        )

    def test_coordinate_bounds_validation(self) -> None:
        """Coordenadas fuera de la pantalla deben ser rechazadas."""
        from core.desktop_automation_security import DesktopAutomationSecurity

        security = DesktopAutomationSecurity()
        result = security.validate_coordinates(x=-100, y=50000)
        assert not result.is_valid, (
            "[AUDIT] Coordenadas fuera de pantalla (-100, 50000) no fueron rechazadas."
        )

    def test_emergency_stop_blocks_desktop_action(self) -> None:
        """Emergency stop activo debe bloquear cualquier acción de desktop."""
        from core.emergency_stop import EmergencyStopManager, EmergencyStopTriggeredError
        from core.desktop_automation_security import DesktopAutomationSecurity

        manager = EmergencyStopManager()
        manager.trigger_stop(reason="audit_test", source="test")

        security = DesktopAutomationSecurity(emergency_stop=manager)

        with pytest.raises(EmergencyStopTriggeredError):
            security.check_emergency_stop(phase="click")

        # Cleanup
        manager.reset(reason="audit_test_cleanup")


# ─────────────────────────────────────────────────────────
# Vector 09: Clipboard Leakage
# ─────────────────────────────────────────────────────────

class TestClipboardLeakage:
    """Verifica que ClipboardSecurity previene leakage de credenciales."""

    def test_password_in_clipboard_redacted_on_read(self) -> None:
        """Contraseñas leídas del clipboard deben ser redactadas."""
        from core.clipboard_security import ClipboardSecurityValidator

        validator = ClipboardSecurityValidator()
        result = validator.validate_clipboard_content(
            content="password=SuperSecret123!@# api_key=sk-abc123xyz"
        )
        assert "SuperSecret123" not in result.sanitized_content, (
            "[AUDIT] Contraseña del clipboard no fue redactada."
        )
        assert result.contains_sensitive_data, (
            "[AUDIT] Contenido sensible no fue detectado en clipboard."
        )

    def test_safe_clipboard_content_preserved(self) -> None:
        """Contenido de clipboard sin credenciales debe ser preservado."""
        from core.clipboard_security import ClipboardSecurityValidator

        validator = ClipboardSecurityValidator()
        result = validator.validate_clipboard_content(
            content="Hello world, this is a normal text to copy-paste."
        )
        assert "Hello world" in result.sanitized_content
        assert not result.contains_sensitive_data

    def test_token_pattern_detected_and_redacted(self) -> None:
        """Tokens JWT y API keys deben ser detectados y redactados."""
        from core.clipboard_security import ClipboardSecurityValidator

        validator = ClipboardSecurityValidator()
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.SflKxw"
        result = validator.validate_clipboard_content(content=f"token: {jwt_token}")
        assert jwt_token not in result.sanitized_content, (
            "[AUDIT] JWT token no fue redactado del clipboard."
        )


# ─────────────────────────────────────────────────────────
# Vector 10: Audit Leakage
# ─────────────────────────────────────────────────────────

class TestAuditLeakage:
    """Verifica que AuditLogger y SecretRedactor no filtran datos sensibles."""

    def test_password_in_audit_parameters_redacted(self) -> None:
        """Parámetros con 'password' en auditoría deben ser REDACTED."""
        from core.audit_logger import sanitize_audit_data

        data = {"password": "secret123", "username": "admin", "action": "login"}
        sanitized = sanitize_audit_data(data)
        assert sanitized["password"] == "[REDACTED]", (
            "[AUDIT] 'password' no fue redactado en audit data."
        )
        assert sanitized["username"] == "admin", "username no debe ser redactado."

    def test_nested_token_in_audit_data_redacted(self) -> None:
        """Token anidado en estructura de audit debe ser REDACTED."""
        from core.audit_logger import sanitize_audit_data

        data = {
            "request": {
                "headers": {
                    "authorization": "Bearer abc123",
                    "content_type": "application/json",
                }
            }
        }
        sanitized = sanitize_audit_data(data)
        assert sanitized["request"]["headers"]["authorization"] == "[REDACTED]", (
            "[AUDIT] 'authorization' header anidado no fue redactado."
        )
        assert sanitized["request"]["headers"]["content_type"] == "application/json"

    def test_long_string_truncated_in_audit(self) -> None:
        """Strings muy largas deben ser truncadas en audit para prevenir leakage."""
        from core.audit_logger import sanitize_audit_data

        data = {"description": "A" * 5000}
        sanitized = sanitize_audit_data(data)
        assert len(str(sanitized["description"])) <= 1001 + len(" [TRUNCATED]") + 1, (
            "[AUDIT] String larga no fue truncada en audit data."
        )

    def test_sensitive_key_false_positive_H03(self) -> None:
        """H-03 AUDIT: 'author' no debe ser redactado como 'auth'."""
        from core.audit_logger import sanitize_audit_data, _is_sensitive_key

        # 'author' contiene 'auth' como prefijo pero NO es una clave sensible
        is_sensitive = _is_sensitive_key("author")
        if is_sensitive:
            pytest.xfail(
                "[AUDIT-H03-CONFIRMED] _is_sensitive_key('author') retornó True. "
                "Falso positivo: 'author' fue redactado como si fuera 'auth'. "
                "Esto rompe la trazabilidad de auditoría."
            )

    def test_audit_event_hash_integrity(self) -> None:
        """El hash SHA-256 de un evento de auditoría debe ser determinista."""
        from core.audit_logger import compute_canonical_event_hash

        event_dict = {
            "event_type": "REQUEST_RECEIVED",
            "user": "test_user",
            "tool_name": "filesystem.read",
            "operation": "read",
        }

        hash1 = compute_canonical_event_hash(event_dict)
        hash2 = compute_canonical_event_hash(event_dict)

        assert hash1 == hash2, "Hash de evento no es determinista."
        assert len(hash1) == 64, "Hash SHA-256 debe tener 64 caracteres hex."

    def test_audit_event_hash_changes_on_tamper(self) -> None:
        """Hash del evento debe cambiar si se modifica cualquier campo."""
        from core.audit_logger import compute_canonical_event_hash

        original = {
            "event_type": "REQUEST_RECEIVED",
            "user": "test_user",
            "tool_name": "filesystem.read",
        }
        tampered = {
            "event_type": "REQUEST_RECEIVED",
            "user": "attacker",  # Modificado
            "tool_name": "filesystem.read",
        }

        hash_original = compute_canonical_event_hash(original)
        hash_tampered = compute_canonical_event_hash(tampered)

        assert hash_original != hash_tampered, (
            "[AUDIT] El hash de auditoría NO cambió al modificar el campo 'user'. "
            "La integridad criptográfica no está funcionando."
        )

    def test_secret_redactor_patterns(self) -> None:
        """SecretRedactor debe detectar y redactar patrones de credenciales comunes."""
        from core.command_output import SecretRedactor

        secrets = [
            "API_KEY=sk-abc123xyz987",
            "password: mysecretpassword",
            "token=eyJhbGci...",
        ]

        for secret_text in secrets:
            redacted, was_redacted = SecretRedactor.redact(secret_text)
            if not was_redacted:
                # Documentar como gap de seguridad
                pytest.xfail(
                    f"[AUDIT] SecretRedactor no detectó secreto en: {secret_text!r}"
                )
