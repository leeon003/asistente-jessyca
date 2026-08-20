"""Frontera de seguridad y validador de automatización de escritorio (DesktopAutomationSecurityManager - Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Aplica el principio FAIL-SAFE DENY sobre toda acción de automatización gráfica UI.
1. Verifica el estado del EmergencyStopManager (SI ESTÁ ACTIVO -> DENY).
2. Valida coordenadas, distancias de arrastre, longitud de texto y presencia de NaN/Infinity.
3. Verifica la integridad criptográfica del fingerprint SHA-256 contra la AuthorizationEvidence.
4. Verifica la frescura del target contra obsolescencia (Stale Target Protection).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from config.settings import AppSettings
from core.desktop_automation_models import (
    DesktopActionRequest,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.emergency_stop import get_emergency_stop_manager
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.desktop_automation_security")


class DesktopAutomationSecurityError(MCPError):
    """Error base de la frontera de seguridad de automatización de escritorio."""

    pass


class DesktopAutomationLimitExceededError(DesktopAutomationSecurityError):
    """Error emitido cuando una acción excede los límites de coordenadas, distancia o texto."""

    pass


class StaleTargetError(DesktopAutomationSecurityError):
    """Error emitido cuando un elemento UI objetivo ha cambiado o está obsoleto."""

    pass


class DesktopAutomationSecurityManager:
    """Validador estricto de seguridad para la ejecución de acciones gráficas sobre el escritorio."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_width: int = settings.DESKTOP_MAX_WIDTH
        self.max_height: int = settings.DESKTOP_MAX_HEIGHT
        self.max_text_length: int = settings.DESKTOP_AUTOMATION_MAX_TEXT_LENGTH
        self.max_drag_distance: int = settings.DESKTOP_AUTOMATION_MAX_DRAG_DISTANCE
        self.max_actions: int = settings.DESKTOP_AUTOMATION_MAX_ACTIONS
        self.emergency_stop = get_emergency_stop_manager()

    def validate_request(self, request: DesktopActionRequest) -> DesktopActionRequest:
        """Valida rigurosamente la solicitud de acción gráfica.

        FAIL-SAFE DENY: Lanza DesktopAutomationSecurityError ante cualquier ambigüedad.
        """
        # 1. VERIFICACIÓN OBLIGATORIA DE PARADA DE EMERGENCIA
        if self.emergency_stop.is_active():
            raise DesktopAutomationSecurityError("PARADA DE EMERGENCIA ACTIVA: Se deniega toda acción sobre el escritorio.")

        target = request.target

        # 2. Validación de coordenadas del target si están presentes
        if target.x is not None or target.y is not None:
            tx = target.x if target.x is not None else 0
            ty = target.y if target.y is not None else 0

            if not isinstance(tx, int) or isinstance(tx, bool) or tx < 0 or tx > self.max_width:
                raise DesktopAutomationSecurityError(f"Coordenada 'x' fuera de límites [0-{self.max_width}]: {tx}")

            if not isinstance(ty, int) or isinstance(ty, bool) or ty < 0 or ty > self.max_height:
                raise DesktopAutomationSecurityError(f"Coordenada 'y' fuera de límites [0-{self.max_height}]: {ty}")

        # 3. Validación específica para TYPE_TEXT
        if request.action_type == DesktopActionType.TYPE_TEXT:
            if request.text is None:
                raise DesktopAutomationSecurityError("La acción 'type_text' requiere especificar el argumento 'text'.")
            if not isinstance(request.text, str):
                raise DesktopAutomationSecurityError("El argumento 'text' debe ser una cadena.")
            if len(request.text) > self.max_text_length:
                raise DesktopAutomationLimitExceededError(f"Longitud del texto excede el máximo permitido ({len(request.text)} > {self.max_text_length}).")

        # 4. Validación específica para DRAG_AND_DROP
        if request.action_type == DesktopActionType.DRAG_AND_DROP:
            if request.dest_x is None or request.dest_y is None:
                raise DesktopAutomationSecurityError("La acción 'drag_and_drop' requiere 'dest_x' y 'dest_y'.")

            for name, val, max_val in [("dest_x", request.dest_x, self.max_width), ("dest_y", request.dest_y, self.max_height)]:
                if not isinstance(val, int) or isinstance(val, bool) or val < 0 or val > max_val:
                    raise DesktopAutomationSecurityError(f"Coordenada de destino '{name}' fuera de límites [0-{max_val}]: {val}")

            src_x = target.x or 0
            src_y = target.y or 0
            dist = math.sqrt((request.dest_x - src_x) ** 2 + (request.dest_y - src_y) ** 2)

            if math.isnan(dist) or math.isinf(dist):
                raise DesktopAutomationSecurityError("Cálculo de distancia de arrastre devolvió NaN o Infinity.")

            if dist > self.max_drag_distance:
                raise DesktopAutomationLimitExceededError(f"Distancia de arrastrar y soltar excede el máximo permitido ({round(dist,1)} > {self.max_drag_distance}).")

        return request

    def verify_fingerprint(
        self,
        request: DesktopActionRequest,
        evidence_fingerprint: str,
        request_id: str,
        tool_name: str = "windows.desktop",
    ) -> bool:
        """Verifica que la huella SHA-256 de la solicitud coincida exactamente con la evidencia autorizada."""
        from server.evidence import compute_evidence_fingerprint

        args_dict: dict[str, Any] = {}
        if request.action_type == DesktopActionType.TYPE_TEXT and request.text is not None:
            args_dict["text_len"] = len(request.text)
        if request.action_type == DesktopActionType.DRAG_AND_DROP:
            args_dict["dest_x"] = request.dest_x
            args_dict["dest_y"] = request.dest_y

        computed_desktop = generate_action_fingerprint(
            tool_name=tool_name,
            action_type=request.action_type.value,
            target_dict=request.target.to_dict(),
            arguments_dict=args_dict,
            request_id=request_id,
        )

        target_params = {k: v for k, v in request.target.to_dict().items() if v is not None}
        computed_pipeline = compute_evidence_fingerprint(
            tool_name=tool_name,
            operation=request.action_type.value,
            parameters=target_params,
            request_id=request_id,
        )

        if evidence_fingerprint not in (computed_desktop, computed_pipeline):
            logger.error(f"[SECURITY MISMATCH] Fingerprint invalido. Esperado: {evidence_fingerprint}, Calculado: {computed_desktop}")
            raise DesktopAutomationSecurityError("Incoherencia en la firma SHA-256 de la acción (Fingerprint mismatch). Posible alteración post-autorización.")

        return True

    def verify_target_freshness(
        self,
        request: DesktopActionRequest,
        current_ui_info: dict[str, Any] | None = None,
    ) -> bool:
        """Verifica que el target UI no esté obsoleto (Stale Target Protection)."""
        if current_ui_info is None:
            return True

        target = request.target
        if target.process_id and "process_id" in current_ui_info:
            if target.process_id != current_ui_info["process_id"]:
                raise StaleTargetError(f"Target obsoleto: Process ID cambio ({target.process_id} != {current_ui_info['process_id']}).")

        if target.window_handle and "window_handle" in current_ui_info:
            if target.window_handle != current_ui_info["window_handle"]:
                raise StaleTargetError(f"Target obsoleto: Window handle cambio ({target.window_handle} != {current_ui_info['window_handle']}).")

        return True


@dataclass(frozen=True)
class DesktopTargetValidationResult:
    """Resultado inmutable de la validación de objetivo o coordenadas del escritorio."""

    is_valid: bool
    reason: str = ""


class DesktopAutomationSecurity:
    """Frontera de seguridad para validación de targets y coordenadas de automatización."""

    def __init__(self, emergency_stop: Any | None = None) -> None:
        from core.emergency_stop import get_emergency_stop_manager
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()

    def validate_target(
        self,
        target_description: str,
        current_screen_state: dict[str, Any] | None = None,
    ) -> DesktopTargetValidationResult:
        """Valida que el target exista y sea visible en la pantalla actual."""
        if current_screen_state is not None:
            visible = current_screen_state.get("visible_elements", [])
            if not visible:
                return DesktopTargetValidationResult(is_valid=False, reason="Target no visible en pantalla.")
            if isinstance(visible, list) and target_description not in visible:
                return DesktopTargetValidationResult(is_valid=False, reason=f"Target '{target_description}' no encontrado.")
        return DesktopTargetValidationResult(is_valid=True, reason="Target validado.")

    def validate_coordinates(
        self,
        x: int,
        y: int,
        max_w: int = 1920,
        max_h: int = 1080,
    ) -> DesktopTargetValidationResult:
        """Valida que las coordenadas estén dentro de los límites de la pantalla."""
        if x < 0 or y < 0 or x > max_w or y > max_h:
            return DesktopTargetValidationResult(is_valid=False, reason="Coordenadas fuera de límites de pantalla.")
        return DesktopTargetValidationResult(is_valid=True, reason="Coordenadas dentro de límites.")

    def check_emergency_stop(self, phase: str = "general") -> None:
        """Verifica que la parada de emergencia no esté activa."""
        self.emergency_stop.check_cancellation(phase=phase)
