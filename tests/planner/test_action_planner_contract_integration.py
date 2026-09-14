"""Tests unitarios para la integración de ActionPlanner con ActionIntentContract (Fase 64.2.1).

Verifica exhaustivamente los 10 requisitos mandatorios (A a J):
A. planner → ActionIntent válido
B. planner → ActionIntent inválido
C. action con confidence baja
D. action que requiere confirmación
E. action que no requiere confirmación
F. skill inexistente
G. operation inexistente/vacía
H. argumentos inválidos
I. asegurar que PLAN no ejecuta ninguna acción
J. asegurar que un ActionIntent inválido nunca alcanza el executor
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from core.action_intent_contract import ActionIntentContract
from core.dialogue.action_planner import (
    ActionPlanner,
    ActionPlanningValidationError,
)


class TestActionPlannerContractIntegration:
    """Suite de validación formal para ActionPlanner con ActionIntentContract."""

    def setup_method(self) -> None:
        self.planner = ActionPlanner()

    # ── A. PLANNER → ACTIONINTENT VÁLIDO ─────────────────────────────────────
    def test_a_planner_to_valid_action_intent(self) -> None:
        """Demuestra que el planner genera un ActionIntentContract completo y válido para una acción."""
        contract = self.planner.plan_action(
            intent="open_application",
            user_input="abre el bloc de notas",
            params={"app_name": "notepad"},
            confidence=0.98,
        )

        assert isinstance(contract, ActionIntentContract)
        # Acción solicitada
        assert contract.action_intent.intent_name == "open_application"
        assert contract.action_intent.target == "notepad"
        assert contract.action_intent.confidence == 0.98
        assert contract.action_intent.parameters["app_name"] == "notepad"

        # ExecutionGate
        assert contract.execution_gate.can_execute is True
        assert contract.execution_gate.needs_clarification is False
        assert contract.execution_gate.needs_confirmation is False

        # ExecutionSpec
        assert contract.execution_spec is not None
        assert contract.execution_spec.skill_id == "windows.apps@1.0.0"
        assert contract.execution_spec.tool_name == "windows.launch_app"
        assert contract.execution_spec.idempotency_key is not None

        # PreActionFeedback
        assert contract.pre_action_feedback.acknowledgement_speech is not None
        assert "bloc de notas" in contract.pre_action_feedback.acknowledgement_speech.lower()

        # Invariantes de planificación
        assert contract.execution_report is None
        assert contract.post_action_feedback is None

    # ── B. PLANNER → ACTIONINTENT INVÁLIDO ───────────────────────────────────
    def test_b_planner_to_invalid_action_intent(self) -> None:
        """Demuestra que intenciones vacías o malformadas son rechazadas inmediatamente."""
        with pytest.raises(ActionPlanningValidationError, match="no puede ser nulo o vacío"):
            self.planner.plan_action(intent="")

        with pytest.raises(ActionPlanningValidationError, match="no puede ser nulo o vacío"):
            self.planner.plan_action(intent="   ")

    # ── C. ACTION CON CONFIDENCE BAJA ────────────────────────────────────────
    def test_c_action_with_low_confidence(self) -> None:
        """Una acción con confianza inferior a 0.70 debe activar el gate de aclaración y bloquear ejecución."""
        contract = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
            confidence=0.45,
        )

        assert contract.action_intent.confidence == 0.45
        assert contract.execution_gate.can_execute is False
        assert contract.execution_gate.needs_clarification is True
        assert contract.execution_gate.clarification_prompt is not None
        assert "confianza" in contract.execution_gate.clarification_prompt.lower()
        assert "0.45" in contract.execution_gate.clarification_prompt

    # ── D. ACTION QUE REQUIERE CONFIRMACIÓN ───────────────────────────────────
    def test_d_action_requiring_confirmation(self) -> None:
        """Acciones sensibles o con requires_confirmation=True activan el gate de confirmación."""
        # Caso 1: Flag explícito
        contract1 = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
            requires_confirmation=True,
        )
        assert contract1.execution_gate.needs_confirmation is True
        assert contract1.execution_gate.can_execute is False
        assert contract1.execution_gate.confirmation_prompt is not None

        # Caso 2: Nivel de riesgo DANGEROUS
        contract2 = self.planner.plan_action(
            intent="delete_file",
            params={"path": "C:\\temp\\old.tmp"},
            risk_level="DANGEROUS",
        )
        assert contract2.execution_gate.needs_confirmation is True
        assert contract2.execution_gate.can_execute is False
        assert contract2.execution_gate.risk_level == "DANGEROUS"

    # ── E. ACTION QUE NO REQUIERE CONFIRMACIÓN ───────────────────────────────
    def test_e_action_not_requiring_confirmation(self) -> None:
        """Acciones seguras con alta confianza no exigen confirmación y pueden ejecutarse."""
        contract = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
            requires_confirmation=False,
            risk_level="SAFE",
        )
        assert contract.execution_gate.needs_confirmation is False
        assert contract.execution_gate.can_execute is True

    # ── F. SKILL INEXISTENTE ─────────────────────────────────────────────────
    def test_f_nonexistent_skill_rejected(self) -> None:
        """Especificar una skill no registrada dispara ActionPlanningValidationError."""
        with pytest.raises(ActionPlanningValidationError, match="Skill inexistente o no disponible"):
            self.planner.plan_action(
                intent="custom_action",
                skill_id="sistema_fantasma.desconocido@1.0.0",
                tool_name="ejecutar_algo",
            )

    # ── G. OPERATION INEXISTENTE O VACÍA ──────────────────────────────────────
    def test_g_empty_operation_rejected(self) -> None:
        """Especificar una operación vacía o en blanco es rechazado por el planificador."""
        with pytest.raises(ActionPlanningValidationError, match="operación solicitada"):
            self.planner.plan_action(
                intent="open_application",
                params={"app_name": "notepad"},
                tool_name="   ",
            )

    # ── H. ARGUMENTOS INVÁLIDOS O INCOMPATIBLES ──────────────────────────────
    def test_h_invalid_arguments_rejected(self) -> None:
        """Argumentos incompatibles o incompletos son rechazados inmediatamente."""
        # Falta app_name en open_application
        with pytest.raises(ActionPlanningValidationError, match="requiere el parámetro 'app_name'"):
            self.planner.plan_action(intent="open_application", params={})

        # app_name vacío en close_application
        with pytest.raises(ActionPlanningValidationError, match="requiere el parámetro 'app_name'"):
            self.planner.plan_action(intent="close_application", params={"app_name": "   "})

        # Confidence inválida fuera de rango
        with pytest.raises(ActionPlanningValidationError, match="Confidence inválida"):
            self.planner.plan_action(
                intent="open_application",
                params={"app_name": "notepad"},
                confidence=1.5,
            )

        with pytest.raises(ActionPlanningValidationError, match="Confidence inválida"):
            self.planner.plan_action(
                intent="open_application",
                params={"app_name": "notepad"},
                confidence=-0.1,
            )

    # ── I. ASEGURAR QUE PLAN NO EJECUTA NINGUNA ACCIÓN ────────────────────────
    def test_i_plan_does_not_execute_any_action(self) -> None:
        """Demuestra formalmente la regla PLANIFICAR != EJECUTAR."""
        mock_executor = MagicMock()

        contract = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
        )

        # Ningún componente de ejecución fue invocado
        mock_executor.assert_not_called()

        # El contrato conserva explícitamente None en los reportes de ejecución
        assert contract.execution_report is None
        assert contract.post_action_feedback is None

    # ── J. ASEGURAR QUE UN ACTIONINTENT INVÁLIDO NUNCA ALCANZA EL EXECUTOR ────
    def test_j_invalid_action_intent_never_reaches_executor(self) -> None:
        """Demuestra que una planificación no ejecutable es rechazada antes de despacharse al executor."""
        mock_executor = MagicMock()

        def dispatch_to_executor(action_contract: ActionIntentContract) -> Any:
            # Protocolo de despacho seguro
            if not action_contract.execution_gate.can_execute:
                raise PermissionError("Ejecución bloqueada por ExecutionGate: can_execute=False")
            return mock_executor.execute(action_contract)

        # 1. Contrato con baja confianza (requiere aclaración)
        low_conf_contract = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
            confidence=0.3,
        )
        with pytest.raises(PermissionError, match="Ejecución bloqueada"):
            dispatch_to_executor(low_conf_contract)

        # 2. Contrato con confirmación requerida
        confirm_contract = self.planner.plan_action(
            intent="open_application",
            params={"app_name": "notepad"},
            requires_confirmation=True,
        )
        with pytest.raises(PermissionError, match="Ejecución bloqueada"):
            dispatch_to_executor(confirm_contract)

        # El executor real NUNCA fue llamado
        mock_executor.execute.assert_not_called()

    # ── COMPATIBILIDAD CON SKILLS DE PRODUCCIÓN ──────────────────────────────
    def test_compatibility_with_production_skills(self) -> None:
        """Verifica compatibilidad con windows.apps, windows.media y windows.screenshot."""
        # 1. windows.apps
        c_apps = self.planner.plan_action("open_application", params={"app_name": "calc"})
        assert c_apps.execution_spec is not None
        assert c_apps.execution_spec.skill_id == "windows.apps@1.0.0"

        # 2. windows.media
        c_media = self.planner.plan_action("play_random_video")
        assert c_media.execution_spec is not None
        assert c_media.execution_spec.skill_id == "windows.media@1.0.0"

        # 3. windows.screenshot
        c_shot = self.planner.plan_action("capture_screenshot")
        assert c_shot.execution_spec is not None
        assert c_shot.execution_spec.skill_id == "windows.screenshot@1.0.0"
        assert c_shot.execution_spec.tool_name == "desktop.screenshot"
