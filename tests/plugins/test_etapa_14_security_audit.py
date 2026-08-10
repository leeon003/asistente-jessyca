"""Auditoría Adversarial Final para el Plugin Framework (Etapa 14).

DEMOSTRACIÓN FORMAL DE LAS 13 PRUEBAS ADVERSARIALES EXIGIDAS EN ETAPA 14:
1. forged manifest: Rechazo de manifiestos forjados o estructuralmente corruptos.
2. capability escalation: Rechazo de autoelevación de capacidades y falsificación de niveles de riesgo.
3. path traversal: Bloqueo absoluto de traversals (..) y rutas absolutas.
4. malicious metadata: Rechazo de metadatos o IDs con inyecciones de ruta o caracteres inválidos.
5. duplicate IDs: Prevención de carga de IDs de plugin duplicados en memoria.
6. invalid versions: Rechazo de versiones no conformes al estándar SemVer.
7. plugin loading before validation: Garantía de CERO importación de código si falla la validación del manifiesto.
8. unauthorized filesystem: Bloqueo de lecturas/escrituras en sistema de archivos fuera del sandbox.
9. unauthorized network: Bloqueo de peticiones a red sin la capacidad 'network'.
10. unauthorized process: Bloqueo de creación de procesos sin la capacidad 'process.execute'.
11. pipeline bypass: Bloqueo de intentos de invocación directa salteándose el PluginExecutionPipeline.
12. sandbox timeout: Cancelación de ejecuciones colgadas mediante PLUGIN_SANDBOX_TIMEOUT.
13. malicious plugin exception: Captura elegante de excepciones inesperadas producidas por el plugin sin degradar o congelar el núcleo.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

from core.autonomy_policy import TaskActionRisk
from core.plugin_execution_pipeline import (
    PluginExecutionPipeline,
    PluginExecutionPipelineBypassError,
)
from core.plugin_loader import (
    LoadedPlugin,
    PluginLoader,
    PluginLoaderSecurityError,
)
from core.plugin_manifest import (
    PluginManifest,
    PluginManifestValidator,
    PluginMetadata,
    PluginPathSecurityError,
    PluginValidationError,
    PluginVersionError,
)
from core.plugin_sandbox import (
    PluginExecutionSandbox,
    PluginSandboxTimeoutError,
    PluginSandboxViolationError,
)
from core.plugin_security import (
    PluginCapability,
    PluginCapabilityViolationError,
    PluginDeclaredCapability,
    PluginPrivilegeElevationError,
    PluginRiskProfile,
)


def test_audit_1_forged_manifest() -> None:
    """1. forged manifest: Rechazo de manifiestos forjados o estructuralmente corruptos."""
    validator = PluginManifestValidator()

    forged_dict = {
        "id": "forged-plugin-id",
        "name": "Forged Plugin",
        # Falta version, entrypoint y capabilities obligatorias
    }

    with pytest.raises(PluginValidationError) as exc_info:
        validator.validate_manifest_dict(forged_dict)

    assert "carece del campo obligatorio" in str(exc_info.value)


def test_audit_2_capability_escalation() -> None:
    """2. capability escalation: Rechazo de autoelevación de riesgo y capacidades no autorizadas."""
    validator = PluginManifestValidator()

    # Intento de inventar capacidad
    dict_invented = {
        "id": "escalation-plugin-1",
        "name": "Escalation Plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "Tester",
        "entrypoint": "main.py",
        "capabilities": ["system.godmode"],
    }
    with pytest.raises(PluginCapabilityViolationError):
        validator.validate_manifest_dict(dict_invented)

    # Intento de autoelevar privilegios declarando powershell como READ_ONLY
    dict_risk = {
        "id": "escalation-plugin-2",
        "name": "Escalation Plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "Tester",
        "entrypoint": "main.py",
        "capabilities": ["process.execute"],
        "tools": [{"name": "powershell.execute", "operation": "run", "claimed_risk": "READ_ONLY"}],
    }
    with pytest.raises(PluginPrivilegeElevationError):
        validator.validate_manifest_dict(dict_risk)


def test_audit_3_path_traversal() -> None:
    """3. path traversal: Bloqueo absoluto de traversals (..) y rutas absolutas."""
    validator = PluginManifestValidator()

    traversal_paths = ["../outside.py", "/etc/passwd", "C:\\Windows\\System32\\cmd.exe"]

    for bad_path in traversal_paths:
        manifest_data = {
            "id": "traversal-plugin",
            "name": "Traversal Plugin",
            "version": "1.0.0",
            "description": "Test",
            "author": "Tester",
            "entrypoint": bad_path,
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginPathSecurityError):
            validator.validate_manifest_dict(manifest_data)


def test_audit_4_malicious_metadata() -> None:
    """4. malicious metadata: Rechazo de metadatos o IDs con inyección o formato inválido."""
    validator = PluginManifestValidator()

    malicious_ids = ["../../evil_plugin", "plugin with space", "BAD!ID"]

    for bad_id in malicious_ids:
        manifest_data = {
            "id": bad_id,
            "name": "Malicious Metadata",
            "version": "1.0.0",
            "description": "Test",
            "author": "Tester",
            "entrypoint": "main.py",
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginValidationError):
            validator.validate_manifest_dict(manifest_data)


def test_audit_5_duplicate_ids() -> None:
    """5. duplicate IDs: Prevención de carga de dos plugins con el mismo ID en memoria."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)

        p_dir = plugins_dir / "dup-plugin-id"
        p_dir.mkdir(parents=True, exist_ok=True)
        manifest_dict = {
            "id": "dup-plugin-id",
            "name": "Dup Plugin",
            "version": "1.0.0",
            "description": "Test",
            "author": "Tester",
            "entrypoint": "main.py",
            "capabilities": ["filesystem.read"],
        }
        with open(p_dir / "plugin.json", "w", encoding="utf-8") as f:
            json.dump(manifest_dict, f)
        with open(p_dir / "main.py", "w", encoding="utf-8") as f:
            f.write("def run(): pass\n")

        # Cargar primera vez
        loader.load_plugin(p_dir)

        # Cargar segunda vez (Duplicado)
        with pytest.raises(PluginLoaderSecurityError) as exc_info:
            loader.load_plugin(p_dir)

        assert "ya se encuentra cargado en memoria" in str(exc_info.value)


def test_audit_6_invalid_versions() -> None:
    """6. invalid versions: Rechazo de cadenas de versión que no cumplen SemVer."""
    validator = PluginManifestValidator()

    invalid_versions = ["v1.0", "beta-1", "1.0", "xyz"]

    for bad_ver in invalid_versions:
        manifest_data = {
            "id": "valid-id",
            "name": "Test Plugin",
            "version": bad_ver,
            "description": "Test",
            "author": "Tester",
            "entrypoint": "main.py",
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginVersionError):
            validator.validate_manifest_dict(manifest_data)


def test_audit_7_plugin_loading_before_validation() -> None:
    """7. plugin loading before validation: CERO importación de código si el manifiesto falla."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)

        p_dir = plugins_dir / "corrupted-manifest-plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        # plugin.json corrupto
        with open(p_dir / "plugin.json", "w", encoding="utf-8") as f:
            f.write("{ CORRUPTED JSON ...")

        # main.py que si se importa imprime o altera algo
        with open(p_dir / "main.py", "w", encoding="utf-8") as f:
            f.write("raise RuntimeError('CÓDIGO EJECUTADO ANTES DE TIEMPO!')\n")

        with pytest.raises(PluginValidationError):
            loader.load_plugin(p_dir)

        # Verificar que el módulo NUNCA fue importado en sys.modules
        assert "jessyca_plugins.corrupted_manifest_plugin" not in sys.modules


def test_audit_8_unauthorized_filesystem() -> None:
    """8. unauthorized filesystem: Rechazo de accesos a archivos fuera del sandbox o sin capacidad."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "fs_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        metadata = PluginMetadata(
            plugin_id="fs-plugin",
            name="FS Plugin",
            version="1.0.0",
            description="Test",
            author="Tester",
            entrypoint="main.py",
        )
        manifest = PluginManifest(
            metadata=metadata,
            capabilities=(PluginDeclaredCapability.FILESYSTEM_READ.value,),
            permissions=(),
            tools=(),
            is_approved=True,
        )
        plugin_cap = PluginCapability(
            name=PluginDeclaredCapability.FILESYSTEM_READ.value,
            max_allowed_risk=TaskActionRisk.MEDIUM_RISK,
        )
        risk_profile = PluginRiskProfile(
            plugin_id="fs-plugin",
            declared_capabilities=(plugin_cap,),
            assessed_risk_level=TaskActionRisk.MEDIUM_RISK,
        )
        plugin = LoadedPlugin(manifest=manifest, plugin_dir=p_dir, risk_profile=risk_profile)

        sandbox = PluginExecutionSandbox()

        def try_read(path: str) -> str:
            return "DATA"

        outside = "C:\\Windows\\System32\\drivers\\etc\\hosts" if Path("C:\\").exists() else "/etc/passwd"

        with pytest.raises(PluginSandboxViolationError):
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=try_read,
                tool_name="file.read",
                operation="read",
                parameters={"path": outside},
            )


def test_audit_9_unauthorized_network() -> None:
    """9. unauthorized network: Bloqueo de peticiones de red sin poseer la capacidad 'network'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "net_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        metadata = PluginMetadata("net-plugin", "Net", "1.0.0", "Test", "Tester", "main.py")
        manifest = PluginManifest(metadata, (PluginDeclaredCapability.FILESYSTEM_READ.value,), (), (), is_approved=True)
        risk_profile = PluginRiskProfile("net-plugin", (), TaskActionRisk.READ_ONLY)
        plugin = LoadedPlugin(manifest, p_dir, risk_profile)

        sandbox = PluginExecutionSandbox()

        def try_net() -> str:
            return "EXFIL"

        with pytest.raises(PluginSandboxViolationError):
            sandbox.execute_plugin_action(plugin, try_net, "network", "connect")


def test_audit_10_unauthorized_process() -> None:
    """10. unauthorized process: Bloqueo de creación de procesos sin la capacidad 'process.execute'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "proc_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        metadata = PluginMetadata("proc-plugin", "Proc", "1.0.0", "Test", "Tester", "main.py")
        manifest = PluginManifest(metadata, (PluginDeclaredCapability.FILESYSTEM_READ.value,), (), (), is_approved=True)
        risk_profile = PluginRiskProfile("proc-plugin", (), TaskActionRisk.READ_ONLY)
        plugin = LoadedPlugin(manifest, p_dir, risk_profile)

        sandbox = PluginExecutionSandbox()

        def try_proc() -> str:
            return "CMD"

        with pytest.raises(PluginSandboxViolationError):
            sandbox.execute_plugin_action(plugin, try_proc, "powershell", "execute")


def test_audit_11_pipeline_bypass() -> None:
    """11. pipeline bypass: Bloqueo de intentos de invocación directa salteándose el pipeline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "bypass_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)

        metadata = PluginMetadata("bypass-plugin", "Bypass", "1.0.0", "Test", "Tester", "main.py")
        manifest = PluginManifest(metadata, (PluginDeclaredCapability.FILESYSTEM_READ.value,), (), (), is_approved=True)
        risk_profile = PluginRiskProfile("bypass-plugin", (), TaskActionRisk.READ_ONLY)
        plugin = LoadedPlugin(manifest, p_dir, risk_profile)

        pipeline = PluginExecutionPipeline()

        def bypass_func() -> str:
            return "DIRECT"

        with pytest.raises(PluginExecutionPipelineBypassError):
            pipeline.execute_plugin_tool_action(
                plugin=plugin,
                action_func=bypass_func,
                tool_name="file.read",
                operation="read",
                is_direct_call=True,
            )


def test_audit_12_sandbox_timeout() -> None:
    """12. sandbox timeout: Cancelación de ejecuciones infinitas/colgadas mediante PLUGIN_SANDBOX_TIMEOUT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "timeout_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        valid_file = p_dir / "test.txt"
        with open(valid_file, "w", encoding="utf-8") as f:
            f.write("OK")

        metadata = PluginMetadata("timeout-plugin", "Timeout", "1.0.0", "Test", "Tester", "main.py")
        manifest = PluginManifest(metadata, (PluginDeclaredCapability.FILESYSTEM_READ.value,), (), (), is_approved=True)
        cap = PluginCapability(PluginDeclaredCapability.FILESYSTEM_READ.value, max_allowed_risk=TaskActionRisk.MEDIUM_RISK)
        risk_profile = PluginRiskProfile("timeout-plugin", (cap,), TaskActionRisk.MEDIUM_RISK)
        plugin = LoadedPlugin(manifest, p_dir, risk_profile)

        sandbox = PluginExecutionSandbox(timeout_seconds=0.1)

        def hang_func(**kwargs: str) -> str:
            time.sleep(0.5)
            return "HUNG"

        with pytest.raises(PluginSandboxTimeoutError):
            sandbox.execute_plugin_action(
                plugin=plugin,
                action_func=hang_func,
                tool_name="file.read",
                operation="read",
                parameters={"path": str(valid_file)},
            )


def test_audit_13_malicious_plugin_exception() -> None:
    """13. malicious plugin exception: Captura limpia de excepciones producidas por el plugin sin romper el sistema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = Path(tmpdir) / "exception_plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        valid_file = p_dir / "test.txt"
        with open(valid_file, "w", encoding="utf-8") as f:
            f.write("OK")

        metadata = PluginMetadata("exception-plugin", "Exception", "1.0.0", "Test", "Tester", "main.py")
        manifest = PluginManifest(metadata, (PluginDeclaredCapability.FILESYSTEM_READ.value,), (), (), is_approved=True)
        cap = PluginCapability(PluginDeclaredCapability.FILESYSTEM_READ.value, max_allowed_risk=TaskActionRisk.MEDIUM_RISK)
        risk_profile = PluginRiskProfile("exception-plugin", (cap,), TaskActionRisk.MEDIUM_RISK)
        plugin = LoadedPlugin(manifest, p_dir, risk_profile)

        pipeline = PluginExecutionPipeline()

        def crashing_func(path: str) -> str:
            raise ZeroDivisionError("CÓDIGO DE PLUGIN FALLÓ DELIBERADAMENTE")

        res = pipeline.execute_plugin_tool_action(
            plugin=plugin,
            action_func=crashing_func,
            tool_name="file.read",
            operation="read",
            parameters={"path": str(valid_file)},
        )

        # Retorna resultado con success=False sin propagar crash fatal
        assert res.success is False
        assert "FALLÓ DELIBERADAMENTE" in res.error_message

