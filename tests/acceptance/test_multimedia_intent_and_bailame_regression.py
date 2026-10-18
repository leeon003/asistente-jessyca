"""Suite exhaustiva de pruebas de regresión para la corrección de comprensión y ejecución de órdenes (FASE 7).

Cubre los 15 escenarios obligatorios:
1. «Jessica, báilame»
2. «Reproduce un video aleatorio de Bailes de IA»
3. «Abre los videos del disco D»
4. «Busca la carpeta Bailes de IA»
5. «Reproduce música de YouTube»
6. «Reproduce música de mi computadora»
7. Carpeta no encontrada
8. Carpeta sin videos
9. Transcripción de baja confianza
10. Fallo al iniciar el reproductor
11. Verificación de reproducción
12. Aprendizaje persistente del comando
13. Ausencia de respuestas repetitivas
14. Ausencia de falsos éxitos
15. Compatibilidad con el orbe AURORA
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.cancellation import CancellationToken
from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.contracts import PlanStepExecutionState, ProcedureLifecycleState
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.planner_engine import PlannerEngine
from core.cognitive_brain.reasoning_engine import ReasoningEngine
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState, InputModality, JessycaRequest
from skills.windows_media_skill import IMediaPlayer, WindowsMediaSkill


class FakeSuccessMediaPlayer:
    """Reproductor simulado para pruebas deterministas sin abrir ventanas reales."""

    def __init__(self) -> None:
        self.launched_videos: list[Path] = []

    def launch(self, video_path: Path) -> tuple[bool, str, int | None]:
        self.launched_videos.append(video_path)
        return True, "PLAYBACK_LAUNCHED", 12345


class FakeFailingMediaPlayer:
    """Reproductor simulado que falla al iniciar."""

    def launch(self, video_path: Path) -> tuple[bool, str, int | None]:
        return False, "SimulatedPlayerCrash: Codecs unavailable", None


@pytest.fixture
def mock_brain(tmp_path: Path):
    """Instancia aislada de JessycaBrain con base de datos temporal."""
    db_file = str(tmp_path / "test_brain_mem.db")
    chk_dir = str(tmp_path / "checkpoints")
    mem_engine = MemoryEngine(db_path=db_file)
    brain = JessycaBrain(
        memory_engine=mem_engine,
        reasoning_engine=ReasoningEngine(),
        planner_engine=PlannerEngine(),
        checkpoint_dir=chk_dir,
    )
    return brain


class TestMultimediaIntentAndBailameRegression:
    """Suite de regresión para las 15 verificaciones de reproducción multimedia y comprensión."""

    def test_01_jessica_bailame_intent_and_execution(self, mock_brain):
        """Escenario 1: «Jessica, báilame» ejecuta media local y NUNCA YouTube."""
        executed_skills = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_skills.append((action_name, tool_name))
            assert "youtube" not in tool_name.lower()
            assert "youtube" not in action_name.lower()
            return True, {"video_nombre": "jessyca1.mp4", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Jessica, báilame",
            session_id="test_s1",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        assert any(t[1] == "windows_media" for t in executed_skills)
        assert not any("youtube" in t[1].lower() for t in executed_skills)
        # Respuesta concisa y natural
        assert "reproduciéndose" in res.response_text.lower()
        # Ausencia de repetición de la orden completa
        assert "he completado la tarea: jessica, báilame" not in res.response_text.lower()

    def test_02_reproduce_video_aleatorio_bailes_de_ia(self, mock_brain):
        """Escenario 2: «Reproduce un video aleatorio de Bailes de IA» enruta a media local."""
        executed_skills = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_skills.append(tool_name)
            return True, {"video_nombre": "jessyca2.mp4", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Reproduce un video aleatorio de Bailes de IA",
            session_id="test_s2",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        assert "windows_media" in executed_skills
        assert "browser_youtube" not in executed_skills

    def test_03_abre_los_videos_del_disco_d(self, mock_brain):
        """Escenario 3: «Abre los videos del disco D» abre el Explorador de Windows, no YouTube."""
        executed_tools = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append((action_name, tool_name, params))
            return True, {"status": "OPENED", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Abre los videos del disco D",
            session_id="test_s3",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        assert any(t[0] == "open_folder" or t[1] == "app_launcher" for t in executed_tools)
        assert not any("youtube" in t[1].lower() for t in executed_tools)

    def test_04_busca_la_carpeta_bailes_de_ia(self, mock_brain):
        """Escenario 4: «Busca la carpeta Bailes de IA» busca en el disco local, no en internet."""
        executed_tools = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append((action_name, tool_name, params))
            return True, {"found_folders": ["D:\\bailes de ia"], "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Busca la carpeta Bailes de IA",
            session_id="test_s4",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        # Debe usar búsqueda en filesystem, NUNCA búsqueda web ni YouTube
        assert any(t[1] == "file_search" or "search" in t[0] for t in executed_tools)
        assert not any(t[1] == "browser_search" for t in executed_tools)
        assert not any(t[1] == "browser_youtube" for t in executed_tools)

    def test_05_reproduce_musica_de_youtube(self, mock_brain):
        """Escenario 5: «Reproduce música de YouTube» activa browser_youtube legítimamente."""
        executed_tools = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append((action_name, tool_name, params))
            return True, {"playback_started": True, "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Reproduce música de YouTube",
            session_id="test_s5",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        assert any(t[1] == "browser_youtube" for t in executed_tools)

    def test_06_reproduce_musica_de_mi_computadora(self, mock_brain):
        """Sin carpeta explícita, solicita ubicación y no sustituye música por vídeos de baile."""
        executed_tools = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append((action_name, tool_name, params))
            return True, {"video_nombre": "audio1.mp3", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Reproduce música de mi computadora",
            session_id="test_s6",
            tool_executor=mock_tool_executor,
        )

        assert res.success is False
        assert res.error == "ClarificationNeeded"
        assert not executed_tools
        assert not any(t[1] == "browser_youtube" for t in executed_tools)

    def test_07_carpeta_no_encontrada(self, tmp_path: Path):
        """Escenario 7: Carpeta no encontrada retorna fallo claro y NO falso éxito."""
        fake_player = FakeSuccessMediaPlayer()
        non_existent_folder = tmp_path / "carpeta_inexistente_123"
        skill = WindowsMediaSkill(authorized_directory=non_existent_folder, player=fake_player)

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is False
        assert res["status"] == "DIRECTORY_NOT_FOUND"
        assert res["execution_count"] == 0
        assert "No encuentro la carpeta" in res["mensaje"]

    def test_08_carpeta_sin_videos(self, tmp_path: Path):
        """Escenario 8: Carpeta vacía o sin vídeos compatibles retorna fallo descriptivo."""
        fake_player = FakeSuccessMediaPlayer()
        empty_folder = tmp_path / "carpeta_vacia"
        empty_folder.mkdir(parents=True, exist_ok=True)
        # Crear un archivo no multimedia (.txt)
        (empty_folder / "nota.txt").write_text("no video")

        skill = WindowsMediaSkill(authorized_directory=empty_folder, player=fake_player)
        res = skill.ejecutar({"accion": "play_random_video"})

        assert res["exito"] is False
        assert res["status"] == "NO_VIDEOS_FOUND"
        assert res["execution_count"] == 0
        assert "No encontré" in res["mensaje"]

    def test_09_transcripcion_baja_confianza(self, mock_brain):
        """Escenario 9: Transcripción con stt_confidence < 0.60 solicita aclaración sin ejecutar."""
        executed_tools = []

        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append(tool_name)
            return True, {}, None

        res = mock_brain.process_request(
            user_input="baila algo",
            session_id="test_s9",
            tool_executor=mock_tool_executor,
            metadata={"stt_confidence": 0.40},
        )

        assert res.success is False
        assert res.error == "ClarificationNeeded"
        assert len(executed_tools) == 0  # Cero herramientas ejecutadas
        assert "¿Podrías aclararme" in res.response_text or "¿Quieres" in res.response_text

    def test_10_fallo_al_iniciar_reproductor(self, tmp_path: Path):
        """Escenario 10: Fallo en el lanzamiento del reproductor retorna error real sin falso éxito."""
        failing_player = FakeFailingMediaPlayer()
        video_folder = tmp_path / "bailes"
        video_folder.mkdir(parents=True, exist_ok=True)
        (video_folder / "baile_test.mp4").write_bytes(b"\x00" * 1024)

        skill = WindowsMediaSkill(authorized_directory=video_folder, player=failing_player)
        res = skill.ejecutar({"accion": "play_random_video"})

        assert res["exito"] is False
        assert res["status"] == "PLAYBACK_FAILED"
        assert res["execution_count"] == 0
        assert "no pude iniciar su reproducción" in res["mensaje"]

    def test_11_verificacion_de_reproduccion(self, tmp_path: Path, monkeypatch):
        """Escenario 11: Reproducción exitosa incluye evidencia verificada determinista."""
        from core.execution.execution_verifier import ExecutionEvidence
        verifier = MagicMock()
        verifier.verify_execution.side_effect = lambda **kw: ExecutionEvidence(
            "simulated_playback", kw["target"], True, {"simulated": True}
        )
        monkeypatch.setattr("skills.windows_media_skill.get_execution_verifier", lambda: verifier)
        success_player = FakeSuccessMediaPlayer()
        video_folder = tmp_path / "bailes_verif"
        video_folder.mkdir(parents=True, exist_ok=True)
        test_video = video_folder / "test_danza.mp4"
        test_video.write_bytes(b"\x00" * 2048)

        skill = WindowsMediaSkill(authorized_directory=video_folder, player=success_player)
        res = skill.ejecutar({"accion": "play_random_video"})

        assert res["exito"] is True
        assert res["status"] == "PLAYBACK_LAUNCHED"
        assert res["video_nombre"] == "test_danza.mp4"
        assert res["execution_count"] == 1
        assert "evidence" in res
        assert res["evidence"].get("is_verified") is True or res["evidence"].get("verified") is True

    def test_12_aprendizaje_persistente_del_comando(self, mock_brain):
        """Escenario 12: «Jessica, báilame» usa el procedimiento persistente 'reproducir_baile_local'."""
        # 1. Verificar que el procedimiento núcleo fue asegurado en estado VALIDATED
        procs = mock_brain.memory_engine.procedural_memory.find_matching("báilame", only_validated=True)
        assert len(procs) >= 1
        proc = procs[0]
        assert proc.name == "reproducir_baile_local"
        assert proc.state == ProcedureLifecycleState.VALIDATED
        assert "windows_media" in proc.authorized_tools

        # 2. Ejecutar la solicitud y verificar el log del hit procedimental
        executed_tools = []
        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            executed_tools.append((action_name, tool_name))
            return True, {"video_nombre": "jessyca_hit.mp4", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="Jessica, báilame",
            session_id="test_s12",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        assert any(t[1] == "windows_media" for t in executed_tools)

    def test_13_ausencia_de_respuestas_repetitivas(self, mock_brain):
        """Escenario 13: La respuesta hablada es natural y no repite plantillas que repiten la orden."""
        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            return True, {"video_nombre": "jessyca15.mp4", "is_verified": True}, None

        res = mock_brain.process_request(
            user_input="por favor reproduce los videos locales de la carpeta Bailes de IA en el disco D",
            session_id="test_s13",
            tool_executor=mock_tool_executor,
        )

        assert res.success is True
        # Debe responder concisamente
        assert res.response_text == "Listo, ya está reproduciéndose jessyca15.mp4."
        # NO debe contener el texto del usuario repetido
        assert "por favor reproduce los videos locales" not in res.response_text

    def test_14_ausencia_de_falsos_exitos(self, mock_brain):
        """Escenario 14: Si una herramienta falla o no se verificó, NUNCA se reporta éxito."""
        def mock_tool_executor(action_name: str, tool_name: str, params: dict):
            # Fallo explícito
            return False, {"exito": False}, "Fallo en verificación de proceso"

        res = mock_brain.process_request(
            user_input="Jessica, báilame",
            session_id="test_s14",
            tool_executor=mock_tool_executor,
        )

        assert res.success is False
        assert res.error is not None
        assert "Listo, ya está reproduciéndose" not in res.response_text
        assert "No se pudo completar la acción" in res.response_text

    def test_15_compatibilidad_con_orbe_aurora(self, mock_brain):
        """Escenario 15: Compatibilidad con el orbe AURORA verificando notificaciones de estado."""
        from interfaces.aurora.visual_states import AuroraVisualState
        from interfaces.aurora.bridge import AuroraBridge

        bridge = AuroraBridge.get_instance()
        states_received = []

        def _state_listener(st: AuroraVisualState):
            states_received.append(st)

        bridge.add_state_listener(_state_listener)

        try:
            # Notificar inicio de cognición y herramienta
            bridge.notify_cognition("routing")
            bridge.notify_tool_start("windows.media")

            assert AuroraVisualState.ROUTING in states_received
            assert AuroraVisualState.EXECUTING in states_received
        finally:
            bridge.remove_state_listener(_state_listener)
