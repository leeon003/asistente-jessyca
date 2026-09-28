"""Regression Tests contra Falsos Éxitos Históricos de JESSYCA (Fase 1 - JDE).

Verifica que JDE prevenga determinísticamente cualquier declaración de falso éxito
en los puntos críticos documentados históricamente en el proyecto:
1. YouTube (browser.youtube): Prevención de conversión de NOT_VERIFIABLE en SUCCEEDED.
2. Navegador (browser.open): Prevención de éxito por mero retorno de webbrowser.open().
3. Notepad / Apps Windows: Detección de PID residual en segundo plano sin ventana interactiva.
4. CMD / PowerShell: Verificación obligatoria de código de salida / proceso.
5. WhatsApp: Detección de cliente no activo / ventana inexistente.
6. MCP: Herramienta FastMCP que devuelve {exito: true} pero sin efecto verificable.
7. Computer Use: Acciones físicas del cursor/teclado que no autocertifican éxito.
"""

from __future__ import annotations

import pytest

from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType


@pytest.fixture
def jde_engine() -> DecisionEngine:
    return DecisionEngine(max_retries=0)


# ── REGRESIÓN 1: YouTube — Prevención de falso éxito por NOT_VERIFIABLE ──
def test_regression_youtube_not_verifiable_never_becomes_success(jde_engine: DecisionEngine) -> None:
    """En versiones anteriores, si el verificador de YouTube devolvía 'NOT_VERIFIABLE',
    local_agent.py lo convertía erróneamente en ExecutionStatus.SUCCEEDED.
    JDE DEBE FORZAR ESTRICTAMENTE ESTADO UNKNOWN Y claims_success=False.
    """
    req = DecisionRequest(
        user_request="Reproduce Bohemian Rhapsody en YouTube",
        intent="youtube_play",
        proposed_action="play_media",
        tool="browser.youtube",
        parameters={"query": "Bohemian Rhapsody", "simulate_unverifiable": True},
        verification_requirements=[
            VerificationRequirement(strategy="youtube_playback", target="Bohemian Rhapsody")
        ],
    )

    # El executor web reporta éxito de despacho HTTP
    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"exito": True, "step": "PLAY_MEDIA", "url": "https://youtube.com/watch?v=123"}

    # El verificador no puede comprobar el stream de audio
    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.UNVERIFIABLE, False, {"status": "NOT_VERIFIABLE"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.UNKNOWN
    assert result.success is False
    assert result.claims_success is False
    assert "no pudo verificarse" in result.message.lower() or "desconoce" in result.message.lower()


# ── REGRESIÓN 2: Navegador — Prevención de éxito por mera llamada a webbrowser.open() ──
def test_regression_browser_open_requires_real_window_verification(jde_engine: DecisionEngine) -> None:
    """BrowserOpenSkill devolvía exito: True con verified: False.
    local_agent.py decía 'Listo, abrí...' sin comprobar que la ventana existiera.
    JDE debe requerir evidencia positiva en el SO.
    """
    req = DecisionRequest(
        user_request="Abre Google",
        intent="open_browser",
        proposed_action="open_url",
        tool="browser.open",
        parameters={"url": "https://www.google.com"},
        verification_requirements=[
            VerificationRequirement(strategy="browser_tab", target="google.com")
        ],
    )

    # Executor llama a webbrowser.open() que siempre devuelve True internamente
    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"exito": True, "url": "https://www.google.com"}

    # Pero el sistema no encuentra ventana de Edge ni Chrome
    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_FALSE, False, {"error": "No browser window found"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.FAILED
    assert result.success is False
    assert result.claims_success is False


# ── REGRESIÓN 3: Notepad / Apps — PID residual sin ventana (MainWindowHandle == 0) ──
def test_regression_notepad_residual_pid_without_visible_gui_fails(jde_engine: DecisionEngine) -> None:
    """Si existe un proceso Notepad suspendido en segundo plano con MainWindowHandle=0,
    el verificador de JDE debe detectar que no tiene ventana interactiva y rechazar el éxito.
    """
    req = DecisionRequest(
        user_request="Abre el bloc de notas",
        intent="open_application",
        proposed_action="open",
        tool="windows.apps",
        parameters={"app_name": "notepad"},
        verification_requirements=[
            VerificationRequirement(
                strategy="window_visible",
                target="notepad",
                expected_properties={"require_visible_window": True},
            )
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"execution_count": 1}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # Proceso existe en memoria, pero NO tiene ventana GUI visible en WinSta0
        return VerificationStatusType.VERIFIED_FALSE, False, {
            "pids": [1024],
            "hwnd": 0,
            "error": "Process exists but MainWindowHandle=0 (invisible background process)",
        }

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.FAILED
    assert result.success is False
    assert result.claims_success is False


# ── REGRESIÓN 4: CMD / PowerShell — Ejecución con fallo de salida en Windows ──
def test_regression_cmd_process_error_exit_code_fails(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Ejecuta comando cmd",
        intent="cmd_execution",
        proposed_action="exec_cmd",
        tool="windows.cmd",
        parameters={"command": "dir non_existent_directory_404"},
        verification_requirements=[
            VerificationRequirement(strategy="process_running", target="cmd.exe")
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        # El comando retornó exit code 1
        return ExecutionStatusType.ERROR, {"exit_code": 1, "stderr": "El sistema no puede encontrar la ruta especificada."}

    result = jde_engine.decide_and_execute(req, executor=mock_executor)

    assert result.state == DecisionState.FAILED
    assert result.claims_success is False
    assert result.executor_status == ExecutionStatusType.ERROR


# ── REGRESIÓN 5: WhatsApp — Intento de interactuar cuando no está instalado / abierto ──
def test_regression_whatsapp_missing_application_fails(jde_engine: DecisionEngine) -> None:
    req = DecisionRequest(
        user_request="Abre WhatsApp",
        intent="open_application",
        proposed_action="open",
        tool="windows.apps",
        parameters={"app_name": "whatsapp"},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="whatsapp")
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        # Subprocess intentó lanzar el comando y falló
        return ExecutionStatusType.ERROR, {"error": "FileNotFoundError: WhatsApp.exe"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor)

    assert result.state == DecisionState.FAILED
    assert result.claims_success is False


# ── REGRESIÓN 6: MCP — Herramienta FastMCP devolviendo {exito: True} pero sin evidencia ──
def test_regression_mcp_fake_success_payload_blocked_without_verification(jde_engine: DecisionEngine) -> None:
    """Una tool MCP externa puede responder JSON {'exito': true, 'status': 'ok'},
    pero JDE nunca lo declara SUCCESS si la verificación física no lo comprueba.
    """
    req = DecisionRequest(
        user_request="Crear archivo de configuración en Windows",
        intent="file_create",
        proposed_action="create_file",
        tool="mcp.windows.filesystem",
        parameters={"path": "C:\\config.ini"},
        verification_requirements=[
            VerificationRequirement(strategy="process", target="C:\\config.ini")
        ],
    )

    # Tool MCP dice exito: True
    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        return ExecutionStatusType.OK, {"exito": True, "bytes_written": 128}

    # Pero el verificador del filesystem no encuentra el archivo (error de permisos o mock)
    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        return VerificationStatusType.VERIFIED_FALSE, False, {"error": "File does not exist on disk"}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.FAILED
    assert result.claims_success is False


# ── REGRESIÓN 7: Computer Use — Acción de mouse/teclado con verified: False ──
def test_regression_computer_use_unverified_action_remains_unverified(jde_engine: DecisionEngine) -> None:
    """ComputerUseAdapter ejecuta clics o pulsaciones con verified=False por defecto.
    JDE no debe marcar la acción como SUCCESS a menos que haya un segundo ciclo de percepción
    que verifique el cambio de estado en la UI.
    """
    req = DecisionRequest(
        user_request="Haz clic en el botón guardar",
        intent="computer_use_click",
        proposed_action="mouse_interact",
        tool="windows_computer_use",
        parameters={"action": "click", "x": 500, "y": 300},
        verification_requirements=[
            VerificationRequirement(strategy="window_visible", target="save_dialog")
        ],
    )

    def mock_executor(tool: str, params: dict) -> tuple[ExecutionStatusType, dict]:
        # El mouse se movió y envió el evento de clic
        return ExecutionStatusType.OK, {"clicked": True, "coords": [500, 300]}

    def mock_verifier(params: dict) -> tuple[VerificationStatusType, bool, dict]:
        # La UI no cambió (el botón no respondió o estaba bloqueado)
        return VerificationStatusType.VERIFIED_FALSE, False, {"ui_delta": 0}

    result = jde_engine.decide_and_execute(req, executor=mock_executor, verifier_override=mock_verifier)

    assert result.state == DecisionState.FAILED
    assert result.claims_success is False
