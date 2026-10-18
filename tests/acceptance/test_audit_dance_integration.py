"""Brain -> planner -> real media selection -> simulated player/probe."""
from unittest.mock import Mock

import pytest

from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.memory_engine import MemoryEngine
from core.execution.execution_verifier import ExecutionEvidence
from skills.windows_media_skill import WindowsMediaSkill


@pytest.mark.parametrize('phrase', ['bailame', 'báilame', 'jessyca bailame', 'Jessyca, báilame', 'Jessica, báilame'])
def test_dance_requests_are_local_and_change_video(phrase, tmp_path, monkeypatch):
    directory = tmp_path / 'videos'
    directory.mkdir()
    for name in ('a.mp4', 'b.mp4', 'c.mp4'):
        (directory / name).write_bytes(b'simulated media')
    player = Mock()
    player.launch.return_value = (True, 'PLAYBACK_LAUNCHED', None)
    verifier = Mock()
    verifier.verify_execution.side_effect = lambda **kw: ExecutionEvidence(
        'simulated_probe', kw['target'], True, {'simulated': True}
    )
    monkeypatch.setattr('skills.windows_media_skill.get_execution_verifier', lambda: verifier)
    skill = WindowsMediaSkill(authorized_directory=directory, player=player)
    brain = JessycaBrain(memory_engine=MemoryEngine(db_path=str(tmp_path / 'memory.db')),
                        checkpoint_dir=str(tmp_path / 'checkpoints'))

    def executor(action, tool, params):
        assert tool == 'windows_media'
        assert action == 'play_random_video'
        assert params['target_dir'].lower() == r'd:\bailes de ia'
        # Redirect disk access only at the filesystem boundary for an isolated test.
        result = skill.ejecutar({'accion': action})
        return result['exito'], result, None

    for _ in range(5):
        response = brain.process_request(phrase, session_id='audit', tool_executor=executor,
                                         metadata={'stt_confidence': 0.95})
        assert response.success
    paths = [call.args[0] for call in player.launch.call_args_list]
    assert len(paths) == 5
    assert all(a != b for a, b in zip(paths, paths[1:]))
