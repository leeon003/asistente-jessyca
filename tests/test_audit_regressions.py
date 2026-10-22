import ast
from pathlib import Path
from types import SimpleNamespace
import sys

def test_computer_use_constructor_preserves_failsafe(monkeypatch):
    from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
    fake = SimpleNamespace(FAILSAFE=True)
    monkeypatch.setitem(sys.modules, 'pyautogui', fake)
    ComputerUseAdapter()
    assert fake.FAILSAFE is True

def test_settings_fields_have_one_definition():
    root = Path(__file__).resolve().parent
    tree = ast.parse((root.parent / 'config/settings.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AppSettings')
    fields = [n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)]
    assert len(fields) == len(set(fields))

def test_registry_public_alias_is_canonical():
    from tools.registry import ToolRegistry, get_tool_registry
    from tools.tool_registry import ToolRegistry as Canonical, get_tool_registry as canonical_get
    assert ToolRegistry is Canonical
    assert get_tool_registry is canonical_get
