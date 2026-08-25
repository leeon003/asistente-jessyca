r"""Suite completa de pruebas unitarias y de integración para Smart Media Playback (Fase "Jessyca, báilame").

Verifica:
TEST 1: Detección de "Jessyca bailame" -> play_random_video
TEST 2: Variantes naturales ("Jessica bailame", "Jessyca, bailame", "Jessyca ponme un baile", etc.)
TEST 3: Selección de exactamente 1 vídeo en directorio con múltiples archivos
TEST 4: Filtrado estricto (a.mp4 elegible, malicious.exe y doc.pdf ignorados)
TEST 5: Carpeta vacía -> NO_VIDEOS_FOUND
TEST 6: Carpeta inexistente -> DIRECTORY_NOT_FOUND
TEST 7: Prevención de repetición inmediata con múltiples vídeos
TEST 8: Repetición permitida cuando existe un único vídeo
TEST 9: Denegación de ruta fuera del directorio autorizado (DENY)
TEST 10: Denegación de intento de Path Traversal (..\otro_video.mp4 -> DENY)
TEST 11: Denegación de intento de ejecutar .exe -> DENY
TEST 12: Fallo de launcher -> PLAYBACK_FAILED (0 falsos éxitos)
TEST 13: Flujo completo de voz (VOICE_TRANSCRIPT -> play_random_video -> windows.media -> playback -> verif -> resp)
TEST 14: Prevención estricta de ejecución duplicada (1 request -> 1 launch, verif no relanza)
TEST 15: Integración y registro seguro en ExperienceLogger
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from core.emergency_stop import EmergencyStopManager
from core.experience import (
    get_experience_logger,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    InputModality,
    JessycaRequest,
)
from skills.windows_media_skill import (
    WindowsMediaSkill,
)


class MockMediaPlayer:
    """Mock determinista de IMediaPlayer para pruebas unitarias."""

    def __init__(self, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.launch_count = 0
        self.launched_paths: list[Path] = []

    def launch(self, video_path: Path) -> tuple[bool, str, int | None]:
        self.launch_count += 1
        self.launched_paths.append(video_path)
        if self.should_succeed:
            return True, "PLAYBACK_LAUNCHED", 9999
        return False, "Failed to launch mock player", None


@pytest.fixture
def temp_dance_dir() -> Any:
    """Crea un directorio temporal aislado para pruebas de Smart Media Playback."""
    tmp = tempfile.mkdtemp(prefix="jessyca_dance_test_")
    path_obj = Path(tmp)
    yield path_obj
    shutil.rmtree(tmp, ignore_errors=True)


class TestSmartMediaPlayback:
    """Suite de validación formal de Smart Media Playback."""

    def setup_method(self) -> None:
        EmergencyStopManager.get_instance().reset("test_media_setup")

    # ══════════════════════════════════════════════════════════════════
    # TEST 1 & TEST 2: INTENT DETECTION & NATURAL VARIANTS
    # ══════════════════════════════════════════════════════════════════

    def test_01_detect_jessyca_bailame(self) -> None:
        """TEST 1: Detecta correctamente 'Jessyca bailame' -> play_random_video."""
        agent = JessycaLocalAgent.get_instance()
        intent, params, is_ambiguous = agent._analyze_intent("Jessyca bailame", "test_sess_01")
        assert intent == "play_random_video"
        assert is_ambiguous is False

    @pytest.mark.parametrize(
        "phrase",
        [
            "Jessica bailame",
            "Jessyca, bailame",
            "Jessica, bailame",
            "Jessyca ponme un baile",
            "Jessyca reproduce un baile",
            "Jessyca quiero ver un baile",
            "bailame",
            "báilame",
            "ponme un baile",
            "reproduce un baile",
            "quiero ver un baile",
        ],
    )
    def test_02_detect_natural_variants(self, phrase: str) -> None:
        """TEST 2: Variantes naturales resuelven a play_random_video."""
        agent = JessycaLocalAgent.get_instance()
        intent, params, is_ambiguous = agent._analyze_intent(phrase, "test_sess_02")
        assert intent == "play_random_video", f"Fallo al detectar intent para frase: '{phrase}'"
        assert is_ambiguous is False

    # ══════════════════════════════════════════════════════════════════
    # TEST 3: SELECCIÓN DE 1 VÍDEO CON MÚLTIPLES ARCHIVOS
    # ══════════════════════════════════════════════════════════════════

    def test_03_select_single_video_from_multiple(self, temp_dance_dir: Path) -> None:
        """TEST 3: Carpeta contiene a.mp4, b.mp4, c.mp4 -> exactamente 1 vídeo seleccionado."""
        for name in ("a.mp4", "b.mp4", "c.mp4"):
            (temp_dance_dir / name).write_bytes(b"dummy video content")

        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is True
        assert res["status"] == "PLAYBACK_LAUNCHED"
        assert res["execution_count"] == 1
        assert res["video_nombre"] in ("a.mp4", "b.mp4", "c.mp4")
        assert mock_player.launch_count == 1
        assert len(mock_player.launched_paths) == 1

    # ══════════════════════════════════════════════════════════════════
    # TEST 4: FILTRADO ESTRICTO DE EXTENSIONES
    # ══════════════════════════════════════════════════════════════════

    def test_04_strict_file_filtering(self, temp_dance_dir: Path) -> None:
        """TEST 4: Carpeta contiene a.mp4, malicious.exe, document.pdf -> solo a.mp4 es elegible."""
        (temp_dance_dir / "a.mp4").write_bytes(b"video data")
        (temp_dance_dir / "malicious.exe").write_bytes(b"malware data")
        (temp_dance_dir / "document.pdf").write_bytes(b"pdf data")
        (temp_dance_dir / "script.ps1").write_bytes(b"ps1 data")

        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        valid = skill._discover_valid_videos(temp_dance_dir)
        assert len(valid) == 1
        assert valid[0].name == "a.mp4"

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is True
        assert res["video_nombre"] == "a.mp4"
        assert mock_player.launched_paths[0].name == "a.mp4"

    # ══════════════════════════════════════════════════════════════════
    # TEST 5: CARPETA VACÍA
    # ══════════════════════════════════════════════════════════════════

    def test_05_empty_directory(self, temp_dance_dir: Path) -> None:
        """TEST 5: Carpeta vacía -> NO_VIDEOS_FOUND."""
        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is False
        assert res["status"] == "NO_VIDEOS_FOUND"
        assert res["error_code"] == "NO_VIDEOS_FOUND"
        assert mock_player.launch_count == 0

    # ══════════════════════════════════════════════════════════════════
    # TEST 6: CARPETA INEXISTENTE
    # ══════════════════════════════════════════════════════════════════

    def test_06_non_existent_directory(self) -> None:
        """TEST 6: Carpeta inexistente -> DIRECTORY_NOT_FOUND."""
        fake_path = Path("Z:\\Ruta_Ficticia_Inexistente_12345")
        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=fake_path, player=mock_player)

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is False
        assert res["status"] == "DIRECTORY_NOT_FOUND"
        assert res["error_code"] == "DIRECTORY_NOT_FOUND"
        assert mock_player.launch_count == 0

    # ══════════════════════════════════════════════════════════════════
    # TEST 7: EVITAR REPETICIÓN INMEDIATA CON MÚLTIPLES VÍDEOS
    # ══════════════════════════════════════════════════════════════════

    def test_07_avoid_immediate_repetition_multi_video(self, temp_dance_dir: Path) -> None:
        """TEST 7: Dos peticiones consecutivas con 2 vídeos -> evita repetir el mismo."""
        (temp_dance_dir / "baile1.mp4").write_bytes(b"video 1")
        (temp_dance_dir / "baile2.mp4").write_bytes(b"video 2")

        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        # 1ra petición
        res1 = skill.ejecutar({"accion": "play_random_video"})
        assert res1["exito"] is True
        v1 = res1["video_nombre"]

        # 2da petición -> debe ser el otro vídeo
        res2 = skill.ejecutar({"accion": "play_random_video"})
        assert res2["exito"] is True
        v2 = res2["video_nombre"]

        assert v1 != v2, f"Se repitió inmediatamente el vídeo '{v1}' habiendo 2 disponibles"

    # ══════════════════════════════════════════════════════════════════
    # TEST 8: PERMITIR REPETICIÓN CUANDO SOLO EXISTE 1 VÍDEO
    # ══════════════════════════════════════════════════════════════════

    def test_08_allow_repetition_single_video(self, temp_dance_dir: Path) -> None:
        """TEST 8: Solo existe un vídeo -> puede reproducirse repetidamente."""
        (temp_dance_dir / "solo_uno.mp4").write_bytes(b"video unico")

        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        res1 = skill.ejecutar({"accion": "play_random_video"})
        assert res1["exito"] is True
        assert res1["video_nombre"] == "solo_uno.mp4"

        res2 = skill.ejecutar({"accion": "play_random_video"})
        assert res2["exito"] is True
        assert res2["video_nombre"] == "solo_uno.mp4"

    # ══════════════════════════════════════════════════════════════════
    # TEST 9, 10 & 11: SEGURIDAD, PATH TRAVERSAL Y EJECUTABLES
    # ══════════════════════════════════════════════════════════════════

    def test_09_deny_path_outside_authorized_directory(self, temp_dance_dir: Path) -> None:
        """TEST 9: Ruta seleccionada fuera del directorio autorizado -> DENY."""
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir)
        res = skill.ejecutar({"accion": "play_random_video", "path": "C:\\Windows\\System32\\video.mp4"})
        assert res["exito"] is False
        assert res["status"] == "DENIED"

    def test_10_deny_path_traversal_attempt(self, temp_dance_dir: Path) -> None:
        """TEST 10: Intentar seleccionar ..\\otro_video.mp4 -> DENY."""
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir)
        traversal_path = str(temp_dance_dir / ".." / "otro_video.mp4")
        res = skill.ejecutar({"accion": "play_random_video", "path": traversal_path})
        assert res["exito"] is False
        assert res["status"] == "DENIED"

    def test_11_deny_executable_attempt(self, temp_dance_dir: Path) -> None:
        """TEST 11: Intentar ejecutar un .exe -> DENY."""
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir)
        exe_path = str(temp_dance_dir / "virus.exe")
        res = skill.ejecutar({"accion": "play_random_video", "path": exe_path})
        assert res["exito"] is False
        assert res["status"] == "DENIED"

    # ══════════════════════════════════════════════════════════════════
    # TEST 12: FALLO DE LAUNCHER -> PLAYBACK_FAILED
    # ══════════════════════════════════════════════════════════════════

    def test_12_launcher_failure_reports_failed(self, temp_dance_dir: Path) -> None:
        """TEST 12: Launcher falla -> PLAYBACK_FAILED y NO SUCCESS."""
        (temp_dance_dir / "baile.mp4").write_bytes(b"video data")
        failing_player = MockMediaPlayer(should_succeed=False)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=failing_player)

        res = skill.ejecutar({"accion": "play_random_video"})
        assert res["exito"] is False
        assert res["status"] == "PLAYBACK_FAILED"
        assert res["error_code"] == "PLAYBACK_FAILED"
        assert "no pude iniciar su reproducción" in res["mensaje"]

    # ══════════════════════════════════════════════════════════════════
    # TEST 13: TEST DE FLUJO DE VOZ COMPLETO
    # ══════════════════════════════════════════════════════════════════

    def test_13_voice_turn_flow(self, temp_dance_dir: Path) -> None:
        """TEST 13: Flujo de voz completo con 1 sola ejecución y respuesta natural."""
        (temp_dance_dir / "salsa.mp4").write_bytes(b"salsa video")
        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        agent = JessycaLocalAgent.get_instance()
        agent.skill_manager.registry.register_skill(skill, replace=True)

        req = JessycaRequest(
            user_input="Jessica bailame",
            modality=InputModality.VOICE,
            session_id="voice_test_sess",
            request_id="req_voice_test_13",
        )

        resp = agent.interact(req)
        assert resp.success is True
        assert resp.intent == "play_random_video"
        assert resp.selected_skill == "windows.media@1.0.0"
        assert "Claro" in resp.response_text or "baile" in resp.response_text
        assert mock_player.launch_count == 1

    # ══════════════════════════════════════════════════════════════════
    # TEST 14: TEST DE PREVENCIÓN DE DUPLICACIÓN
    # ══════════════════════════════════════════════════════════════════

    def test_14_anti_duplication_single_execution(self, temp_dance_dir: Path) -> None:
        """TEST 14: Una sola frase no debe provocar múltiples reproducciones."""
        (temp_dance_dir / "bachata.mp4").write_bytes(b"bachata video")
        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        agent = JessycaLocalAgent.get_instance()
        agent.skill_manager.registry.register_skill(skill, replace=True)

        req = JessycaRequest(
            user_input="Jessica, bailame",
            session_id="anti_dup_sess",
            request_id="req_anti_dup_14",
        )

        resp = agent.interact(req)
        assert resp.success is True
        assert mock_player.launch_count == 1

        # Reenvío de la misma petición con idéntico request_id (idempotencia)
        resp_dup = agent.interact(req)
        assert resp_dup.success is True
        assert mock_player.launch_count == 1, "Idempotency guard no bloqueó la segunda invocación duplicada"

    # ══════════════════════════════════════════════════════════════════
    # TEST 15: EXPERIENCE LOGGER INTEGRATION
    # ══════════════════════════════════════════════════════════════════

    def test_15_experience_logger_records_smart_playback(self, temp_dance_dir: Path) -> None:
        """TEST 15: Verifica que la experiencia se registre correctamente en ExperienceLogger."""
        (temp_dance_dir / "tango.mp4").write_bytes(b"tango video")
        mock_player = MockMediaPlayer(should_succeed=True)
        skill = WindowsMediaSkill(authorized_directory=temp_dance_dir, player=mock_player)

        agent = JessycaLocalAgent.get_instance()
        agent.skill_manager.registry.register_skill(skill, replace=True)

        exp_logger = get_experience_logger()
        exp_logger.enable()

        req = JessycaRequest(
            user_input="Jessyca quiero ver un baile",
            session_id="exp_sess_15",
            request_id="req_exp_15_smart",
        )

        resp = agent.interact(req)
        assert resp.success is True

        records = exp_logger.repository.get_by_correlation_id("req_exp_15_smart")
        assert len(records) >= 1
        exp = records[0]
        assert exp.intent is not None
        assert exp.intent.name == "play_random_video"
        assert exp.metadata.skill_used == "windows.media@1.0.0"
