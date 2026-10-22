"""Regression checks for optional dependencies and OS safety boundaries."""
import asyncio
import subprocess
import sys
from unittest.mock import Mock

import pytest

from core.anydoc import adapter as anydoc_adapter
from core.anydoc.models import ConversionStatus
from core.integration.models import IntegrationContext, IntegrationStatus
from tools.filesystem.path_security import PathSecurityManager
from tools.filesystem.errors import UnsupportedPathError
from tools.process.process_service import ProcessService
from tools.process.errors import ProtectedProcessError


def test_anydoc_missing_dependency_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_adapter, 'anydoc', None)
    adapter = anydoc_adapter.AnyDocAdapter()
    assert asyncio.run(adapter.initialize()) is False
    assert adapter.status == IntegrationStatus.UNAVAILABLE
    assert asyncio.run(adapter.health_check()).is_healthy is False
    output = tmp_path / 'never-created.md'
    result = adapter.convert_file(str(tmp_path / 'absent.csv'), str(output))
    assert result.status == ConversionStatus.UNSUPPORTED
    assert not output.exists()
    result = asyncio.run(adapter.execute('document_processing.convert', IntegrationContext(session_id='missing')))
    assert not result.executed and not result.verified


def test_anydoc_import_without_optional_distribution():
    script = '''
import builtins
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == "anydoc":
        raise ModuleNotFoundError("simulated missing optional dependency", name="anydoc")
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
from core.anydoc import AnyDocAdapter
assert AnyDocAdapter().name == "anydoc"
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('pid', [0, 1, 4])
def test_reserved_process_ids_never_reach_process_backend(monkeypatch, pid):
    backend = Mock(side_effect=AssertionError('must reject before process lookup'))
    monkeypatch.setattr('tools.process.process_service.psutil.Process', backend)
    with pytest.raises(ProtectedProcessError):
        ProcessService().terminate_process(pid)
    backend.assert_not_called()


def test_foreign_drive_is_not_a_relative_filename(tmp_path):
    if sys.platform == 'win32':
        pytest.skip('Checks foreign Windows syntax on a non-Windows host')
    guard = PathSecurityManager(sandbox_root=tmp_path)
    with pytest.raises(UnsupportedPathError):
        guard.validate_and_canonicalize('C:secret.txt')


def test_windows_gui_launch_does_not_invoke_second_launcher(monkeypatch):
    import os
    from types import SimpleNamespace, ModuleType
    from core import application_session_manager as module

    adapter = module.WindowsApplicationAdapter()
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt', path=os.path, environ=os.environ))
    monkeypatch.setattr(module.shutil, 'which', lambda value: value)
    launcher = Mock(return_value=SimpleNamespace(pid=12345))
    monkeypatch.setattr(module.subprocess, 'Popen', launcher)
    monkeypatch.setattr(adapter, 'find_existing_session', lambda _: SimpleNamespace(hwnd=123, pid=12345))
    shell = Mock()
    package = ModuleType('win32com')
    client = ModuleType('win32com.client')
    client.Dispatch = Mock(return_value=shell)
    package.client = client
    monkeypatch.setitem(sys.modules, 'win32com', package)
    monkeypatch.setitem(sys.modules, 'win32com.client', client)
    session = adapter.launch(module.KNOWN_DESCRIPTORS['notepad'])
    launcher.assert_called_once_with(['notepad.exe'], shell=False)
    shell.ShellExecute.assert_not_called()
    assert session.pid == 12345 and session.hwnd == 123
