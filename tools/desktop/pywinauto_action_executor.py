"""Ejecutor gobernado de acciones gráficas basado en pywinauto (Fase I4).

GARANTÍA ABSOLUTA DE SEGURIDAD Y GOBERNANZA:
1. SEPARADO DE IUIInspectionBackend: La inspección permanece 100% de sólo lectura.
2. NUNCA se autoautoriza: Requiere autorización explícita de políticas de JESSYCA.
3. Si la política deniega o la parada de emergencia está activa: CERO clicks, CERO pulsaciones de tecla.
4. Maneja ambigüedad y elementos desaparecidos/obsoletos (stale elements) limpiamente.
5. Inicializa y limpia COM (pythoncom) en el subproceso correspondiente.
6. Preserva coordenadas multi-monitor válidas (incluyendo valores negativos).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.desktop_automation_models import (
    DesktopActionMetadata,
    DesktopActionRequest,
    DesktopActionResult,
    DesktopActionType,
    generate_action_fingerprint,
)
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.exceptions import UIBackendUnavailableError
from core.logger import get_logger

logger = get_logger("jessyca.tools.desktop.pywinauto_action_executor")


def _init_com() -> bool:
    try:
        import pythoncom
        pythoncom.CoInitialize()
        return True
    except Exception:
        return False


def _uninit_com() -> None:
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:
        pass


class PyWinAutoGovernedActionExecutor:
    """Ejecutor gobernado de acciones UI sobre el escritorio mediante pywinauto.

    Toda acción física debe estar previamente autorizada y validada contra
    parada de emergencia y límites de seguridad.
    """

    def __init__(
        self,
        backend_type: str = "uia",
        emergency_stop_manager: EmergencyStopManager | None = None,
        policy_evaluator: Any | None = None,
    ) -> None:
        self.backend_type = backend_type
        self.emergency_stop = emergency_stop_manager or get_emergency_stop_manager()
        self.policy_evaluator = policy_evaluator

    def _ensure_pywinauto(self) -> Any:
        try:
            from pywinauto import Desktop
            return Desktop
        except ImportError as err:
            logger.warning("[PYWINAUTO EXECUTOR] Dependencia 'pywinauto' no instalada.")
            raise UIBackendUnavailableError("Dependencia 'pywinauto' no instalada.") from err

    def execute_action(
        self,
        request: DesktopActionRequest,
        request_id: str = "gov-req",
        authorized: bool = False,
    ) -> DesktopActionResult:
        """Ejecuta una acción física en el escritorio ÚNICAMENTE si está autorizada por JESSYCA.

        Si authorized=False y no hay un evaluador de política que apruebe la acción,
        la ejecución es DENEGADA INMEDIATAMENTE y se realizan CERO clicks.
        """
        start_t = datetime.now(UTC)

        # 1. Comprobación de Parada de Emergencia
        if self.emergency_stop.is_stopped():
            logger.warning(f"[PYWINAUTO EXECUTOR] Acción [{request.action_type.value}] abortada: Parada de Emergencia activa.")
            fp = generate_action_fingerprint(
                tool_name="windows.desktop.pywinauto",
                action_type=request.action_type.value,
                target_dict=request.target.to_dict(),
                arguments_dict={},
                request_id=request_id,
            )
            return DesktopActionResult(
                success=False,
                metadata=DesktopActionMetadata(
                    action_type=request.action_type.value,
                    target_summary=request.target.to_summary(),
                    action_fingerprint=fp,
                    processing_time_ms=0.0,
                    backend_name="PyWinAutoGovernedActionExecutor",
                    timestamp=start_t,
                ),
                message="EMERGENCY_STOP_ACTIVE: Acción abortada: Parada de Emergencia activa.",
            )

        # 2. Comprobación de Autorización / Política de Seguridad (CERO CLICKS ANTE DENEGACIÓN)
        is_permitted = authorized
        if not is_permitted and self.policy_evaluator:
            try:
                is_permitted = bool(self.policy_evaluator.is_authorized(request))
            except Exception as e:
                logger.error(f"[PYWINAUTO EXECUTOR] Error en evaluación de política: {e}")
                is_permitted = False

        if not is_permitted:
            logger.warning(
                f"[PYWINAUTO EXECUTOR] POLÍTICA DENEGADA: Acción [{request.action_type.value}] NO autorizada. "
                "CERO clicks ejecutados."
            )
            fp = generate_action_fingerprint(
                tool_name="windows.desktop.pywinauto",
                action_type=request.action_type.value,
                target_dict=request.target.to_dict(),
                arguments_dict={},
                request_id=request_id,
            )
            return DesktopActionResult(
                success=False,
                metadata=DesktopActionMetadata(
                    action_type=request.action_type.value,
                    target_summary=request.target.to_summary(),
                    action_fingerprint=fp,
                    processing_time_ms=0.5,
                    backend_name="PyWinAutoGovernedActionExecutor",
                    timestamp=start_t,
                ),
                message="POLICY_DENIED_ZERO_CLICKS: Acción denegada por política de seguridad de JESSYCA: no autorizada (CERO clicks realizados).",
            )

        # 3. Validar disponibilidad de la librería
        try:
            desktop_cls = self._ensure_pywinauto()
        except UIBackendUnavailableError as err:
            fp = generate_action_fingerprint(
                tool_name="windows.desktop.pywinauto",
                action_type=request.action_type.value,
                target_dict=request.target.to_dict(),
                arguments_dict={},
                request_id=request_id,
            )
            return DesktopActionResult(
                success=False,
                metadata=DesktopActionMetadata(
                    action_type=request.action_type.value,
                    target_summary=request.target.to_summary(),
                    action_fingerprint=fp,
                    processing_time_ms=0.0,
                    backend_name="PyWinAutoGovernedActionExecutor",
                    timestamp=start_t,
                ),
                message=f"BACKEND_UNAVAILABLE: {err}",
            )

        com_initialized = _init_com()
        try:
            desktop = desktop_cls(backend=self.backend_type)
            target = request.target
            op = request.action_type

            # 4. Localizar la ventana o elemento objetivo
            target_win = None
            if target.window_handle:
                try:
                    for win in desktop.windows():
                        if getattr(win, "handle", None) == target.window_handle:
                            target_win = win
                            break
                except Exception:
                    pass
            elif target.process_id:
                try:
                    for win in desktop.windows():
                        if getattr(win.element_info, "process_id", None) == target.process_id:
                            target_win = win
                            break
                except Exception:
                    pass
            elif target.name:
                matches: list[Any] = []
                for win in desktop.windows(visible_only=True):
                    try:
                        if target.name.lower() in (win.window_text() or "").lower():
                            matches.append(win)
                    except Exception:
                        continue
                if len(matches) > 1:
                    exact = [w for w in matches if (w.window_text() or "").strip().lower() == target.name.strip().lower()]
                    if len(exact) == 1:
                        target_win = exact[0]
                    else:
                        logger.warning(f"[PYWINAUTO EXECUTOR] Ambigüedad detectada para ventana '{target.name}'.")
                        fp = generate_action_fingerprint(
                            tool_name="windows.desktop.pywinauto",
                            action_type=op.value,
                            target_dict=target.to_dict(),
                            arguments_dict={},
                            request_id=request_id,
                        )
                        return DesktopActionResult(
                            success=False,
                            metadata=DesktopActionMetadata(
                                action_type=op.value,
                                target_summary=target.to_summary(),
                                action_fingerprint=fp,
                                processing_time_ms=1.0,
                                backend_name="PyWinAutoGovernedActionExecutor",
                                timestamp=start_t,
                            ),
                            message=f"AMBIGUOUS_TARGET: Se encontraron {len(matches)} ventanas coincidentes para '{target.name}'.",
                        )
                elif matches:
                    target_win = matches[0]

            # 5. Ejecutar la acción gobernada
            if op == DesktopActionType.FOCUS_WINDOW:
                if not target_win:
                    fp = generate_action_fingerprint(
                        tool_name="windows.desktop.pywinauto",
                        action_type=op.value,
                        target_dict=target.to_dict(),
                        arguments_dict={},
                        request_id=request_id,
                    )
                    return DesktopActionResult(
                        success=False,
                        metadata=DesktopActionMetadata(
                            action_type=op.value,
                            target_summary=target.to_summary(),
                            action_fingerprint=fp,
                            processing_time_ms=0.5,
                            backend_name="PyWinAutoGovernedActionExecutor",
                            timestamp=start_t,
                        ),
                        message="TARGET_NOT_FOUND_OR_STALE: Elemento obsoleto o ventana no encontrada para foco.",
                    )
                target_win.set_focus()

            elif op == DesktopActionType.CLICK_ELEMENT:
                # Coordenadas explícitas (soporte multi-monitor con coordenadas negativas)
                if target.x is not None and target.y is not None:
                    from pywinauto import mouse
                    mouse.click(coords=(target.x, target.y))
                elif target_win:
                    # Si hay automation_id específico, buscar el control hijo
                    if target.automation_id:
                        ctrl = target_win.child_window(auto_id=target.automation_id)
                        if not ctrl.exists(timeout=0.5):
                            fp = generate_action_fingerprint(
                                tool_name="windows.desktop.pywinauto",
                                action_type=op.value,
                                target_dict=target.to_dict(),
                                arguments_dict={},
                                request_id=request_id,
                            )
                            return DesktopActionResult(
                                success=False,
                                metadata=DesktopActionMetadata(
                                    action_type=op.value,
                                    target_summary=target.to_summary(),
                                    action_fingerprint=fp,
                                    processing_time_ms=0.5,
                                    backend_name="PyWinAutoGovernedActionExecutor",
                                    timestamp=start_t,
                                ),
                                message=f"STALE_OR_MISSING_CONTROL: Control con auto_id '{target.automation_id}' no encontrado o destruido.",
                            )
                        ctrl.click_input()
                    else:
                        target_win.click_input()
                else:
                    fp = generate_action_fingerprint(
                        tool_name="windows.desktop.pywinauto",
                        action_type=op.value,
                        target_dict=target.to_dict(),
                        arguments_dict={},
                        request_id=request_id,
                    )
                    return DesktopActionResult(
                        success=False,
                        metadata=DesktopActionMetadata(
                            action_type=op.value,
                            target_summary=target.to_summary(),
                            action_fingerprint=fp,
                            processing_time_ms=0.5,
                            backend_name="PyWinAutoGovernedActionExecutor",
                            timestamp=start_t,
                        ),
                        message="TARGET_NOT_FOUND_OR_STALE: Objetivo no encontrado o destruido para clic.",
                    )

            elif op == DesktopActionType.TYPE_TEXT:
                if request.text is None:
                    raise ValueError("Se requiere texto para type_text.")
                from pywinauto import keyboard
                keyboard.send_keys(request.text, with_spaces=True)

            elif op == DesktopActionType.DRAG_AND_DROP:
                if target.x is None or target.y is None or request.dest_x is None or request.dest_y is None:
                    raise ValueError("Se requieren coordenadas de origen y destino para drag_and_drop.")
                from pywinauto import mouse
                mouse.press(coords=(target.x, target.y))
                mouse.release(coords=(request.dest_x, request.dest_y))

            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            fp = generate_action_fingerprint(
                tool_name="windows.desktop.pywinauto",
                action_type=op.value,
                target_dict=target.to_dict(),
                arguments_dict={"text_len": len(request.text)} if request.text else {},
                request_id=request_id,
            )

            return DesktopActionResult(
                success=True,
                metadata=DesktopActionMetadata(
                    action_type=op.value,
                    target_summary=target.to_summary(),
                    action_fingerprint=fp,
                    processing_time_ms=proc_ms,
                    backend_name="PyWinAutoGovernedActionExecutor",
                    timestamp=start_t,
                ),
                message=f"Acción gobernada '{op.value}' ejecutada exitosamente vía pywinauto.",
            )

        except Exception as e:
            logger.warning(f"[PYWINAUTO EXECUTOR FAIL-SAFE] Fallo durante la ejecución: {e}")
            proc_ms = (datetime.now(UTC) - start_t).total_seconds() * 1000
            fp = generate_action_fingerprint(
                tool_name="windows.desktop.pywinauto",
                action_type=request.action_type.value,
                target_dict=request.target.to_dict(),
                arguments_dict={},
                request_id=request_id,
            )
            return DesktopActionResult(
                success=False,
                metadata=DesktopActionMetadata(
                    action_type=request.action_type.value,
                    target_summary=request.target.to_summary(),
                    action_fingerprint=fp,
                    processing_time_ms=proc_ms,
                    backend_name="PyWinAutoGovernedActionExecutor",
                    timestamp=start_t,
                ),
                message=f"Fallo durante la ejecución vía pywinauto: {e}",
                error_message=str(e),
            )
        finally:
            if com_initialized:
                _uninit_com()
