"""Suite de pruebas para la habilidad WindowsComputerUseSkill (Fase 4 CUA Integration)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from core.security_architecture import SecurityLevel
from skills.computer_use_skill import WindowsComputerUseSkill
from skills.skill_models import SkillStatus


@pytest.fixture
def computer_use_skill():
    mock_adapter = MagicMock()
    mock_adapter.is_ready.return_value = True
    mock_res = MagicMock()
    mock_res.success = True
    mock_res.message = "Operación completada"
    mock_res.data = {"active_window": "Calculadora"}
    mock_res.verified = True
    mock_adapter.execute.return_value = mock_res
    return WindowsComputerUseSkill(adapter=mock_adapter)


def test_01_skill_definition_and_manifest(computer_use_skill):
    """Valida metadatos y niveles de riesgo de la skill."""
    assert computer_use_skill.nombre == "windows.computer_use"
    assert computer_use_skill.nivel_riesgo == 3  # HIGH
    assert computer_use_skill.definition.risk_level == SecurityLevel.HIGH
    assert "desktop" in computer_use_skill.definition.capabilities


def test_02_observe_action_allowed(computer_use_skill):
    """Acciones de observación son SAFE y se ejecutan con ALLOW."""
    with patch.object(computer_use_skill.permission_manager, "check_permission", return_value=True):
        res = computer_use_skill.ejecutar({"accion": "observe"})
        assert res["exito"] is True
        assert res["security_verdict"] == "ALLOW"
        assert res["verified"] is True


def test_03_high_risk_action_permission_denied(computer_use_skill):
    """Si PermissionManager deniega una acción física, se aborta y retorna DENY."""
    with patch.object(computer_use_skill.permission_manager, "check_permission", return_value=False):
        res = computer_use_skill.ejecutar({"accion": "click", "x": 500, "y": 300})
        assert res["exito"] is False
        assert res["security_verdict"] == "DENY"
        assert "no autorizada" in res["mensaje"]


def test_04_execute_skill_framework_interface(computer_use_skill):
    """Valida la interfaz execute(context) -> SkillResult del Skill Framework."""
    from skills.skill_models import SkillContext
    ctx = SkillContext(
        skill_id="windows.computer_use",
        intent="windows.computer_use",
        execution_id="test-exec-1",
        parameters={"accion": "observe"},
    )
    with patch.object(computer_use_skill.permission_manager, "check_permission", return_value=True):
        skill_res = computer_use_skill.execute(ctx)
        assert skill_res.status == SkillStatus.COMPLETED
        assert skill_res.output["exito"] is True
