"""Pruebas unitarias de PluginExecutionSandbox (Etapa 14.3).

REQUISITOS PROBADOS:
1. Intentar leer fuera del sandbox lanza PluginSandboxViolationError.
2. Intentar escribir fuera del sandbox lanza PluginSandboxViolationError.
3. Acceder a capacidades no declaradas lanza PluginSandboxViolationError.
4. Ejecutar procesos no autorizados (sin 'process.execute') lanza PluginSandboxViolationError.
5. Acceder a red sin permiso (sin 'network') lanza PluginSandboxViolationError.
6. Exceder el tiempo límite (PLUGIN_SANDBOX_TIMEOUT) lanza PluginSandboxTimeoutError.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from core.autonomy_policy import TaskActionRisk
from core.plugin_loader import LoadedPlugin
from core.plugin_manifest import PluginManifest, PluginMetadata
from core.plugin_sandbox import (
    PluginExecutionSandbox,
    PluginSandboxTimeoutError,
    PluginSandboxViolationError,
)
from core.plugin_security import (
    PluginCapability,
    PluginDeclaredCapability,
    PluginRiskProfile,
)


def _create_test_plugin(
    plugin_dir: Path,
    plugin_id: str = "sandbox-test-plugin",
    capabilities: list[str] | None = None,
) -> LoadedPlugin:
    caps = capabilities if capabilities is not None else [PluginDeclaredCapability.FILESYSTEM_READ.value]
    metadata = PluginMetadata(
        plugin_id=plugin_id,
        name="Sandbox Test Plugin",
        version="1.0.0",
        description="Test",
        author="Tester",
        entrypoint="main.py",
    )
    manifest = PluginManifest(
        metadata=metadata,
        capabilities=tuple(caps),
        permissions=(),
        tools=(),
        is_approved=True,
    )
    plugin_capabilities = tuple(
        PluginCapability(name=c, max_allowed_risk=TaskActionRisk.MEDIUM_RISK) for c in caps
    )
    risk_profile = PluginRiskProfile(
        plugin_id=plugin_id,
        declared_capabilities=plugin_capabilities,
        assessed_risk_level=TaskActionRisk.MEDIUM_RISK,
    )
    return LoadedPlugin(
        manifest=manifest,
        plugin_dir=plugin_dir,
        risk_profile=risk_profile,
        module=None,
    )


def test_sandbox_read_outside_rejected() -> None:
    """Verifica que leer archivos fuera del directorio del sandbox sea rechazado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.read"])

        sandbox = PluginExecutionSandbox()

        def dummy_read(file_path: str) -> str:
            return "DATA"

        outside_file = "C:\\Windows\\System32\\drivers\\etc\\hosts" if Path("C:\\").exists() else "/etc/passwd"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=dummy_read,
                tool_name="file.read",
                operation="read",
                parameters={"path": outside_file},
            )

        assert "fuera del sandbox" in str(exc_info.value)


def test_sandbox_write_outside_rejected() -> None:
    """Verifica que escribir archivos fuera del directorio del sandbox sea rechazado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.write"])

        sandbox = PluginExecutionSandbox()

        def dummy_write(file_path: str) -> str:
            return "WRITTEN"

        outside_file = "C:\\Windows\\System32\\malware.dll" if Path("C:\\").exists() else "/tmp/malware.sh"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=dummy_write,
                tool_name="file.write",
                operation="write",
                parameters={"path": outside_file},
            )

        assert "fuera del sandbox" in str(exc_info.value)


def test_sandbox_undeclared_capability_rejected() -> None:
    """Verifica que intentar ejecutar acciones sin la capacidad declarada sea rechazado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        # Solo tiene filesystem.read
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.read"])

        sandbox = PluginExecutionSandbox()

        def dummy_clipboard() -> str:
            return "CLIPBOARD DATA"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=dummy_clipboard,
                tool_name="clipboard",
                operation="read",
            )

        assert "carece de la capacidad requerida" in str(exc_info.value)


def test_sandbox_unauthorized_process_execution_rejected() -> None:
    """Verifica que intentar ejecutar procesos sin la capacidad 'process.execute' sea rechazado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        # Sin capacidad process.execute
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.read"])

        sandbox = PluginExecutionSandbox()

        def dummy_cmd() -> str:
            return "CMD EXECUTED"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=dummy_cmd,
                tool_name="process",
                operation="execute",
            )

        assert "process.execute" in str(exc_info.value) or "carece" in str(exc_info.value)


def test_sandbox_unauthorized_network_access_rejected() -> None:
    """Verifica que acceder a red sin la capacidad 'network' sea rechazado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        # Sin capacidad network
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.read"])

        sandbox = PluginExecutionSandbox()

        def dummy_net() -> str:
            return "HTTP OK"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=dummy_net,
                tool_name="network",
                operation="connect",
            )

        assert "network" in str(exc_info.value) or "carece" in str(exc_info.value)


def test_sandbox_execution_timeout() -> None:
    """Verifica que si la ejecución del plugin supera timeout_seconds se lance PluginSandboxTimeoutError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "my_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        plugin = _create_test_plugin(p_dir, capabilities=["filesystem.read"])

        # Sandbox con timeout extremadamente corto (0.1 segundos)
        sandbox = PluginExecutionSandbox(timeout_seconds=0.1)

        def slow_action(**kwargs: str) -> str:
            time.sleep(0.5)
            return "DONE"


        with pytest.raises(PluginSandboxTimeoutError) as exc_info:
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=slow_action,
                tool_name="file.read",
                operation="read",
                parameters={"path": str(p_dir / "valid.txt")},
            )

        assert "SANDBOX TIMEOUT" in str(exc_info.value)
