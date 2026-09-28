"""Pruebas unitarias fundamentales para JESSYCA Decision Engine (JDE) - Fase 1.

Verifica rigurosamente los 10 escenarios contractuales obligatorios:
- TEST 1: Acción ejecutada + verificada correctamente -> SUCCESS.
- TEST 2: Executor devuelve OK pero la acción NO ocurrió -> FAILED o UNKNOWN (NUNCA SUCCESS).
- TEST 3: Executor falla físicamente -> FAILED.
- TEST 4: Verifier no puede comprobar o falla -> UNKNOWN.
- TEST 5: Policy bloquea -> BLOCKED.
- TEST 6: Primary falla + fallback funciona + verifier confirma -> SUCCESS.
- TEST 7: LLM confidence alta (0.99) pero verificación negativa -> FAILED / UNKNOWN.
- TEST 8: Acción sensible requiere confirmación -> BLOCKED / REQUIRES_CONFIRMATION.
- TEST 9: Retry controlado tras fallo de verificación transitorio.
- TEST 10: Generación de Recibo íntegro con fingerprint criptográfico SHA-256.
"""

from __future__ import annotations

import pytest

from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, FallbackSpec, VerificationRequirement
from core.jde.policy import JDEPolicyGate
from core.jde.receipts import ActionReceipt
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.jde.verification import VerifierRegistry


@pytest.fixture
def jde_engine() -> DecisionEngine:
    return DecisionEngine(max_retries=1)


# ── TEST 1: Acción ejecutada + verificada correctamente -> SUCCESS ──
def test_jde_test_1_action_executed_and_verified_success(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Abre el bloc de notas",
        intent="open_application",
        proposed_action="launch_app",
        tool="windows.apps",
        parameters={"app_name": "notepad", "mock_verified": True},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="notepad", expected_properties={"mock_verified": True})
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"pid": 1234, "spawned": True}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_TRUE, True, {"hwnd": 5001, "visible": True}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.SUCCESS
    assert result.success is True
    assert result.claims_success is True
    assert result.executor_status == ExecutionStatusType.OK
    assert result.verification_status == VerificationStatusType.VERIFIED_TRUE


# ── TEST 2: Executor devuelve OK pero la acción NO ocurrió -> FAILED o UNKNOWN (NUNCA SUCCESS) ──
def test_jde_test_2_executor_ok_but_not_verified_never_success(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Abre YouTube",
        intent="open_browser",
        proposed_action="open_url",
        tool="browser.open",
        parameters={"url": "https://www.youtube.com"},
        verification_requirements=[
            VerificationRequirement(strategy="browser_tab", target="youtube.com")
        ],
    )

    # El executor afirma que abrió el navegador (OK)
    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"msg": "webbrowser.open called successfully"}

    # Pero el verificador comprueba el SO y NO encuentra ninguna ventana ni proceso real
    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_FALSE, False, {"error": "Window not found on desktop"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    # Invariante Anti-False Success: NUNCA SUCCESS
    assert result.state != DecisionState.SUCCESS
    assert result.state in (DecisionState.FAILED, DecisionState.UNKNOWN)
    assert result.success is False
    assert result.claims_success is False


# ── TEST 3: Executor falla físicamente -> FAILED ──
def test_jde_test_3_executor_fails(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Ejecuta comando",
        intent="cmd_exec",
        proposed_action="run_cmd",
        tool="system.cmd",
        parameters={"cmd": "invalid_command_xyz"},
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.ERROR, {"error": "Executable not found"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor)

    assert result.state == DecisionState.FAILED
    assert result.success is False
    assert result.claims_success is False
    assert result.executor_status == ExecutionStatusType.ERROR


# ── TEST 4: Verifier no puede comprobar determinísticamente -> UNKNOWN ──
def test_jde_test_4_verifier_unverifiable_yields_unknown(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Reproduce música de fondo",
        intent="play_media",
        proposed_action="play_audio",
        tool="windows.media",
        parameters={"track": "ambient.mp3"},
        verification_requirements=[
            VerificationRequirement(strategy="youtube_playback", target="ambient.mp3")
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"status": "dispatched"}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # El sistema no pudo inspeccionar si el parlante emite sonido
        return VerificationStatusType.UNVERIFIABLE, False, {"reason": "Audio stream inspection not supported"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.UNKNOWN
    assert result.success is False
    assert result.claims_success is False
    assert result.verification_status == VerificationStatusType.UNVERIFIABLE


# ── TEST 5: Policy bloquea acción no permitida -> BLOCKED ──
def test_jde_test_5_policy_blocks_unauthorized_action(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Elimina todos los archivos temporales",
        intent="file_delete",
        proposed_action="delete_all",
        tool="windows.files",
        parameters={"path": "C:\\Windows\\Temp"},
        risk_level="HIGH",
    )

    executor_called = False

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        nonlocal executor_called
        executor_called = True
        return ExecutionStatusType.OK, {}

    result = jde_engine.decide_and_execute(req, executor=mock_executor)

    assert result.state == DecisionState.BLOCKED
    assert result.success is False
    assert result.claims_success is False
    assert executor_called is False  # El executor jamás fue invocado
    assert "crítica" in result.message.lower() or "confirmación" in result.message.lower()


# ── TEST 6: Primary falla + fallback funciona + verifier confirma -> SUCCESS ──
def test_jde_test_6_primary_fails_fallback_succeeds_and_verifies(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Abre la calculadora",
        intent="open_application",
        proposed_action="open_uwp_calc",
        tool="windows.apps.calc_uwp",
        parameters={"app": "calculator"},
        fallback=FallbackSpec(
            tool="windows.apps.calc_exe",
            action="open_classic_calc",
            parameters={"app": "calc.exe"},
        ),
        verification_requirements=[
            VerificationRequirement(strategy="process_running", target="calc")
        ],
    )

    tools_called: list[str] = []

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        tools_called.append(tool)
        if tool == "windows.apps.calc_uwp":
            return ExecutionStatusType.ERROR, {"error": "UWP package not registered"}
        return ExecutionStatusType.OK, {"pid": 7788}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # Si ejecutó la tool de fallback, la ventana existe
        if "calc.exe" in str(params):
            return VerificationStatusType.VERIFIED_TRUE, True, {"hwnd": 8002, "proc": "calc.exe"}
        return VerificationStatusType.VERIFIED_FALSE, False, {}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.SUCCESS
    assert result.success is True
    assert result.claims_success is True
    assert result.used_fallback is True
    assert tools_called == ["windows.apps.calc_uwp", "windows.apps.calc_exe"]


# ── TEST 7: LLM confidence alta (0.99) pero verificación negativa -> FAILED / UNKNOWN ──
def test_jde_test_7_high_llm_confidence_does_not_override_negative_verification(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Escribe notas en Notepad",
        intent="type_text",
        proposed_action="send_keys",
        tool="windows.apps",
        confidence=0.99,  # ¡Confianza máxima del LLM!
        parameters={"text": "Hola mundo"},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="notepad")
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"keys_sent": True}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # El verifier inspecciona la UI y el texto NO fue introducido
        return VerificationStatusType.VERIFIED_FALSE, False, {"error": "Text not found in target control"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    # Invariante: La confianza del LLM (0.99) NUNCA se traduce en éxito si el verifier es negativo
    assert result.state != DecisionState.SUCCESS
    assert result.success is False
    assert result.claims_success is False


# ── TEST 8: Acción requiere confirmación -> BLOCKED / REQUIRES_CONFIRMATION ──
def test_jde_test_8_action_requires_confirmation(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Termina el proceso notepad",
        intent="kill_process",
        proposed_action="kill",
        tool="windows.process",
        parameters={"target_proc": "notepad.exe"},
        risk_level="HIGH",
    )

    result = jde_engine.decide_and_execute(req, executor=lambda t, p: (ExecutionStatusType.OK, {}))

    assert result.state == DecisionState.BLOCKED
    assert result.error_code == "REQUIRES_CONFIRMATION"
    assert result.claims_success is False


# ── TEST 9: Retry controlado tras fallo de verificación transitorio ──
def test_jde_test_9_controlled_retry_eventually_succeeds(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Lanza la aplicación de prueba",
        intent="open_app",
        proposed_action="launch",
        tool="windows.apps",
        parameters={"app": "test_app"},
        verification_requirements=[
            VerificationRequirement(strategy="process_running", target="test_app")
        ],
    )

    attempts = 0

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        nonlocal attempts
        attempts += 1
        return ExecutionStatusType.OK, {"attempt": attempts}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # En el intento 1 falla porque la ventana tardó en pintar; en el intento 2 ya está visible
        if attempts > 1:
            return VerificationStatusType.VERIFIED_TRUE, True, {"hwnd": 9001}
        return VerificationStatusType.VERIFIED_FALSE, False, {"error": "Window not painted yet"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.SUCCESS
    assert result.success is True
    assert result.retry_count == 1
    assert attempts == 2


# ── TEST 10: Receipt completo generado con fingerprint criptográfico íntegro ──
def test_jde_test_10_complete_receipt_with_cryptographic_fingerprint(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Abre bloc de notas",
        intent="open_application",
        proposed_action="open",
        tool="windows.apps",
        parameters={"app_name": "notepad"},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="notepad")
        ],
    )

    result = jde_engine.decide_and_execute(
        req,
        executor=lambda t, p: (ExecutionStatusType.OK, {"status": "spawned"}),
        verifier_override=lambda p: (VerificationStatusType.VERIFIED_TRUE, True, {"hwnd": 1234}),
    )

    assert result.receipt_id is not None
    assert result.receipt_data is not None

    receipt = ActionReceipt(**result.receipt_data)
    assert receipt.request_id == req.request_id
    assert receipt.final_status == DecisionState.SUCCESS
    assert receipt.verified is True
    assert len(receipt.fingerprint) == 64  # SHA-256
    assert receipt.verify_integrity() is True
