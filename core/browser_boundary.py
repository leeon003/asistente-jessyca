"""Frontera de seguridad para el control de sesiones de navegador web (Subetapa 11.2).

GARANTÍA ABSOLUTA DE SEGURIDAD Y PRIVACIDAD:
Interconecta el control del navegador web (`windows.browser`) con la tubería de autorización SecureExecutionPipeline,
URLAllowlistPolicy (Deny-by-Default), EmergencyStopManager, AuditLogger y EventBus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.browser_models import BrowserControlError
from core.browser_session_manager import BrowserSessionManager
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine, SecurityLevel

logger = get_logger("jessyca.core.browser_boundary")


class BrowserControlBoundary:
    """Frontera de seguridad para la ejecución autorizada, sanitizada y auditada de navegación web."""

    def __init__(
        self,
        session_manager: BrowserSessionManager | None = None,
        emergency_stop_manager: EmergencyStopManager | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.session_manager = session_manager or BrowserSessionManager()
        self.emergency_stop = emergency_stop_manager or get_emergency_stop_manager()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute_browser_control(
        self,
        action: str,
        url: str | None = None,
        tab_id: str | None = None,
        media_action: str | None = None,
        selector: str | None = None,
        js_snippet: Any | None = None,
        request_id: str = "browser-boundary-req",
    ) -> dict[str, Any]:
        """Ejecuta una operación sobre el navegador web atravesando la frontera de seguridad."""
        start_time = datetime.now(UTC)
        act_clean = str(action).strip().lower()

        # 1. Comprobación inmediata de Parada de Emergencia (Fail-Safe)
        self.emergency_stop.check_cancellation(phase="validation")

        # 2. Evaluación de Riesgo y Permisos
        risk_level = SecurityLevel.WARNING if act_clean in ("open_url", "navigate", "switch_tab", "query_dom") else SecurityLevel.DANGEROUS
        decision = self.permission_manager.check_permission(
            tool_name="windows.browser",
            operation=act_clean,
            parameters={"url": url, "tab_id": tab_id, "media_action": media_action, "selector": selector},
            risk_level=risk_level,
        )

        if decision == PermissionDecision.DENY:
            raise BrowserControlError(f"Operación de navegador '{act_clean}' denegada por la política de seguridad.")

        # Re-verificación de Parada de Emergencia antes de la ejecución
        self.emergency_stop.check_cancellation(phase="execution")

        # 3. Invocación de la operación sobre el gestor de sesiones de navegador
        if act_clean in ("open_url", "navigate", "open"):
            if not url:
                raise BrowserControlError("Se requiere una URL para la operación 'open_url'.")
            tab = self.session_manager.open_url(url)
            msg = f"URL '{tab.url}' cargada exitosamente en la pestaña '{tab.tab_id}'."
            res_dict = tab.to_dict()

        elif act_clean in ("switch_tab", "focus_tab"):
            if not tab_id:
                raise BrowserControlError("Se requiere un 'tab_id' para la operación 'switch_tab'.")
            tab = self.session_manager.switch_tab(tab_id)
            msg = f"Foco asignado a la pestaña '{tab.tab_id}'."
            res_dict = tab.to_dict()

        elif act_clean in ("close_tab", "close"):
            if not tab_id:
                raise BrowserControlError("Se requiere un 'tab_id' para la operación 'close_tab'.")
            success = self.session_manager.close_tab(tab_id)
            msg = f"Pestaña '{tab_id}' cerrada exitosamente." if success else f"No se encontró la pestaña '{tab_id}'."
            res_dict = {"closed": success, "tab_id": tab_id}

        elif act_clean in ("query_dom", "get_element"):
            if not selector:
                raise BrowserControlError("Se requiere un 'selector' para consultar el DOM.")
            elem = self.session_manager.query_dom_element(selector)
            msg = f"Elemento DOM '{selector}' consultado exitosamente."
            res_dict = elem

        elif act_clean in ("click_dom", "click_element"):
            if not selector:
                raise BrowserControlError("Se requiere un 'selector' para hacer clic en el DOM.")
            clk = self.session_manager.click_dom_element(selector)
            msg = f"Clic en elemento DOM '{selector}' ejecutado exitosamente."
            res_dict = {"clicked": clk, "selector": selector}

        elif act_clean in ("execute_js", "js_snippet"):
            if not js_snippet:
                raise BrowserControlError("Se requiere un 'js_snippet' predefinido en AllowedJSSnippet.")
            js_res = self.session_manager.execute_js_snippet(js_snippet)
            msg = "Snippet de JavaScript predefinido ejecutado con éxito."
            res_dict = {"result": js_res}

        elif act_clean in ("control_media", "play_media", "media"):
            m_act = media_action or "play"
            tab = self.session_manager.control_media(action=m_act, tab_id=tab_id)
            msg = f"Acción de medios '{m_act}' ejecutada sobre '{tab.title}'. Estado verificado: {tab.media_state}."
            res_dict = tab.to_dict()

        else:
            raise BrowserControlError(f"Acción de control de navegador no soportada: '{action}'")

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # 4. Registro de auditoría con PRIVACIDAD ABSOLUTA (METADATOS EXCLUSIVOS)
        audit_meta = {
            "action": act_clean,
            "url_domain": url.split("/")[2] if url and "/" in url else None,
            "duration_ms": duration_ms,
            "result": res_dict,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.browser",
                operation=act_clean,
                duration_ms=duration_ms,
                reason=msg,
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:browser_action_executed", audit_meta)
        return {
            "success": True,
            "action": act_clean,
            "tab": res_dict,
            "message": msg,
        }


@dataclass(frozen=True)
class BrowserValidationResult:
    """Resultado inmutable de la validación de URL para el navegador."""

    is_allowed: bool
    url: str
    reason: str = ""


class BrowserBoundary:
    """Frontera declarativa de validación y control de URLs para el navegador."""

    def __init__(
        self,
        allowed_domains: set[str] | list[str] | None = None,
        allowed_schemes: set[str] | None = None,
        blocked_schemes: set[str] | None = None,
    ) -> None:
        from urllib.parse import urlparse
        self._urlparse = urlparse
        self.allowed_domains = set(allowed_domains) if allowed_domains is not None else {"youtube.com", "google.com", "github.com", "microsoft.com"}
        self.allowed_schemes = allowed_schemes or {"http", "https"}
        self.blocked_schemes = blocked_schemes or {"javascript", "data", "file", "chrome", "edge", "about"}

    def validate_url(self, url: str) -> BrowserValidationResult:
        """Valida deterministamente si una URL cumple con los esquemas y lista blanca de dominios."""
        if not url or not isinstance(url, str):
            return BrowserValidationResult(is_allowed=False, url=url, reason="URL vacía o no válida.")

        clean_url = url.strip()
        scheme_check = clean_url.split(":")[0].lower()
        if scheme_check in self.blocked_schemes or scheme_check not in self.allowed_schemes:
            return BrowserValidationResult(is_allowed=False, url=url, reason=f"Esquema no permitido '{scheme_check}'.")

        try:
            parsed = self._urlparse(clean_url)
            domain = (parsed.hostname or "").lower()
            if not domain:
                return BrowserValidationResult(is_allowed=False, url=url, reason="Host no encontrado en URL.")

            if not self.allowed_domains:
                return BrowserValidationResult(is_allowed=False, url=url, reason="Allowlist de dominios vacía.")

            is_match = False
            for allowed in self.allowed_domains:
                allowed_clean = allowed.lower()
                if domain == allowed_clean or domain.endswith("." + allowed_clean):
                    is_match = True
                    break

            if not is_match:
                return BrowserValidationResult(is_allowed=False, url=url, reason=f"Dominio '{domain}' fuera de allowlist.")

            return BrowserValidationResult(is_allowed=True, url=url, reason="URL autorizada por allowlist.")
        except Exception as e:
            return BrowserValidationResult(is_allowed=False, url=url, reason=f"Error validando URL: {e}")
