"""Motor de Interacción Confiable y Gestión de Respuestas Human-in-the-Loop (trusted_interaction_engine.py - Fase 41).

Implementa:
- Gestión de ciclo de vida de confirmaciones y aclaraciones.
- Validación de coincidencia de alcance (Scope Matching) para evitar elevación de privilegios.
- Control de expiración (TTL).
- Control de usuario: Aprobación, Rechazo, Modificación, Pausa, Reanudación y Cancelación.
- Detección de desviación e incomprensión de resultados (Drift / Misunderstanding).
"""

from __future__ import annotations

import threading
from typing import Any

from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.interaction.interaction_models import (
    ClarificationPrompt,
    ConfirmationPrompt,
    InteractionState,
    UserInteractionResponse,
    UserResponseType,
)
from core.logger import get_logger

logger = get_logger("jessyca.interaction.engine")


class TrustedInteractionEngine:
    """Motor de orquestación para interacción humana segura y de confianza."""

    def __init__(self, emergency_stop: EmergencyStopManager | None = None) -> None:
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._pending_confirmations: dict[str, ConfirmationPrompt] = {}
        self._pending_clarifications: dict[str, ClarificationPrompt] = {}
        self._task_states: dict[str, InteractionState] = {}
        self._lock = threading.RLock()

    def register_confirmation(self, prompt: ConfirmationPrompt) -> str:
        """Registra una solicitud de confirmación pendiente."""
        with self._lock:
            self._pending_confirmations[prompt.confirmation_id] = prompt
            self._task_states[prompt.task_id] = InteractionState.WAITING_USER
            logger.info(f"[HITL] Confirmación '{prompt.confirmation_id}' registrada para tarea '{prompt.task_id}'.")
            return prompt.confirmation_id

    def register_clarification(self, prompt: ClarificationPrompt, task_id: str = "") -> str:
        """Registra una solicitud de aclaración pendiente."""
        with self._lock:
            self._pending_clarifications[prompt.prompt_id] = prompt
            if task_id:
                self._task_states[task_id] = InteractionState.ASK_CLARIFICATION
            logger.info(f"[HITL] Aclaración '{prompt.prompt_id}' registrada.")
            return prompt.prompt_id

    def process_user_response(
        self,
        response: UserInteractionResponse,
        expected_action: str | None = None,
        expected_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Procesa la respuesta explícita del usuario validando alcance, caducidad e invariantes."""
        if self.emergency_stop.is_stopped():
            return {
                "success": False,
                "state": InteractionState.CANCELLED.value,
                "reason": "Parada de Emergencia activa. Respuesta no procesable.",
                "authorized": False,
            }

        with self._lock:
            # 1. CANCELACIÓN
            if response.response_type == UserResponseType.CANCEL:
                return {
                    "success": True,
                    "state": InteractionState.CANCELLED.value,
                    "reason": "Tarea cancelada explícitamente por el usuario.",
                    "authorized": False,
                }

            # 2. PAUSA
            if response.response_type == UserResponseType.PAUSE:
                return {
                    "success": True,
                    "state": InteractionState.PAUSED.value,
                    "reason": "Tarea pausada por el usuario.",
                    "authorized": False,
                }

            # 3. REANUDACIÓN
            if response.response_type == UserResponseType.RESUME:
                return {
                    "success": True,
                    "state": InteractionState.EXECUTE.value,
                    "reason": "Tarea reanudada por el usuario.",
                    "authorized": True,
                }

            # 4. RECHAZO
            if response.response_type == UserResponseType.REJECT:
                cid = response.confirmation_id
                if cid and cid in self._pending_confirmations:
                    del self._pending_confirmations[cid]
                return {
                    "success": False,
                    "state": InteractionState.DENIED.value,
                    "reason": f"Acción rechazada por el usuario: {response.comment or 'Sin comentario'}",
                    "authorized": False,
                }

            # 5. CONFIRMACIÓN EXPLÍCITA
            if response.response_type == UserResponseType.CONFIRM:
                cid = response.confirmation_id
                if not cid or cid not in self._pending_confirmations:
                    return {
                        "success": False,
                        "state": InteractionState.DENIED.value,
                        "reason": f"ID de confirmación '{cid}' inexistente o ya consumido.",
                        "authorized": False,
                    }

                prompt = self._pending_confirmations[cid]

                # Verificar expiración (TTL)
                if prompt.is_expired():
                    del self._pending_confirmations[cid]
                    return {
                        "success": False,
                        "state": InteractionState.FAILED.value,
                        "reason": f"La solicitud de confirmación '{cid}' ha expirado por tiempo límite (TTL).",
                        "authorized": False,
                    }

                # Scope Matching: Verificar que la confirmación coincide exactamente con la acción esperada
                if expected_action and expected_action != prompt.action_name:
                    del self._pending_confirmations[cid]
                    return {
                        "success": False,
                        "state": InteractionState.DENIED.value,
                        "reason": f"Scope Mismatch: La acción confirmada '{prompt.action_name}' no coincide con la acción solicitada '{expected_action}'.",
                        "authorized": False,
                    }

                # Validar parámetros si se proporcionaron
                if expected_params and expected_params != prompt.relevant_parameters:
                    del self._pending_confirmations[cid]
                    return {
                        "success": False,
                        "state": InteractionState.DENIED.value,
                        "reason": "Parameter Mismatch: Los parámetros confirmados difieren de los parámetros de ejecución.",
                        "authorized": False,
                    }

                # Confirmación válida consumida
                del self._pending_confirmations[cid]
                return {
                    "success": True,
                    "state": InteractionState.EXECUTE.value,
                    "task_id": prompt.task_id,
                    "action_name": prompt.action_name,
                    "reason": "Confirmación válida y autorizada dentro del alcance.",
                    "authorized": True,
                }

            # 6. ACLARACIÓN / MODIFICACIÓN DE PARÁMETROS
            if response.response_type in (UserResponseType.CLARIFY, UserResponseType.MODIFY):
                pid = response.prompt_id
                if pid and pid in self._pending_clarifications:
                    del self._pending_clarifications[pid]
                return {
                    "success": True,
                    "state": InteractionState.EXECUTE.value,
                    "selected_option": response.selected_option,
                    "modified_parameters": response.modified_parameters,
                    "reason": "Aclaración o modificación procesada.",
                    "authorized": True,
                }

            return {
                "success": False,
                "state": InteractionState.FAILED.value,
                "reason": f"Tipo de respuesta no soportado: '{response.response_type}'",
                "authorized": False,
            }

    def detect_drift(self, expected_intent: str, step_output: Any) -> tuple[bool, str]:
        """Detecta desviaciones o resultados inesperados que contradigan la intención original."""
        str_out = str(step_output).lower()
        if "error irremediable" in str_out or "inconsistencia grave" in str_out:
            logger.warning(f"[DRIFT DETECTED] Resultado discrepa con la intención '{expected_intent}'.")
            return True, "Desviación detectada: El resultado intermedio indica error o inconsistencia con la intención."
        return False, "Resultado coherente."
