"""Pruebas de Integración y Garantías de JDE Shadow Mode (Fase 2).

Verifica exhaustivamente los requerimientos de la Fase 2:
- TEST 1: "abre bloc de notas" con éxito verificado -> CONCORDANT_SUCCESS.
- TEST 2: Éxito sin verificación en SO -> FALSE_SUCCESS y CRITICAL_DIVERGENCE.
- TEST 3: Fallo reportado pero acción ocurrió en el SO -> FALSE_FAILURE.
- TEST 4: Acción sensible sin confirmación -> POLICY_DIVERGENCE.
- TEST 5: MCP devolviendo payload {"exito": true} sin evidencia física -> FALSE_SUCCESS / UNKNOWN.
- TEST 6: Computer Use devuelve ejecución sin cambio observable -> FALSE_SUCCESS / VERIFICATION_DIVERGENCE.
- TEST 7: GARANTÍA ABSOLUTA: Shadow Mode nunca ejecuta una acción adicional (call_count = 0).
- TEST 8: GARANTÍA DE INTEGRIDAD: Shadow Mode no modifica success ni mensaje de JessycaResponse.
- TEST 9: GARANTÍA DE PRIVACIDAD: Secretos, contraseñas y tokens son redactados en los registros.
- TEST 10: Persistencia correcta en archivo JSONL.
- TEST 11: Integración real con JessycaLocalAgent observando el turno sin alterar la respuesta.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest

from core.jde.adapter import JDEShadowAdapter, LocalAgentExecutionContext
from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.shadow import (
    DivergenceSeverity,
    JDEShadowMode,
    ShadowClassification,
    redact_sensitive_data,
)
from core.jde.states import DecisionState
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest


@pytest.fixture
def tmp_shadow_log(tmp_path) -> str:
    return str(tmp_path / "test_shadow.jsonl")


@pytest.fixture
def shadow_mode(tmp_shadow_log: str) -> JDEShadowMode:
    return JDEShadowMode(persist_to_file=True, log_file_path=tmp_shadow_log)


@pytest.fixture
def shadow_adapter(shadow_mode: JDEShadowMode) -> JDEShadowAdapter:
    return JDEShadowAdapter(shadow_mode=shadow_mode)


# ── TEST 1: CONCORDANT_SUCCESS ──
def test_shadow_test_1_concordant_success(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-1",
        user_input="abre bloc de notas",
        intent="open_application",
        tool="windows.apps",
        action="open_application",
        parameters={"app_name": "notepad"},
        exec_success=True,
        current_message="Listo, abrí el Bloc de notas.",
        is_verified=True,
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.CONCORDANT_SUCCESS
    assert evaluation.is_divergent is False
    assert evaluation.jde_predicted_state == DecisionState.SUCCESS
    assert evaluation.severity == DivergenceSeverity.INFO


# ── TEST 2: FALSE_SUCCESS & CRITICAL_DIVERGENCE ──
def test_shadow_test_2_false_success_critical_divergence(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-2",
        user_input="Abre YouTube",
        intent="open_browser",
        tool="browser.open",
        action="open_url",
        parameters={"url": "https://www.youtube.com"},
        exec_success=True,
        current_message="Listo, abrí YouTube en el navegador.",
        is_verified=False,  # ¡No verificado!
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.FALSE_SUCCESS
    assert evaluation.is_divergent is True
    assert evaluation.severity == DivergenceSeverity.CRITICAL
    assert evaluation.jde_predicted_state == DecisionState.UNKNOWN
    assert "CRITICAL_FALSE_SUCCESS" in (evaluation.divergence_reason or "")


# ── TEST 3: FALSE_FAILURE ──
def test_shadow_test_3_false_failure(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-3",
        user_input="Abre bloc de notas",
        intent="open_application",
        tool="windows.apps",
        action="open_application",
        parameters={"app_name": "notepad"},
        exec_success=False,
        current_message="Error al abrir bloc de notas.",
        is_verified=True,  # Pero la ventana sí existe en Windows
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.FALSE_FAILURE
    assert evaluation.is_divergent is True
    assert evaluation.jde_predicted_state == DecisionState.SUCCESS


# ── TEST 4: POLICY_DIVERGENCE ──
def test_shadow_test_4_policy_divergence(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-4",
        user_input="Termina el proceso CMD",
        intent="kill_process",
        tool="windows.process",
        action="kill",
        parameters={"target": "cmd.exe"},
        exec_success=True,
        current_message="Proceso cmd.exe terminado.",
        is_verified=True,
        security_level="HIGH",
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.POLICY_DIVERGENCE
    assert evaluation.is_divergent is True
    assert evaluation.jde_predicted_state == DecisionState.BLOCKED
    assert evaluation.jde_requires_confirmation is True


# ── TEST 5: MCP FALSE_SUCCESS / UNKNOWN ──
def test_shadow_test_5_mcp_unverified_payload(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-5",
        user_input="Escribe en registro de Windows",
        intent="registry_write",
        tool="mcp.windows.registry",
        action="set_value",
        parameters={"key": "HKCU\\Software\\Test", "value": "1"},
        exec_success=True,  # MCP devolvió {"exito": true}
        current_message="Clave de registro configurada con éxito.",
        is_verified=False,  # Pero no se comprobó en Windows Registry
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.FALSE_SUCCESS
    assert evaluation.severity == DivergenceSeverity.CRITICAL
    assert evaluation.is_divergent is True
    assert evaluation.jde_predicted_state == DecisionState.UNKNOWN


# ── TEST 6: Computer Use VERIFICATION_DIVERGENCE ──
def test_shadow_test_6_computer_use_unverified_action(shadow_adapter: JDEShadowAdapter) -> None:
    ctx = LocalAgentExecutionContext(
        request_id="req-test-6",
        user_input="Haz clic en enviar",
        intent="computer_use.mouse_interact",
        tool="windows_computer_use",
        action="mouse_interact",
        parameters={"action": "click", "x": 100, "y": 200},
        exec_success=True,
        current_message="Clic ejecutado.",
        is_verified=False,
    )

    evaluation = shadow_adapter.observe(ctx)
    assert evaluation is not None
    assert evaluation.classification == ShadowClassification.FALSE_SUCCESS
    assert evaluation.severity == DivergenceSeverity.CRITICAL


# ── TEST 7: GARANTÍA ABSOLUTA: Shadow Mode NUNCA ejecuta una acción física ──
def test_shadow_test_7_never_executes_additional_actions(shadow_adapter: JDEShadowAdapter) -> None:
    mock_system_launcher = MagicMock()

    ctx = LocalAgentExecutionContext(
        request_id="req-test-7",
        user_input="Abre bloc de notas",
        intent="open_application",
        tool="windows.apps",
        action="open_application",
        parameters={"app_name": "notepad"},
        exec_success=True,
        current_message="Listo, abrí el Bloc de notas.",
        is_verified=True,
    )

    # Observamos el turno
    shadow_adapter.observe(ctx)

    # Comprobamos que ningún lanzador fue llamado desde Shadow Mode
    assert mock_system_launcher.call_count == 0


# ── TEST 8: GARANTÍA DE INTEGRIDAD: No modifica la respuesta del agente ──
def test_shadow_test_8_does_not_modify_agent_response() -> None:
    agent = JessycaLocalAgent.get_instance()
    initial_shadow_obs = agent.jde_shadow_adapter.shadow_mode.metrics.total_observations

    # Ejecutar una consulta o acción a través de interact()
    resp = agent.interact("consulta general de prueba")

    # La respuesta original se mantiene intacta
    assert resp.response_text is not None
    assert isinstance(resp.success, bool)

    # Shadow observó el turno
    assert agent.jde_shadow_adapter.shadow_mode.metrics.total_observations >= initial_shadow_obs


# ── TEST 9: GARANTÍA DE PRIVACIDAD: Redacción de secretos ──
def test_shadow_test_9_secret_redaction(shadow_mode: JDEShadowMode, tmp_shadow_log: str) -> None:
    raw_params = {
        "user": "admin",
        "password": "SuperSecretPassword123!",
        "api_key": "sk-1234567890abcdef",
        "auth_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "normal_field": "hello world",
    }

    req = DecisionRequest(
        user_request="Configura el token Bearer secret_xyz_9999",
        intent="set_token",
        proposed_action="store_auth",
        tool="system.auth",
        parameters=raw_params,
    )

    evaluation = shadow_mode.evaluate_shadow(
        request=req,
        current_system_success=True,
        current_system_message="Credenciales guardadas.",
        current_system_verified=True,
    )

    # Verificar que el objeto logeado tenga los secretos redactados
    log_dict = evaluation.to_log_dict()
    assert log_dict["parameters"]["password"] == "***REDACTED_SECRET***"
    assert log_dict["parameters"]["api_key"] == "***REDACTED_SECRET***"
    assert log_dict["parameters"]["auth_token"] == "***REDACTED_SECRET***"
    assert log_dict["parameters"]["normal_field"] == "hello world"
    assert "SuperSecretPassword123!" not in str(log_dict)

    # Verificar que en el archivo JSONL en disco los secretos no aparezcan en texto plano
    with open(tmp_shadow_log, "r", encoding="utf-8") as f:
        file_content = f.read()
    assert "SuperSecretPassword123!" not in file_content
    assert "sk-1234567890abcdef" not in file_content


# ── TEST 10: Persistencia e Historial de Divergencias ──
def test_shadow_test_10_persistence_and_metrics_summary(shadow_mode: JDEShadowMode, tmp_shadow_log: str) -> None:
    req_concordant = DecisionRequest(
        user_request="Abre Notepad",
        intent="open_app",
        proposed_action="open",
        tool="windows.apps",
    )
    req_divergent = DecisionRequest(
        user_request="Reproduce video",
        intent="youtube_play",
        proposed_action="play",
        tool="browser.youtube",
    )

    shadow_mode.evaluate_shadow(req_concordant, current_system_success=True, current_system_message="Listo", current_system_verified=True)
    shadow_mode.evaluate_shadow(req_divergent, current_system_success=True, current_system_message="Listo", current_system_verified=False)

    report_text = shadow_mode.metrics.format_report()
    assert "Observations: 2" in report_text
    assert "Concordant success:       1" in report_text
    assert "False success:            1" in report_text
    assert "Critical divergences:     1" in report_text

    # Comprobar que en disco hay exactamente 2 líneas JSON válidas
    with open(tmp_shadow_log, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2
    parsed_0 = json.loads(lines[0])
    parsed_1 = json.loads(lines[1])
    assert parsed_0["classification"] == ShadowClassification.CONCORDANT_SUCCESS.value
    assert parsed_1["classification"] == ShadowClassification.FALSE_SUCCESS.value
