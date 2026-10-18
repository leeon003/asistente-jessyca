from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor

from core.cognitive_brain.contracts import ContextBundle
from core.cognitive_brain.reasoning_engine import ReasoningEngine
from core.cognitive_brain.planner_engine import PlannerEngine
from core.execution.execution_verifier import ExecutionEvidence, ExecutionVerifier
from core.media_playback import MediaPlaybackVerificationStrategy
from skills.windows_media_skill import WindowsMediaSkill


def test_explicit_folder_is_not_dance():
    result = ReasoningEngine().comprehend('abre la carpeta Bailes de IA', ContextBundle())
    assert result.intent_category == 'open_folder'
    plan = PlannerEngine().create_plan(result, ['app_launcher'])
    assert plan.steps[0].action_name == 'open_folder'


def test_explicit_audio_file_path_reaches_media_skill():
    result = ReasoningEngine().comprehend(r'reproduce música de "D:\Musica\tema.mp3"', ContextBundle())
    plan = PlannerEngine().create_plan(result, ['windows_media'])
    assert plan.steps[0].parameters['file_path'] == r'D:\Musica\tema.mp3'
    assert plan.steps[0].parameters['target_dir'] == r'D:\Musica'
    assert plan.steps[0].parameters['media_type'] == 'audio'


def test_music_without_location_requests_clarification():
    result = ReasoningEngine().comprehend('reproduce música de mi computadora', ContextBundle())
    assert result.is_ambiguous
    assert not result.requires_action


def test_repeat_state_survives_new_skill_and_concurrent_requests(tmp_path, monkeypatch):
    for name in ('a.mp4', 'b.mp4', 'c.mp4'):
        (tmp_path / name).write_bytes(b'test')
    player = Mock()
    player.launch.return_value = (True, 'ok', 123)
    verifier = Mock()
    verifier.verify_execution.side_effect = lambda **kw: ExecutionEvidence('simulated', kw['target'], True)
    monkeypatch.setattr('skills.windows_media_skill.get_execution_verifier', lambda: verifier)
    state = tmp_path / 'state.json'
    first = WindowsMediaSkill(tmp_path, player, state_path=state)
    previous = first.ejecutar({'accion': 'play_random_video'})['video_nombre']
    second = WindowsMediaSkill(tmp_path, player, state_path=state)
    current = second.ejecutar({'accion': 'play_random_video'})['video_nombre']
    assert current != previous
    player.reset_mock()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: second.ejecutar({'accion': 'play_random_video'}), range(30)))
    paths = [call.args[0] for call in player.launch.call_args_list]
    assert len(paths) == 30
    assert all(a != b for a, b in zip(paths, paths[1:]))


def test_audio_directory_never_selects_video(tmp_path, monkeypatch):
    (tmp_path / 'song.mp3').write_bytes(b'test')
    (tmp_path / 'dance.mp4').write_bytes(b'test')
    player = Mock()
    player.launch.return_value = (False, 'simulated failure', None)
    skill = WindowsMediaSkill(tmp_path, player)
    skill.ejecutar({'accion': 'play_local_music'})
    assert player.launch.call_args.args[0].suffix == '.mp3'


def test_media_verifier_does_not_trust_verified_flag():
    strategy = ExecutionVerifier().get_strategy('play_media')
    assert isinstance(strategy, MediaPlaybackVerificationStrategy)
    evidence = strategy.verify('play_media', 'file.mp4', {'verified': True})
    assert not evidence.is_verified
