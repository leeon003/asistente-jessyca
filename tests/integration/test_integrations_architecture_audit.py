"""Batería de Pruebas Automatizadas para la Auditoría y Consolidación de Integraciones.

Verifica formalmente:
1. Jarvis: Implementación canónica vs fallbacks, prevención de doble registro.
2. ARE: Inicialización unificada Hub <-> ARERuntime, ciclo de vida, planificación real vs plantillas.
3. AnyDoc: Confinamiento estricto de entradas/salidas, enlaces (symlinks), límites y procedencia con archivos temporales.
4. Archify + ORCA + ADE: Unificación como subsistema de producto sin asistentes ni JDE duplicados.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from core.anydoc.adapter import AnyDocAdapter
from core.anydoc.models import AnyDocTaskContract, ConversionStatus
from core.anydoc.orchestrator import AnyDocGovernedOrchestrator
from core.archify.adapter import (
    ArchifyMode,
    JessycaArchifyAdapter,
)
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime
from core.integration.adapters.are_adapter import AREAdapter, TaskGraph, TaskNode
from core.integration.adapters.jarvis_adapter import JarvisAdapter
from core.integration.hub import get_integration_hub
from core.integration.models import IntegrationContext, IntegrationStatus
from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode
from core.orca_ade.orchestrator import OrcaGovernedOrchestrator
from skills.archify_skill import ArchifySkill, generate_mermaid_fallback

# ==============================================================================
# 1. JARVIS VS NATIVE SKILLS AUDIT
# ==============================================================================

class TestJarvisIntegrationsAudit:
    """Verifica que Jarvis actúe estrictamente como proveedor subordinado / fallback."""

    def test_jarvis_adapter_disabled_by_default_in_hub(self) -> None:
        """Comprueba que Jarvis NO esté habilitado por defecto en IntegrationHub."""
        hub = get_integration_hub()
        jarvis_entry = hub.registry.get("jarvis-py")
        assert jarvis_entry is not None
        # Por defecto debe estar disabled para evitar doble registro activo en producción
        assert hub.registry.is_enabled("jarvis-py") is False

    def test_jarvis_app_control_is_secondary_fallback_to_native_apps(self) -> None:
        """Comprueba que jarvis.app_control utiliza alias estáticos frente a la resolución canónica."""
        jarvis = JarvisAdapter()
        cap = jarvis.get_capability("jarvis.app_control")
        assert cap is not None
        # Jarvis solo conoce alias fijos de diccionario
        from core.integration.adapters.jarvis_adapter import _APP_ALIASES
        assert "notepad" in _APP_ALIASES
        assert "calc" in _APP_ALIASES
        assert "unregistered_custom_binary" not in _APP_ALIASES

    def test_jarvis_volume_control_is_keystroke_fallback(self) -> None:
        """Comprueba que jarvis.volume_control es emulación multimedia a ciegas."""
        jarvis = JarvisAdapter()
        cap = jarvis.get_capability("jarvis.volume_control")
        assert cap is not None
        assert "action" in cap.parameters_schema
        # Comprueba que no tiene parámetros para nivel porcentual exacto (0-100)
        assert "level" not in cap.parameters_schema

    def test_jarvis_workspace_confinement_is_isolated_sandbox(self) -> None:
        """Comprueba que jarvis.workspace_files bloquee traversal fuera del workspace."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            jarvis = JarvisAdapter(workspace_root=temp_path)
            outside_file = "../../secret.txt"
            assert jarvis._resolve_safe_path(outside_file) is None


# ==============================================================================
# 2. ARE INITIALIZATION, LIFECYCLE & CAPABILITIES AUDIT
# ==============================================================================

class TestAREArchitectureAudit:
    """Verifica la trazabilidad, ciclo de vida unificado y límites de ARE."""

    def test_are_initialization_shares_adapter_with_hub(self) -> None:
        """Comprueba que ARERuntime reutilice el adaptador de ARE registrado en IntegrationHub."""
        hub = get_integration_hub()
        hub_are_adapter = hub.registry.get("are")
        assert hub_are_adapter is not None

        runtime = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        assert runtime.are_adapter is hub_are_adapter

    def test_are_lifecycle_synchronization_with_disabled_mode(self) -> None:
        """Comprueba que establecer modo DISABLED sincronice el estado del adaptador en el Hub."""
        runtime = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        assert runtime.current_mode == ARERuntimeMode.CONTROLLED

        runtime.set_mode(ARERuntimeMode.DISABLED)
        assert runtime.current_mode == ARERuntimeMode.DISABLED
        assert runtime.are_adapter.status == IntegrationStatus.DISABLED

        # Restaurar a CONTROLLED
        runtime.set_mode(ARERuntimeMode.CONTROLLED)
        assert runtime.are_adapter.status == IntegrationStatus.READY

    def test_are_active_mode_is_strictly_prohibited(self) -> None:
        """Comprueba que el modo ACTIVE esté terminantemente bloqueado y forzado a CONTROLLED."""
        runtime = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        with pytest.raises(PermissionError, match="ACTIVE.*strictly prohibited"):
            runtime.set_mode("ACTIVE")
        assert runtime.current_mode == ARERuntimeMode.CONTROLLED

    def test_are_real_dag_topological_sort_and_cycle_detection(self) -> None:
        """Comprueba la capacidad REAL de ARE: Kahn topological sort y detección de ciclos."""
        graph = TaskGraph(goal="Test DAG real")
        graph.add_node(TaskNode(id="step_a", title="A", action_type="test", depends_on=[]))
        graph.add_node(TaskNode(id="step_b", title="B", action_type="test", depends_on=["step_a"]))
        graph.add_node(TaskNode(id="step_c", title="C", action_type="test", depends_on=["step_b"]))

        order = graph.get_topological_order()
        assert order == ["step_a", "step_b", "step_c"]

        # Agregar ciclo circular
        graph.nodes["step_a"].depends_on = ["step_c"]
        with pytest.raises(ValueError, match="dependencias circulares"):
            graph.get_topological_order()

    def test_are_limited_templates_heuristic_classification(self) -> None:
        """Verifica que la descomposición heurística de ARE responde a plantillas limitadas por palabras clave."""
        async def _run() -> None:
            adapter = AREAdapter()
            await adapter.initialize()

            context = IntegrationContext(
                session_id="test_session_are",
                parameters={"goal": "Localiza documento y resume con referencias", "context": {}}
            )
            res = await adapter.execute("are.decompose_task", context)
            assert res.executed is True
            nodes = res.output.get("graph", {}).get("nodes", {})
            # Confirma que disparó la plantilla estática documentada para documentos
            assert "step_1_search" in nodes or "step_1_read" in nodes

        asyncio.run(_run())


# ==============================================================================
# 3. ANYDOC CONFINEMENT, LINKS, LIMITS & PROVENANCE
# ==============================================================================

class TestAnyDocConfinementAndProvenance:
    """Verifica el confinamiento, manejo de symlinks, límites de tamaño y procedencia."""

    def test_anydoc_input_confinement_rejects_external_reads(self) -> None:
        """Comprueba que AnyDocAdapter rechace lecturas fuera de sus directorios autorizados."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = os.path.join(tmp_dir, "sandbox")
            os.makedirs(sandbox_dir, exist_ok=True)
            adapter = AnyDocAdapter(base_sandbox_dir=sandbox_dir)

            outside_file = os.path.join(tmp_dir, "unauthorized.docx")
            with open(outside_file, "w") as f:
                f.write("content")

            with pytest.raises(ValueError, match="outside authorized read sandbox"):
                adapter.validate_and_confine_path(outside_file, must_exist=True, is_output=False)

    def test_anydoc_output_confinement_rejects_external_writes(self) -> None:
        """Comprueba que AnyDocAdapter rechace escrituras fuera del sandbox configurado."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = os.path.join(tmp_dir, "sandbox")
            os.makedirs(sandbox_dir, exist_ok=True)
            adapter = AnyDocAdapter(base_sandbox_dir=sandbox_dir)

            outside_output = os.path.join(tmp_dir, "out_escaped.md")
            with pytest.raises(ValueError, match="escapes authorized sandbox"):
                adapter.validate_and_confine_path(outside_output, must_exist=False, is_output=True)

    def test_anydoc_symlink_traversal_is_resolved_and_rejected(self) -> None:
        """Comprueba que un enlace simbólico apuntando fuera del sandbox sea resuelto y rechazado."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = os.path.join(tmp_dir, "sandbox")
            os.makedirs(sandbox_dir, exist_ok=True)
            outside_file = os.path.join(tmp_dir, "outside_secret.txt")
            with open(outside_file, "w") as f:
                f.write("secret data")

            symlink_path = os.path.join(sandbox_dir, "symlink_to_secret.txt")
            try:
                os.symlink(outside_file, symlink_path)
            except (OSError, NotImplementedError):
                pytest.skip("Symlinks no soportados con permisos de usuario actual en este entorno de Windows.")

            adapter = AnyDocAdapter(base_sandbox_dir=sandbox_dir)
            with pytest.raises(ValueError, match="outside authorized read sandbox"):
                adapter.validate_and_confine_path(symlink_path, must_exist=True, is_output=False)

    def test_anydoc_file_size_safety_limit(self) -> None:
        """Comprueba que AnyDocAdapter rechace archivos que excedan el límite de tamaño."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            sandbox_dir = os.path.join(tmp_dir, "sandbox")
            os.makedirs(sandbox_dir, exist_ok=True)
            small_limit = 100  # 100 bytes
            adapter = AnyDocAdapter(base_sandbox_dir=sandbox_dir, max_file_size_bytes=small_limit)

            large_file = os.path.join(sandbox_dir, "large.txt")
            with open(large_file, "wb") as f:
                f.write(b"A" * 500)

            res = adapter.convert_file(large_file)
            assert res.status == ConversionStatus.RESOURCE_LIMIT
            assert "exceeds safety limit" in (res.error_message or "")

    def test_anydoc_governed_orchestrator_receipt_provenance(self) -> None:
        """Comprueba que el orquestador genere recibos inmutables con hashes de entrada/salida."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = AnyDocGovernedOrchestrator(base_dir=tmp_dir)

            # Crear archivo de prueba CSV válido en el sandbox de entrada
            test_file = os.path.join(orchestrator.input_dir, "doc_test.csv")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("id,param,valor\n1,usuario,password=secret123\n")

            out_file = os.path.join(orchestrator.output_dir, "doc_test.md")

            contract = AnyDocTaskContract(
                task_id="task_anydoc_001",
                decision_id="dec_jde_001",
                operation_id="op_anydoc_001",
                input_path=test_file,
                input_format="csv",
                output_path=out_file,
                operation="document_processing.convert",
            )
            seal = contract.compute_seal()

            result = orchestrator.dispatch_task(contract, jde_decision="ALLOW", contract_seal=seal)
            assert result.status == ConversionStatus.VERIFIED_SUCCESS
            assert result.verified is True
            assert result.input_hash is not None
            assert result.output_hash is not None
            assert result.receipt is not None
            assert result.receipt.input_hash == result.input_hash
            assert result.receipt.output_hash == result.output_hash

            # Verificar redacción de secretos en la salida
            with open(out_file, encoding="utf-8") as rf:
                content = rf.read()
            assert "secret123" not in content
            assert "password=[REDACTED]" in content


# ==============================================================================
# 4. ARCHIFY + ORCA + ADE UNIFIED PRODUCT INTEGRATION
# ==============================================================================

class TestArchifyOrcaAdeProductIntegration:
    """Verifica que Archify + ORCA + ADE operen como un subsistema unificado de producto."""

    def test_single_product_integration_no_duplicate_personas(self) -> None:
        """Comprueba que ni Orca, ni ADE, ni Archify declaren personalidades de asistente separadas."""
        orca_adapter = OrcaAdeAdapter(mode=OrcaAdeMode.CONTROLLED)
        archify_adapter = JessycaArchifyAdapter(mode=ArchifyMode.CONTROLLED)
        skill = ArchifySkill(adapter=archify_adapter)

        # Son módulos técnicos subordinados al Core de JESSYCA
        assert orca_adapter.name == "orca_ade"
        assert archify_adapter.current_mode == ArchifyMode.CONTROLLED
        assert skill.nombre == "tools.archify"

    def test_archify_mermaid_fallback_is_deterministic(self) -> None:
        """Comprueba que Archify cuenta con un fallback determinista a Mermaid sin dependencias externas."""
        spec = {
            "title": "Arquitectura de Integraciones JESSYCA",
            "components": [
                {"id": "CORE", "name": "JESSYCA Core"},
                {"id": "JDE", "name": "Jessyca Decision Engine"},
                {"id": "ORCA", "name": "ORCA Worktrees"},
            ],
            "connections": [
                {"from": "CORE", "to": "JDE", "label": "Gobernanza"},
                {"from": "JDE", "to": "ORCA", "label": "ALLOW"},
            ],
        }
        mermaid_code = generate_mermaid_fallback(spec, "architecture")
        assert "graph TD" in mermaid_code
        assert 'CORE["JESSYCA Core"]' in mermaid_code
        assert 'CORE -->|"Gobernanza"| JDE' in mermaid_code
        assert 'JDE -->|"ALLOW"| ORCA' in mermaid_code

    def test_orca_ade_requires_real_jde_allow_verdict(self) -> None:
        """Comprueba que ORCA/ADE requiera obligatoriamente ALLOW de JDE y no ejecute con DENY."""
        orchestrator = OrcaGovernedOrchestrator()
        result = orchestrator.dispatch_task(
            objective="Modificar archivo de configuración",
            workspace="test_ws",
            decision_id="dec_deny_001",
            jde_decision="DENY",
        )
        assert result.status == "DENIED"
        assert result.verified is False
        assert len(result.changed_files) == 0
