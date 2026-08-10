"""Pruebas unitarias e integradas del Pipeline Seguro de Ejecución de Plugins (Etapa 14.4).

REQUISITOS PROBADOS:
1. Plugin benigno de prueba: Se ejecuta correctamente cumpliendo la ruta obligatoria de 8 pasos.
2. Plugin deliberadamente malicioso 1 (Path Traversal): Rechazado en el pipeline.
3. Plugin deliberadamente malicioso 2 (Proceso no autorizado): Rechazado en el pipeline.
4. Plugin deliberadamente malicioso 3 (Red no autorizada): Rechazado en el pipeline.
5. Intento de Bypass Directo: Saltearse el pipeline lanza PluginExecutionPipelineBypassError.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.autonomy_policy import TaskActionRisk
from core.plugin_execution_pipeline import (
    PluginExecutionPipeline,
    PluginExecutionPipelineBypassError,
)
from core.plugin_loader import LoadedPlugin
from core.plugin_manifest import PluginManifest, PluginMetadata
from core.plugin_sandbox import PluginSandboxViolationError
from core.plugin_security import (
    PluginCapability,
    PluginRiskProfile,
)


def _create_mock_loaded_plugin(
    plugin_dir: Path,
    plugin_id: str,
    capabilities: list[str],
) -> LoadedPlugin:
    """Helper para crear una instancia cargada de plugin para pruebas."""
    metadata = PluginMetadata(
        plugin_id=plugin_id,
        name=f"Plugin {plugin_id}",
        version="1.0.0",
        description="Test plugin",
        author="Tester",
        entrypoint="main.py",
    )
    manifest = PluginManifest(
        metadata=metadata,
        capabilities=tuple(capabilities),
        permissions=(),
        tools=(),
        is_approved=True,
    )
    plugin_caps = tuple(
        PluginCapability(name=c, max_allowed_risk=TaskActionRisk.MEDIUM_RISK) for c in capabilities
    )
    risk_profile = PluginRiskProfile(
        plugin_id=plugin_id,
        declared_capabilities=plugin_caps,
        assessed_risk_level=TaskActionRisk.MEDIUM_RISK,
    )
    return LoadedPlugin(
        manifest=manifest,
        plugin_dir=plugin_dir,
        risk_profile=risk_profile,
        module=None,
    )


def test_benign_plugin_execution() -> None:
    """Verifica que un plugin benigno de prueba complete el pipeline exitosamente."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "benign_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        valid_file = p_dir / "sample.txt"
        with open(valid_file, "w", encoding="utf-8") as f:
            f.write("BENIGN DATA")

        plugin = _create_mock_loaded_plugin(p_dir, "benign-plugin", capabilities=["filesystem.read"])

        pipeline = PluginExecutionPipeline()

        def benign_action(path: str) -> str:
            with open(path, encoding="utf-8") as f:
                return f.read()

        result = pipeline.execute_plugin_tool_action(
            plugin=plugin,
            action_func=benign_action,
            tool_name="file.read",
            operation="read",
            parameters={"path": str(valid_file)},
        )

        assert result.success is True
        assert result.result == "BENIGN DATA"


def test_malicious_plugin_path_traversal_rejected() -> None:
    """Verifica el rechazo de un plugin malicioso que intenta Path Traversal fuera del sandbox."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "malicious_plugin_1"
        p_dir.mkdir(parents=True, exist_ok=True)

        plugin = _create_mock_loaded_plugin(p_dir, "malicious-plugin-1", capabilities=["filesystem.read"])

        pipeline = PluginExecutionPipeline()

        def malicious_traversal_action(path: str) -> str:
            return "LEAKED DATA"

        outside_target = "C:\\Windows\\System32\\config\\SAM" if Path("C:\\").exists() else "/etc/shadow"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            pipeline.execute_plugin_tool_action(
                plugin=plugin,
                action_func=malicious_traversal_action,
                tool_name="file.read",
                operation="read",
                parameters={"path": outside_target},
            )

        assert "fuera del sandbox" in str(exc_info.value)


def test_malicious_plugin_unauthorized_cmd_rejected() -> None:
    """Verifica el rechazo de un plugin malicioso que intenta ejecutar shell/procesos no autorizados."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "malicious_plugin_2"
        p_dir.mkdir(parents=True, exist_ok=True)

        # Carece de process.execute
        plugin = _create_mock_loaded_plugin(p_dir, "malicious-plugin-2", capabilities=["filesystem.read"])

        pipeline = PluginExecutionPipeline()

        def malicious_cmd_action() -> str:
            return "HACKED"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            pipeline.execute_plugin_tool_action(
                plugin=plugin,
                action_func=malicious_cmd_action,
                tool_name="powershell",
                operation="execute",
            )

        assert "carece" in str(exc_info.value) or "process.execute" in str(exc_info.value) or "denegada" in str(exc_info.value)


def test_malicious_plugin_unauthorized_network_rejected() -> None:
    """Verifica el rechazo de un plugin malicioso que intenta exfiltrar datos por red sin permiso."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "malicious_plugin_3"
        p_dir.mkdir(parents=True, exist_ok=True)

        # Carece de network
        plugin = _create_mock_loaded_plugin(p_dir, "malicious-plugin-3", capabilities=["filesystem.read"])

        pipeline = PluginExecutionPipeline()

        def malicious_net_action() -> str:
            return "EXFILTRATED"

        with pytest.raises(PluginSandboxViolationError) as exc_info:
            pipeline.execute_plugin_tool_action(
                plugin=plugin,
                action_func=malicious_net_action,
                tool_name="network",
                operation="http_post",
            )

        assert "network" in str(exc_info.value) or "carece" in str(exc_info.value) or "denegada" in str(exc_info.value)


def test_direct_bypass_rejected() -> None:
    """Verifica que saltearse el pipeline lanzará PluginExecutionPipelineBypassError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "bypass_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        plugin = _create_mock_loaded_plugin(p_dir, "bypass-plugin", capabilities=["filesystem.read"])

        pipeline = PluginExecutionPipeline()

        def bypass_action() -> str:
            return "BYPASS"

        with pytest.raises(PluginExecutionPipelineBypassError) as exc_info:
            pipeline.execute_plugin_tool_action(
                plugin=plugin,
                action_func=bypass_action,
                tool_name="file.read",
                operation="read",
                is_direct_call=True,  # Intento de bypass
            )

        assert "PIPELINE BYPASS DETECTED" in str(exc_info.value)
