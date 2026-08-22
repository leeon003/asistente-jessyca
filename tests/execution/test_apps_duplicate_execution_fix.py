"""Tests de regresión para prevención de ejecución duplicada en windows.apps (test_apps_duplicate_execution_fix.py).

Verifica exhaustivamente los 10 escenarios obligatorios:
- TEST 1: Una petición 'abre el bloc de notas' genera exactamente 1 ejecución.
- TEST 2: Verificación lenta genera una sola ejecución.
- TEST 3: Polling de verificación no repite la ejecución.
- TEST 4: Skill devuelve SUCCESS sin segundas ejecuciones.
- TEST 5: Aplicación ya abierta no duplica procesos (Single-Instance reuse).
- TEST 6: Dos peticiones independientes (request_id=A, request_id=B) ejecutan independientemente.
- TEST 7: Conversación continua turno 0 ('notepad') y turno 1 ('calc') ejecutan 1 vez cada una.
- TEST 8: Entrada de modo voz ejecuta exactamente 1 vez.
- TEST 9: Fallo de STT / silencio no produce ninguna ejecución (0 ejecuciones).
- TEST 10: Callbacks, retries o session loop no causan invocaciones múltiples de una misma transcripción.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from core.execution.execution_verifier import get_execution_verifier
from core.execution.idempotency_guard import (
    get_idempotency_guard,
)
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


def test_01_single_request_single_execution() -> None:
    """TEST 1: Una petición 'abre el bloc de notas' produce exactamente UNA invocación de ejecución."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1001, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(request_id="req-test-01", session_id="sess-01", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert mock_popen.call_count == 1

        guard = get_idempotency_guard()
        records = guard.get_records_for_session("sess-01")
        assert len(records) == 1
        assert records[0].actual_execution_count == 1
        assert records[0].status == "SUCCEEDED"


def test_02_slow_verification_single_execution() -> None:
    """TEST 2: La verificación tarda pero produce una sola ejecución."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1002, "name": "notepad.exe"}

    # Primeros 3 polls de psutil no encuentran el proceso, el cuarto lo encuentra
    poll_sequence = [[], [], [], [fake_proc]]

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=poll_sequence):
        req = JessycaRequest(request_id="req-test-02", session_id="sess-02", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        # A pesar de los 4 ciclos de polling, Popen debe llamarse EXACTAMENTE una vez
        assert mock_popen.call_count == 1


def test_03_verification_polling_does_not_reexecute() -> None:
    """TEST 3: La verificación hace polling sin ejecutar nuevamente la acción."""
    verifier = get_execution_verifier()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1003, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [], [fake_proc]]):
        # Invocación directa del verificador
        evidence = verifier.verify_execution("open_application", "notepad.exe", {"nombre_app": "notepad"}, timeout_seconds=1.0)

        assert evidence.is_verified is True
        # El verificador NUNCA debe invocar subprocess.Popen
        mock_popen.assert_not_called()


def test_04_skill_success_no_second_execution() -> None:
    """TEST 4: La skill devuelve SUCCESS y no existe segunda ejecución."""
    skill = WindowsAppsSkill()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 1004, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        res = skill.ejecutar({"accion": "abrir", "nombre_app": "notepad"})

        assert res["exito"] is True
        assert res["execution_count"] == 1
        assert res["reused_instance"] is False
        assert mock_popen.call_count == 1


def test_05_already_open_app_single_instance_reuse() -> None:
    """TEST 5: La aplicación ya está abierta; se ejecuta 1 sola vez y se verifica el estado en Windows."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 4444, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", return_value=[fake_proc]):
        req = JessycaRequest(request_id="req-test-05", session_id="sess-05", user_input="Jessica abre el bloc de notas")
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert mock_popen.call_count == 1
        assert "Listo, abrí el Bloc de notas." in res.response_text


def test_06_independent_requests_execute_independently() -> None:
    """TEST 6: Dos peticiones independientes (request_id=A, request_id=B) ejecutan independientemente."""
    agent = JessycaLocalAgent.get_instance()
    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 2001, "name": "notepad.exe"}
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 2002, "name": "calc.exe"}

    with patch("subprocess.Popen") as mock_popen:
        # Petición A: Abre notepad
        with patch("psutil.process_iter", side_effect=[[], [fake_notepad]]):
            req_a = JessycaRequest(request_id="req-A", session_id="sess-06", user_input="Jessica abre el bloc de notas")
            res_a = agent.interact(req_a)
            assert res_a.success is True
            assert res_a.intent == "open_application"

        # Petición B: Abre calculadora (request_id diferente)
        with patch("psutil.process_iter", side_effect=[[], [fake_calc]]):
            req_b = JessycaRequest(request_id="req-B", session_id="sess-06", user_input="Jessica abre la calculadora")
            res_b = agent.interact(req_b)
            assert res_b.success is True
            assert res_b.intent == "open_application"

        # Cada una debe haber llamado a Popen 1 vez (total 2)
        assert mock_popen.call_count == 2


def test_07_continuous_conversation_turns() -> None:
    """TEST 7: Conversación continua: Turno 0 'notepad', Turno 1 'calc' ejecutan exactamente una vez cada una."""
    agent = JessycaLocalAgent.get_instance()
    fake_notepad = MagicMock()
    fake_notepad.info = {"pid": 3001, "name": "notepad.exe"}
    fake_calc = MagicMock()
    fake_calc.info = {"pid": 3002, "name": "calc.exe"}

    session_id = "sess-continuous-07"

    with patch("subprocess.Popen") as mock_popen:
        # Turno 0: Con wake word
        with patch("psutil.process_iter", side_effect=[[], [fake_notepad]]):
            req_turn0 = JessycaRequest(
                request_id="req-turn0",
                session_id=session_id,
                user_input="Jessica abre el bloc de notas",
                modality=InputModality.VOICE,
            )
            res0 = agent.interact(req_turn0)
            assert res0.success is True
            assert res0.intent == "open_application"

        # Turno 1: Conversación continua sin wake word
        with patch("psutil.process_iter", side_effect=[[], [fake_calc]]):
            req_turn1 = JessycaRequest(
                request_id="req-turn1",
                session_id=session_id,
                user_input="abre la calculadora",
                modality=InputModality.VOICE,
            )
            res1 = agent.interact(req_turn1)
            assert res1.success is True
            assert res1.intent == "open_application"

        assert mock_popen.call_count == 2


def test_08_voice_mode_single_execution() -> None:
    """TEST 8: Entrada de modo voz 'Jessica abre bloc de notas' genera exactamente 1 ejecución."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 5001, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(
            request_id="req-voice-08",
            session_id="sess-voice-08",
            user_input="Jessica Abre bloc de notas",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)

        assert res.success is True
        assert res.status == AgentExecutionState.COMPLETED
        assert mock_popen.call_count == 1


def test_09_stt_failure_zero_executions() -> None:
    """TEST 9: Silencio o fallo de STT no genera ninguna ejecución de procesos."""
    agent = JessycaLocalAgent.get_instance()

    with patch("subprocess.Popen") as mock_popen:
        # Texto vacío / ininteligible
        req = JessycaRequest(
            request_id="req-stt-fail",
            session_id="sess-09",
            user_input="",
            modality=InputModality.VOICE,
        )
        res = agent.interact(req)

        assert res.success is False
        assert mock_popen.call_count == 0


def test_10_duplicate_request_id_prevented_by_idempotency() -> None:
    """TEST 10: Una transcripción duplicada con el mismo request_id no provoca múltiples ejecuciones."""
    agent = JessycaLocalAgent.get_instance()
    fake_proc = MagicMock()
    fake_proc.info = {"pid": 6001, "name": "notepad.exe"}

    with patch("subprocess.Popen") as mock_popen, patch("psutil.process_iter", side_effect=[[], [fake_proc]]):
        req = JessycaRequest(
            request_id="req-duplicate-10",
            session_id="sess-10",
            user_input="Jessica abre el bloc de notas",
            modality=InputModality.VOICE,
        )
        # Primera invocación
        res1 = agent.interact(req)
        assert res1.success is True
        assert mock_popen.call_count == 1

        # Segunda invocación con el MISMO request_id (ej. retry accidental o loop duplicado)
        res2 = agent.interact(req)
        assert res2.success is True
        # El call_count DEBE seguir siendo exactamente 1
        assert mock_popen.call_count == 1
