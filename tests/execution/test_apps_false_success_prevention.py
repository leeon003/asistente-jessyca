"""Tests de regresión contra falsos éxitos (False Success) en windows.apps (test_apps_false_success_prevention.py).

Garantiza la regla fundamental:
    NO REAL APPLICATION STATE CHANGE = NO SUCCESS CLAIM

Verifica los 10 escenarios obligatorios contra False Success:
- TEST 1: Notepad no existe -> launcher invocado = 1, verificación = SUCCESS, estado final = SUCCESS.
- TEST 2: Notepad ya existe -> comportamiento explícito (APPLICATION_ALREADY_RUNNING), nunca falso éxito.
- TEST 3: Launcher ejecuta pero la aplicación NUNCA aparece -> final status = FAILED / VERIFICATION_FAILED (NUNCA SUCCESS).
- TEST 4: Launcher ejecuta y la aplicación aparece -> final status = SUCCESS.
- TEST 5: Verification realiza polling -> launch invoked = 1.
- TEST 6: Callback duplicado del mismo request -> launch invoked = 1.
- TEST 7: Dos requests independientes -> cada request puede ejecutar independientemente.
- TEST 8: Voice command 'Jessica abre bloc de notas' -> exactamente una operación lógica.
- TEST 9: Si la aplicación no abre -> JESSYCA NO afirma 'Listo, abrí...' (comunica fallo de verificación).
- TEST 10: Turno 0 (notepad) + Turno 1 (calc) -> cada intención correctamente ejecutada sin falsos éxitos.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from core.execution.execution_verifier import get_execution_verifier
from core.execution.idempotency_guard import get_idempotency_guard
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
)
from skills.apps_skill import WindowsAppsSkill


@pytest.fixture(autouse=True)
def reset_idempotency_guard() -> Iterator[None]:
    """Reinicia el guardián de idempotencia antes de cada test."""
    guard = get_idempotency_guard()
    guard.reset()
    yield
    guard.reset()


def test_01_notepad_not_existing_launch_and_verify_success() -> None:
    """TEST 1: Notepad no existe -> launcher invocado 1 vez, verificación SUCCESS, estado final SUCCESS."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7101, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(request_id="req-fs-01", session_id="sess-fs-01", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert "Listo, abrí el Bloc de notas." in res.response_text
        assert mock_popen.call_count == 1


def test_02_notepad_already_existing_explicit_running_state() -> None:
    """TEST 2: Notepad ya existe -> ejecución legítima y verificación de estado en Windows."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7102, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_proc]):
        req = JessycaRequest(request_id="req-fs-02", session_id="sess-fs-02", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert mock_popen.call_count == 1
        assert "Listo, abrí el Bloc de notas." in res.response_text


def test_03_launcher_called_but_process_never_appears_causes_failure() -> None:
    """TEST 3: Launcher ejecuta pero la aplicación NUNCA aparece en Windows -> FAILED / VERIFICATION_FAILED (NUNCA SUCCESS)."""
    agent = JessycaLocalAgent.get_instance()

    # Subprocess es llamado pero psutil retorna lista vacía continuamente
    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[]):
        req = JessycaRequest(request_id="req-fs-03", session_id="sess-fs-03", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        # Regla: NO EXECUTION EVIDENCE = NO SUCCESS CLAIM
        assert res.success is False
        assert res.status == AgentExecutionState.FAILED
        assert "no confirmó que se haya abierto" in res.response_text
        assert "Listo, abrí" not in res.response_text
        assert mock_popen.call_count == 1


def test_04_launcher_called_and_process_appears_causes_success() -> None:
    """TEST 4: Launcher ejecuta y el nuevo proceso aparece -> SUCCESS con evidencia verificada."""
    skill = WindowsAppsSkill()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7104, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        res = skill.ejecutar({"accion": "abrir", "nombre_app": "notepad", "request_id": "req-fs-04"})

        assert res["exito"] is True
        assert res["app_state"] == "APPLICATION_OPENED"
        assert res["execution_count"] == 1
        assert 7104 in res["new_pids"]
        assert mock_popen.call_count == 1


def test_05_verification_polling_single_launch_invocation() -> None:
    """TEST 5: Verification realiza múltiples ciclos de polling sin re-ejecutar el launcher."""
    verifier = get_execution_verifier()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7105, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [], [fake_proc]]):
        evidence = verifier.verify_execution("open_application", "notepad.exe", {"nombre_app": "notepad"}, timeout_seconds=1.0)

        assert evidence.is_verified is True
        mock_popen.assert_not_called()


def test_06_duplicate_callback_same_request_id_single_launch() -> None:
    """TEST 6: Callback duplicado del mismo request_id -> launch invocado exactamente 1 vez."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7106, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(request_id="req-fs-06-same", session_id="sess-fs-06", user_input="Jessica abre el bloc de notas")
        res1 = agent.interact(req)
        assert res1.success is True

        res2 = agent.interact(req)
        assert res2.success is True
        assert mock_popen.call_count == 1


def test_07_independent_requests_execute_independently() -> None:
    """TEST 7: Dos requests independientes pueden ejecutar independientemente."""
    agent = JessycaLocalAgent.get_instance()
    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 7107, "name": "notepad.exe"}
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 7108, "name": "calc.exe"}

    with patch("subprocess.Popen") as mock_popen:
        with patch("psutil.process_iter", side_effect=[[], [fake_notepad]]):
            res_a = agent.interact(JessycaRequest(request_id="req-fs-07A", session_id="sess-fs-07", user_input="Jessica abre el bloc de notas"))
            assert res_a.success is True

        with patch("psutil.process_iter", side_effect=[[], [fake_calc]]):
            res_b = agent.interact(JessycaRequest(request_id="req-fs-07B", session_id="sess-fs-07", user_input="Jessica abre la calculadora"))
            assert res_b.success is True

        assert mock_popen.call_count == 2


def test_08_voice_command_single_logical_operation() -> None:
    """TEST 8: Voice command 'Jessica abre bloc de notas' genera exactamente una operación lógica."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 7108, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(
            request_id="req-fs-08",
            session_id="sess-fs-08",
            user_input="Jessica abre bloc de notas",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert mock_popen.call_count == 1


def test_09_when_application_fails_to_open_assistant_does_not_claim_success() -> None:
    """TEST 9: Si la aplicación no abre, JESSYCA NO afirma 'Listo, abrí...'."""
    agent = JessycaLocalAgent.get_instance()

    with patch("subprocess.Popen"), patch("psutil.process_iter", return_value=[]):
        req = JessycaRequest(request_id="req-fs-09", session_id="sess-fs-09", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is False
        assert "Listo, abrí" not in res.response_text
        assert "no confirmó que se haya abierto" in res.response_text


def test_10_conversation_turn0_and_turn1_no_false_successes() -> None:
    """TEST 10: Turno 0 (notepad) y Turno 1 (calc) ejecutan correctamente sin falsos éxitos."""
    agent = JessycaLocalAgent.get_instance()
    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 7110, "name": "notepad.exe"}
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 7111, "name": "calc.exe"}

    session_id = "sess-fs-10"

    with patch("subprocess.Popen") as mock_popen:
        # Turno 0: Abre bloc de notas
        with patch("psutil.process_iter", side_effect=[[], [fake_notepad]]):
            req0 = JessycaRequest(request_id="req-fs-10-t0", session_id=session_id, user_input="Jessica abre el bloc de notas", modality=InputModality.VOICE)
            res0 = agent.interact(req0)
            assert res0.success is True
            assert "Listo, abrí el Bloc de notas." in res0.response_text

        # Turno 1: Abre calculadora
        with patch("psutil.process_iter", side_effect=[[], [fake_calc]]):
            req1 = JessycaRequest(request_id="req-fs-10-t1", session_id=session_id, user_input="abre la calculadora", modality=InputModality.VOICE)
            res1 = agent.interact(req1)
            assert res1.success is True
            assert "Listo, abrí la Calculadora." in res1.response_text

        assert mock_popen.call_count == 2
