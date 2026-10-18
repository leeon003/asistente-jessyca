"""Independent audit: dispatch is not evidence of playback."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.execution.execution_verifier import ExecutionEvidence
from skills.windows_media_skill import WindowsMediaSkill


@pytest.fixture
def media(tmp_path, monkeypatch):
    for name in ('a.mp4', 'b.mp4', 'c.mp4'):
        (tmp_path / name).write_bytes(b'test fixture, not playable media')
    player = Mock()
    player.launch.return_value = (True, 'PLAYBACK_LAUNCHED', None)
    verifier = Mock()
    verifier.verify_execution.return_value = ExecutionEvidence(
        'playback_probe', 'test', False, {'reason': 'not observed'}
    )
    monkeypatch.setattr('skills.windows_media_skill.get_execution_verifier', lambda: verifier)
    return WindowsMediaSkill(authorized_directory=tmp_path, player=player), player, verifier


def test_launch_without_observation_is_not_success(media):
    skill, player, verifier = media
    result = skill.ejecutar({'accion': 'play_random_video'})
    assert player.launch.call_count == 1
    assert result['exito'] is False
    assert result['status'] == 'PLAYBACK_UNVERIFIED'
    assert result['execution_count'] == 1
    assert result['evidence']['is_verified'] is False
    assert 'verified' not in verifier.verify_execution.call_args.kwargs['parameters']


def test_explicit_video_is_respected(media):
    skill, player, verifier = media
    target = skill.authorized_directory / 'b.mp4'
    skill._select_random_video = lambda videos: videos[0]
    result = skill.ejecutar({'accion': 'play_video', 'file_path': str(target)})
    assert player.launch.call_args.args[0].resolve() == target.resolve()


def test_repeated_dance_never_repeats_previous(media):
    skill, player, verifier = media
    verifier.verify_execution.side_effect = lambda **kw: ExecutionEvidence(
        'test_probe', kw['target'], True, {'simulated': True}
    )
    for _ in range(100):
        result = skill.ejecutar({'accion': 'play_random_video'})
        assert result['exito'] is True
    paths = [call.args[0] for call in player.launch.call_args_list]
    assert all(a != b for a, b in zip(paths, paths[1:]))
    assert len(set(paths)) > 1


def test_missing_explicit_video_does_not_launch_another(media):
    skill, player, verifier = media
    result = skill.ejecutar({'accion': 'play_video', 'file_path': str(skill.authorized_directory / 'missing.mp4')})
    assert result['exito'] is False
    player.launch.assert_not_called()


def test_player_exception_is_controlled(media):
    skill, player, verifier = media
    player.launch.side_effect = OSError('player unavailable')
    result = skill.ejecutar({'accion': 'play_random_video'})
    assert result['exito'] is False
    assert result['status'] == 'PLAYBACK_FAILED'


def test_verifier_exception_does_not_trigger_second_launch(media):
    skill, player, verifier = media
    verifier.verify_execution.side_effect = RuntimeError('probe unavailable')
    result = skill.ejecutar({'accion': 'play_random_video'})
    assert result['exito'] is False
    assert result['status'] == 'PLAYBACK_UNVERIFIED'
    assert result['execution_count'] == 1
    assert player.launch.call_count == 1
