"""Adaptador de Ejecución y Verificación Obligatoria para JESSYCA 4.0 (Fase 70).

Implementa la regla fundamental:
    "UNA ACCIÓN NO SE CONSIDERA COMPLETADA HASTA QUE SU RESULTADO HAYA SIDO
    VERIFICADO O DECLARADO EXPLÍCITAMENTE COMO NO VERIFICABLE."

Flujo obligatorio:
    INTENT
      ↓
    SECURITY / CONFIRMATION
      ↓
    EXECUTION
      ↓
    VERIFICATION
      ↓
    RESPONSE

Garantías:
1. Anti-False Success: Ninguna acción se declara exitosa sin evidencia verificable.
2. Estados canónicos de verificación: VERIFIED, FAILED, NOT_VERIFIABLE.
3. State Machine estricta: EXECUTING -> VERIFYING -> RESPONDING.
4. Event Bus: Publicación de exactamente UN evento VerificationResult por acción.
5. Aislamiento de excepciones: Fallos en verificador producen NOT_VERIFIABLE o FAILED, nunca VERIFIED.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from core.bus import EventBus, get_event_bus
from core.events.base import (
    ActionProposed,
    SpeakRequested,
    VerificationResult,
)
from core.execution.execution_verifier import (
    ExecutionVerifier,
    get_execution_verifier,
)
from core.execution.post_execution_verifier import (
    PostExecutionVerifier,
)
from core.logger import get_logger
from core.state.machine import StateMachine
from core.state.states import SessionState

logger = get_logger("jessyca.core.execution.verification_adapter")


class VerificationStatus(StrEnum):
    """Estados canónicos de verificación post-ejecución (Fase 70)."""

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"


# Alias legibles para respuestas al usuario
APP_LABELS: dict[str, str] = {
    "notepad": "Bloc de notas",
    "notepad.exe": "Bloc de notas",
    "bloc de notas": "Bloc de notas",
    "calc": "la Calculadora",
    "calc.exe": "la Calculadora",
    "calculadora": "la Calculadora",
    "mspaint": "Paint",
    "paint": "Paint",
    "explorer": "el Explorador de archivos",
    "explorador": "el Explorador de archivos",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "edge": "Microsoft Edge",
    "cmd": "el Símbolo del sistema",
    "terminal": "la Terminal",
}


def _humanize_app(target: str) -> str:
    """Convierte identificadores de aplicación a nombres amigables en español."""
    cleaned = (target or "").strip().lower()
    base = cleaned[:-4] if cleaned.endswith(".exe") else cleaned
    return APP_LABELS.get(base, APP_LABELS.get(cleaned, target or "la aplicación"))


class ActionVerificationAdapter:
    """Adaptador que orquesta la ejecución y verificación obligatoria de acciones."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        state_machine: StateMachine | None = None,
        execution_verifier: ExecutionVerifier | None = None,
        post_verifier: PostExecutionVerifier | None = None,
        executor_fn: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._state_machine = state_machine
        self._execution_verifier = execution_verifier or get_execution_verifier()
        self._post_verifier = post_verifier or PostExecutionVerifier(verifier=self._execution_verifier)
        self._executor_fn = executor_fn

        self._started = False
        self._lock = threading.RLock()
        self._processed_events: set[str] = set()

    @property
    def is_started(self) -> bool:
        return self._started

    def start(self) -> None:
        """Inicia el adaptador suscribiéndose a ActionProposed."""
        with self._lock:
            if self._started:
                return
            self._event_bus.subscribe(ActionProposed, self.on_action_proposed)
            self._started = True
            logger.info("[ACTION_VERIFICATION_ADAPTER] Suscrito a ActionProposed.")

    def stop(self) -> None:
        """Detiene el adaptador desuscribiéndose del Event Bus."""
        with self._lock:
            if not self._started:
                return
            self._event_bus.unsubscribe(ActionProposed, self.on_action_proposed)
            self._started = False
            logger.info("[ACTION_VERIFICATION_ADAPTER] Detenido y desuscrito.")

    def __enter__(self) -> ActionVerificationAdapter:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    async def __aenter__(self) -> ActionVerificationAdapter:
        self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _extract_target(self, action_name: str, parameters: dict[str, Any]) -> str:
        """Extrae el target principal (app, archivo, etc.) de los parámetros."""
        return str(
            parameters.get("app_name")
            or parameters.get("target")
            or parameters.get("nombre_app")
            or parameters.get("app")
            or parameters.get("path")
            or parameters.get("filename")
            or parameters.get("query")
            or action_name
        )

    def _determine_action_type(
        self, action_name: str, parameters: dict[str, Any]
    ) -> tuple[str, bool]:
        """Identifica el tipo de acción y si es potencialmente verificable de forma determinista.

        Retorna:
            (operation_type, is_verifiable)
        """
        act_norm = (action_name or "").lower().replace("_", ".")
        param_act = str(parameters.get("accion") or parameters.get("action") or "").lower()

        # 1. Cierre de aplicaciones
        if (
            "close" in act_norm
            or "cerrar" in act_norm
            or "kill" in act_norm
            or "terminate" in act_norm
            or param_act in ("close", "cerrar", "kill", "terminate")
        ):
            return "close_application", True

        # 2. Apertura de aplicaciones
        if (
            "open" in act_norm
            or "abrir" in act_norm
            or "launch" in act_norm
            or "windows.apps" in act_norm
            or "apps.open" in act_norm
            or param_act in ("open", "abrir", "launch")
        ):
            return "open_application", True

        # 3. Captura de pantalla
        if (
            "screenshot" in act_norm
            or "pantalla" in act_norm
            or "windows.screenshot" in act_norm
        ):
            return "screenshot", True

        # 4. Operaciones de archivos
        if any(k in act_norm for k in ("file", "archivo", "create", "write", "guardar")):
            return "file_operation", True

        # 5. Media / Volumen (no verificable salvo sensor explícito)
        if any(k in act_norm for k in ("media", "volume", "volumen", "mute", "unmute")):
            return "media_operation", False

        # 6. Acciones genéricas
        return "generic", False

    def _execute_internal(
        self, action_name: str, parameters: dict[str, Any]
    ) -> tuple[bool, Any, str | None]:
        """Ejecuta la acción a través del executor inyectado o mecanismo por defecto."""
        if self._executor_fn is not None:
            try:
                res = self._executor_fn(action_name, parameters)
                if isinstance(res, dict):
                    success = bool(res.get("exito", res.get("success", True)))
                    err = res.get("error") or res.get("mensaje") if not success else None
                    return success, res, err
                elif isinstance(res, bool):
                    return res, res, None if res else "Executor returned False"
                return True, res, None
            except Exception as exc:
                logger.error(f"[EXECUTION EXCEPTION] {exc}", exc_info=True)
                return False, None, str(exc)

        # Fallback a AppsSkill si corresponde a windows.apps
        op_type, _ = self._determine_action_type(action_name, parameters)
        if op_type in ("open_application", "close_application"):
            try:
                from skills.apps_skill import WindowsAppsSkill

                skill = WindowsAppsSkill()
                params = dict(parameters)
                if op_type == "open_application" and "accion" not in params:
                    params["accion"] = "abrir"
                elif op_type == "close_application" and "accion" not in params:
                    params["accion"] = "cerrar"
                res = skill.ejecutar(params)
                success = bool(res.get("exito", False))
                err = res.get("mensaje") if not success else None
                return success, res, err
            except Exception as exc:
                logger.warning(f"[EXECUTION FALLBACK ERROR] {exc}")
                return False, None, str(exc)

        # Ejecución simulada por defecto si no hay executor
        return True, {"action": action_name, "executed": True}, None

    def _verify_real_effect(
        self,
        op_type: str,
        target: str,
        parameters: dict[str, Any],
        exec_output: Any,
    ) -> tuple[VerificationStatus, bool, dict[str, Any], str]:
        """Comprueba el efecto real post-ejecución sobre el sistema operativo.

        Retorna:
            (status, verified, evidence_dict, message)
        """
        human_target = _humanize_app(target)

        if op_type == "open_application":
            ev = self._execution_verifier.verify_execution(
                action="open_application",
                target=target,
                parameters=parameters,
                timeout_seconds=2.0,
            )
            evidence = ev.to_dict()
            if ev.is_verified:
                msg = f"Listo, {human_target} está abierto."
                return VerificationStatus.VERIFIED, True, evidence, msg
            else:
                msg = f"No pude abrir {human_target}."
                return VerificationStatus.FAILED, False, evidence, msg

        elif op_type == "close_application":
            ev = self._execution_verifier.verify_execution(
                action="close_application",
                target=target,
                parameters=parameters,
                timeout_seconds=2.0,
            )
            evidence = ev.to_dict()
            if ev.is_verified:
                msg = f"Listo, {human_target} está cerrado."
                return VerificationStatus.VERIFIED, True, evidence, msg
            else:
                msg = f"No pude cerrar {human_target}."
                return VerificationStatus.FAILED, False, evidence, msg

        elif op_type == "screenshot":
            path_val = (
                parameters.get("path")
                or parameters.get("filename")
                or (exec_output.get("path") if isinstance(exec_output, dict) else None)
            )
            if path_val:
                exists = os.path.exists(path_val)
                size_bytes = os.path.getsize(path_val) if exists and os.path.isfile(path_val) else 0
                evidence = {
                    "file_exists": exists,
                    "path": str(path_val),
                    "size_bytes": size_bytes,
                }
                if exists and size_bytes > 0:
                    return VerificationStatus.VERIFIED, True, evidence, "Listo, captura de pantalla guardada y verificada."
                else:
                    return VerificationStatus.FAILED, False, evidence, "No pude guardar la captura de pantalla."
            elif isinstance(exec_output, dict) and exec_output.get("exito"):
                # Captura en memoria verificada
                evidence = {"in_memory": True, "size": len(str(exec_output.get("analisis", "")))}
                return VerificationStatus.VERIFIED, True, evidence, "Listo, pantalla capturada y analizada con éxito."
            else:
                evidence = {"reason": "No screenshot file or image data generated"}
                return VerificationStatus.FAILED, False, evidence, "No pude realizar la captura de pantalla."

        elif op_type == "file_operation":
            path_val = parameters.get("path") or parameters.get("filename") or target
            ev = self._execution_verifier.verify_execution(
                action="file_exists",
                target=str(path_val),
                parameters=parameters,
            )
            evidence = ev.to_dict()
            if ev.is_verified:
                return VerificationStatus.VERIFIED, True, evidence, f"Listo, archivo verificado en {path_val}."
            else:
                return VerificationStatus.FAILED, False, evidence, f"No se encontró el archivo en {path_val}."

        # Para acciones no verificables
        evidence = {"verifiable": False, "reason": "No deterministic verification sensor available"}
        msg = "La acción se ejecutó, pero no pude verificar el resultado."
        return VerificationStatus.NOT_VERIFIABLE, False, evidence, msg

    async def on_action_proposed(self, event: ActionProposed) -> None:
        """Handler asíncrono para eventos ActionProposed.

        Orquesta de forma rigurosa:
        1. Comprobación de seguridad/confirmación previa.
        2. Transición de State Machine: EXECUTING.
        3. Ejecución de la acción.
        4. Transición de State Machine: VERIFYING (obligatoria tanto si éxito como si fallo).
        5. Verificación del efecto real en el sistema.
        6. Publicación de exactamente UN evento VerificationResult con evidencia.
        7. Transición de State Machine: RESPONDING.
        8. Publicación de SpeakRequested con la respuesta apropiada.
        """
        # Deduplicación por event_id y action_id (Fase 75.1-B)
        action_id = getattr(event, "action_id", None) or str((event.parameters or {}).get("action_id") or event.event_id)
        if event.event_id in self._processed_events or (action_id and action_id in self._processed_events):
            logger.debug(f"[ACTION_VERIFICATION_ADAPTER] Evento o acción duplicada ignorada: event_id={event.event_id} action_id={action_id}")
            return
        self._processed_events.add(event.event_id)
        if action_id:
            self._processed_events.add(action_id)

        action_name = event.action_name
        parameters = dict(event.parameters or {})
        if action_id and "action_id" not in parameters:
            parameters["action_id"] = action_id
        session_id = event.session_id or "default_session"
        metadata = event.metadata or {}
        intent_name = str(metadata.get("intent") or action_name)
        target = self._extract_target(action_name, parameters)
        human_target = _humanize_app(target)

        logger.info(
            f"[ACTION_VERIFICATION_ADAPTER] Procesando acción: '{action_name}' action_id='{action_id}' "
            f"target='{target}' (session_id={session_id})"
        )

        # ── 1. SEGURIDAD Y CONFIRMACIÓN ──
        if metadata.get("requires_confirmation") is True:
            logger.info(f"[SECURITY/CONFIRMATION] Acción '{action_name}' requiere confirmación explícita.")
            if self._state_machine is not None and self._state_machine.can_transition_to(SessionState.CONFIRMING):
                self._state_machine.transition_to(SessionState.CONFIRMING)
            return

        # ── 2. TRANSICIÓN A EXECUTING ──
        if self._state_machine is not None:
            curr = self._state_machine.current_state
            if curr != SessionState.EXECUTING:
                if self._state_machine.can_transition_to(SessionState.EXECUTING):
                    self._state_machine.transition_to(SessionState.EXECUTING)
                elif curr == SessionState.IDLE:
                    self._state_machine.transition_to(SessionState.WAKEWORD)
                    self._state_machine.transition_to(SessionState.LISTENING)
                    self._state_machine.transition_to(SessionState.TRANSCRIBING)
                    self._state_machine.transition_to(SessionState.ROUTING)
                    self._state_machine.transition_to(SessionState.EXECUTING)

        # ── 3. EJECUCIÓN ──
        exec_success, exec_output, exec_error = self._execute_internal(action_name, parameters)

        # ── 4. TRANSICIÓN OBLIGATORIA A VERIFYING ──
        # La regla 5 exige: EXECUTING -> VERIFYING -> RESPONDING (incluso si la ejecución falla)
        if self._state_machine is not None:
            if self._state_machine.can_transition_to(SessionState.VERIFYING):
                self._state_machine.transition_to(SessionState.VERIFYING)

        # ── 5. VERIFICACIÓN DEL EFECTO REAL ──
        op_type, is_verifiable = self._determine_action_type(action_name, parameters)

        status: VerificationStatus
        verified: bool
        evidence: dict[str, Any]
        response_message: str

        if not exec_success:
            # Si la ejecución falló, la verificación confirma el fallo
            status = VerificationStatus.FAILED
            verified = False
            evidence = {
                "execution_succeeded": False,
                "error": exec_error,
                "op_type": op_type,
            }
            if op_type == "close_application":
                response_message = f"No pude cerrar {human_target}."
            elif op_type == "open_application":
                response_message = f"No pude abrir {human_target}."
            else:
                response_message = f"No pude completar la acción {action_name}."
        elif not is_verifiable:
            # Acción ejecutada pero sin sensor de verificación determinista
            status = VerificationStatus.NOT_VERIFIABLE
            verified = False
            evidence = {
                "verifiable": False,
                "reason": "No deterministic verification sensor available",
                "op_type": op_type,
            }
            response_message = "La acción se ejecutó, pero no pude verificar el resultado."
        else:
            # Acción ejecutable y verificable: inspeccionar efecto real
            try:
                # Si exec_output ya trae evidencia directa de AppsSkill
                if (
                    isinstance(exec_output, dict)
                    and "evidence" in exec_output
                    and isinstance(exec_output["evidence"], dict)
                ):
                    ev_dict = exec_output["evidence"]
                    is_ev_verified = bool(ev_dict.get("is_verified", False))
                    evidence = ev_dict
                    if is_ev_verified:
                        status = VerificationStatus.VERIFIED
                        verified = True
                        if op_type == "open_application":
                            response_message = f"Listo, {human_target} está abierto."
                        elif op_type == "close_application":
                            response_message = f"Listo, {human_target} está cerrado."
                        else:
                            response_message = f"Listo, {action_name} verificado."
                    else:
                        status = VerificationStatus.FAILED
                        verified = False
                        if op_type == "close_application":
                            response_message = f"No pude cerrar {human_target}."
                        else:
                            response_message = f"No pude abrir {human_target}."
                else:
                    status, verified, evidence, response_message = self._verify_real_effect(
                        op_type=op_type,
                        target=target,
                        parameters=parameters,
                        exec_output=exec_output,
                    )
            except Exception as exc:
                # Fallo en el propio verificador: NO asumir VERIFIED (Sección 15)
                logger.error(f"[VERIFIER EXCEPTION] Error comprobando acción '{action_name}': {exc}", exc_info=True)
                status = VerificationStatus.NOT_VERIFIABLE
                verified = False
                evidence = {
                    "verifier_exception": str(exc),
                    "exception_type": type(exc).__name__,
                }
                response_message = f"No pude verificar si {human_target} quedó abierto."

        # ── 6. PUBLICAR EXACTAMENTE UN EVENTO VerificationResult ──
        verif_event = VerificationResult(
            session_id=session_id,
            action_name=action_name,
            intent=intent_name,
            status=status.value,
            verified=verified,
            confidence=1.0 if verified else 0.0,
            evidence=evidence,
            message=response_message,
            details={"action": action_name, "target": target, "op_type": op_type},
        )
        await self._event_bus.publish(verif_event)
        logger.info(
            f"[ACTION_VERIFICATION_ADAPTER] VerificationResult publicado: status={status.value} "
            f"verified={verified} session_id={session_id}"
        )

        # ── 7. TRANSICIÓN A RESPONDING Y PUBLICACIÓN SpeakRequested ──
        if self._state_machine is not None:
            if self._state_machine.can_transition_to(SessionState.RESPONDING):
                self._state_machine.transition_to(SessionState.RESPONDING)

        speak_event = SpeakRequested(
            text=response_message,
            session_id=session_id,
            metadata={
                "intent": intent_name,
                "verification_status": status.value,
                "verified": verified,
            },
        )
        await self._event_bus.publish(speak_event)
        logger.info(f"[ACTION_VERIFICATION_ADAPTER] SpeakRequested publicado: '{response_message}'")
