from unittest.mock import Mock

from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.planner_engine import PlannerEngine


def test_explicit_memory_survives_restart_without_plaintext_secret(tmp_path):
    db = str(tmp_path / 'memory.db')
    storage = str(tmp_path / 'semantic')
    memory = MemoryEngine(db_path=db, storage_dir=storage)
    brain = JessycaBrain(memory_engine=memory, checkpoint_dir=str(tmp_path / 'checkpoints'))
    result = brain.process_request('Recuerda que mi lenguaje favorito es Python', session_id='audit')
    assert result.success
    restarted = MemoryEngine(db_path=db, storage_dir=storage)
    assert any('Python' in row['content'] for row in restarted.recall_facts('lenguaje favorito'))
    secret = 'dummy-audit-secret-917'
    result = brain.process_request('Recuerda mi contraseña bancaria ' + secret, session_id='audit')
    assert result.success
    assert secret not in str(memory.get_working_memory('audit'))
    assert secret not in str(memory.episodic_memory.get_recent_episodes())
    assert secret not in str(memory.recall_facts('contraseña'))


def test_conclusions_are_synthesis_not_desktop_typing():
    action, tool, _ = PlannerEngine()._map_subgoal_to_action('presenta conclusiones', {})
    assert action == 'summarize_results'
    assert tool == 'cognitive_synthesis'


def test_apps_writing_failure_is_not_reported_as_success(monkeypatch):
    from skills.apps_skill import WindowsAppsSkill
    from core.desktop.unified_controller import UnifiedDesktopController
    skill = WindowsAppsSkill()
    monkeypatch.setattr(skill.session_manager, 'adapter', Mock())
    monkeypatch.setattr(UnifiedDesktopController, 'write_in_window', lambda *a, **k: Mock(success=False))
    assert skill._type_into_app('notepad', 'audit') is False
