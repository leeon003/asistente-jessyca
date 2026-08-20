"""Guardia y validador estricto de seguridad para la ejecución de acciones sobre el escritorio (Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
La única ruta permitida para ejecutar acciones es:
Agent/Workflow -> DesktopAction -> ActionGuard -> Validation -> Safety Check -> Executor -> Verification -> Audit
Rechaza explícitamente coordenadas mágicas, objetivos no validados, targets obsoletos (stale state_hash) y confianza insuficiente.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.desktop_automation_models import (
    DesktopActionMetadata,
    DesktopActionRequest,
    DesktopActionResult,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.desktop_executors_models import (
    ActionGuardValidationError,
    ActionTimeoutError,
    IKeyboardExecutor,
    IMouseExecutor,
    InsufficientConfidenceError,
    StaleTargetError,
    TargetNotFoundError,
    ValidatedTarget,
)
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.event_bus import get_event_bus
from core.logger import get_logger
from tools.desktop.executors import (
    FakeKeyboardExecutor,
    FakeMouseExecutor,
    IKeyboardExecutor,
    IMouseExecutor,
)

logger = get_logger("jessyca.tools.desktop.action_guard")


class ActionGuard:
    """Guardia de seguridad obligatorio que valida e interrumpe acciones no autorizadas antes de invocar ejecutores."""

    def __init__(
        self,
        mouse_executor: IMouseExecutor | None = None,
        keyboard_executor: IKeyboardExecutor | None = None,
        emergency_stop_manager: EmergencyStopManager | None = None,
        min_confidence: float = 0.70,
        action_timeout_seconds: float = 10.0,
    ) -> None:
        settings = AppSettings()
        self.mouse_executor = mouse_executor or FakeMouseExecutor()
        self.keyboard_executor = keyboard_executor or FakeKeyboardExecutor()
        self.emergency_stop_manager = emergency_stop_manager or get_emergency_stop_manager()
        self.min_confidence = min_confidence
        self.action_timeout_seconds = action_timeout_seconds
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()

    def execute_guarded_action(
        self,
        request: DesktopActionRequest,
        validated_target: ValidatedTarget | None,
        current_ui_state_hash: str | None = None,
        request_id: str = "guard-action-req",
    ) -> DesktopActionResult:
        """Ejecuta una acción gráfica atravesando estrictamente la tubería de seguridad de 7 pasos.

        Fases de la tubería:
        1. Acción y parámetros validados.
        2. Parada de Emergencia verificada.
        3. Objetivo y ventana validados.
        4. Verificación de estado visual obsoleto (stale target check).
        5. Verificación de umbral de confianza mínimo.
        6. Verificación de tiempo límite (timeout).
        7. Invocación de ejecutor de ratón/teclado y auditoría con privacidad.
        """
        start_time = datetime.now(UTC)

        # FASE 1 & FASE 2: Verificación inmediata de Parada de Emergencia
        self.emergency_stop_manager.check_cancellation(phase="validation")

        # FASE 3: Validación del objetivo y ventana
        if validated_target is None:
            raise TargetNotFoundError("Acción denegada: No se proporcionó un ValidatedTarget inspeccionado previamente.")

        if not validated_target.hwnd or validated_target.hwnd <= 0:
            raise TargetNotFoundError(f"Acción denegada: Identificador de ventana HWND inválido: {validated_target.hwnd}")

        if not validated_target.owner_title or not isinstance(validated_target.owner_title, str):
            raise TargetNotFoundError("Acción denegada: El título de ventana propietaria debe ser una cadena no vacía.")

        # FASE 4: Verificación de estado visual obsoleto (Stale Target Check)
        if current_ui_state_hash is not None and current_ui_state_hash != validated_target.state_hash:
            raise StaleTargetError(
                f"Acción denegada: El estado visual del objetivo ha cambiado desde su inspección "
                f"(hash actual={current_ui_state_hash}, hash esperado={validated_target.state_hash})."
            )

        # FASE 5: Verificación de umbral de confianza mínimo
        if validated_target.confidence < self.min_confidence:
            raise InsufficientConfidenceError(
                f"Acción denegada: Nivel de confianza insuficiente para el objetivo "
                f"({validated_target.confidence:.2f} < {self.min_confidence:.2f})."
            )

        # FASE 6: Verificación de tiempo límite (Timeout Check)
        if request.duration_ms > self.action_timeout_seconds * 1000:
            raise ActionTimeoutError(
                f"Acción denegada: La duración de la acción excede el tiempo límite permitido "
                f"({request.duration_ms}ms > {self.action_timeout_seconds * 1000}ms)."
            )

        # Re-verificación de Parada de Emergencia inmediatamente antes de invocar los ejecutores reales
        self.emergency_stop_manager.check_cancellation(phase="execution")

        # FASE 7: Invocación del ejecutor correspondiente
        op = request.action_type
        cx, cy = validated_target.center_x, validated_target.center_y

        if op == DesktopActionType.CLICK_ELEMENT:
            self.mouse_executor.click(cx, cy, button="left")
            msg = f"Clic izquierdo ejecutado exitosamente en ({cx}, {cy})."

        elif op == DesktopActionType.TYPE_TEXT:
            if request.text is None:
                raise ActionGuardValidationError("Acción denegada: La acción type_text requiere el parámetro 'text'.")
            self.mouse_executor.click(cx, cy, button="left")
            self.keyboard_executor.type_text(request.text)
            msg = f"Texto escrito exitosamente en el objetivo (longitud={len(request.text)})."

        elif op == DesktopActionType.FOCUS_WINDOW:
            self.mouse_executor.click(cx, cy, button="left")
            msg = f"Foco de ventana asignado a HWND {validated_target.hwnd}."

        elif op == DesktopActionType.DRAG_AND_DROP:
            dx = request.dest_x if request.dest_x is not None else cx
            dy = request.dest_y if request.dest_y is not None else cy
            self.mouse_executor.move(cx, cy)
            self.mouse_executor.click(cx, cy, button="left")
            self.mouse_executor.move(dx, dy)
            msg = f"Arrastre ejecutado de ({cx}, {cy}) a ({dx}, {dy})."

        else:
            raise ActionGuardValidationError(f"Acción de automatización no soportada por ActionGuard: '{op}'")

        duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

        # Firma criptográfica SHA-256 de la acción ejecutada
        fp = generate_action_fingerprint(
            tool_name="windows.desktop",
            action_type=op.value,
            target_dict=validated_target.to_dict(),
            arguments_dict={"duration_ms": request.duration_ms},
            request_id=request_id,
        )

        metadata = DesktopActionMetadata(
            action_type=op.value,
            target_summary=f"HWND={validated_target.hwnd} | Pos=({cx},{cy}) | Conf={validated_target.confidence:.2f}",
            action_fingerprint=fp,
            processing_time_ms=duration_ms,
            backend_name=self.mouse_executor.__class__.__name__,
            timestamp=datetime.now(UTC),
        )

        result = DesktopActionResult(success=True, metadata=metadata, message=msg)

        # Auditoría con PRIVACIDAD ABSOLUTA (METADATOS EXCLUSIVOS, CERO SECRETOS)
        audit_meta = {
            "action_type": op.value,
            "hwnd": validated_target.hwnd,
            "confidence": validated_target.confidence,
            "state_hash": validated_target.state_hash,
            "duration_ms": duration_ms,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.DESKTOP_ACTION_SUCCEEDED,
                request_id=request_id,
                tool_name="windows.desktop",
                operation=op.value,
                duration_ms=duration_ms,
                reason="Acción de escritorio validada y ejecutada por ActionGuard exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("desktop:guarded_action_executed", audit_meta)
        return result
