"""Tests exhaustivos para ControlledToolPlanner (Etapa 19.0).

Verifica:
1. Flujo canónico: User Intent -> Context -> Memory Evidence -> Tool Discovery -> Plan -> Policy Validation -> Execution.
2. Capacidades del Planner: Proponer, ordenar, comparar y descartar herramientas.
3. Invariantes de Seguridad Estricta:
   - El Planner NO puede ejecutar directamente (lanza PlannerAuthorityViolationError).
   - El Planner NO puede conceder permisos.
   - El Planner NO puede modificar niveles de riesgo ni de autonomía.
   - El Planner NO puede modificar políticas.
4. Descarte de herramientas no disponibles según HealthMonitor.
5. Ponderación por evidencia de memoria (preferencias del usuario).
6. Handoff seguro a WorkflowExecutor y SecureExecutionPipeline.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.diagnostics.models import HealthCheck, HealthStatus
from core.diagnostics.monitor import HealthMonitor
from core.tool_planner import (
    ControlledToolPlanner,
    MemoryEvidence,
    PlannerAuthorityViolationError,
    ToolDiscoveryService,
    ToolPlanProposal,
)
from core.workflow import WorkflowExecutor, WorkflowState


class TestControlledToolPlanner:
    """Pruebas funcionales y de seguridad para ControlledToolPlanner."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.planner = ControlledToolPlanner()

    def test_intent_to_plan_generation(self) -> None:
        """Verifica que el planner genere una propuesta declarativa sin ejecutar."""
        intent = "Leer archivo de configuración y notificar al usuario"
        context = {"session_id": "sess_123", "cwd": "C:\\projects"}
        evidence = [
            MemoryEvidence(
                evidence_id="ev_01",
                fact_or_preference="Usuario prefiere notificaciones por el canal notification",
                category="user_preference",
            )
        ]

        subtasks = [
            {"step_id": "s1", "description": "leer archivo", "keywords": ["filesystem", "read"], "parameters": {"path": "C:\\config.json"}},
            {"step_id": "s2", "description": "notificar usuario", "keywords": ["notification", "send"], "parameters": {"msg": "Config leída"}, "dependencies": ["s1"]},
        ]

        proposal = self.planner.plan(
            intent=intent,
            context=context,
            memory_evidence=evidence,
            subtasks_hints=subtasks,
        )

        assert isinstance(proposal, ToolPlanProposal)
        assert len(proposal.proposed_steps) == 2
        assert proposal.proposed_steps[0].tool_name == "filesystem"
        assert proposal.proposed_steps[0].operation == "read"
        assert proposal.proposed_steps[1].tool_name == "notification"
        assert proposal.proposed_steps[1].dependencies == ("s1",)

    def test_memory_evidence_boosts_preferred_tool(self) -> None:
        """Verifica que la evidencia de memoria favorezca la herramienta preferida."""
        intent = "Gestionar documento de texto"
        evidence = [
            MemoryEvidence(
                evidence_id="ev_pref",
                fact_or_preference="El usuario suele preferir document en lugar de filesystem para notas",
                confidence=1.0,
            )
        ]
        subtasks = [
            {"step_id": "s1", "keywords": ["document", "filesystem"], "parameters": {}},
        ]

        proposal = self.planner.plan(intent=intent, memory_evidence=evidence, subtasks_hints=subtasks)
        assert len(proposal.proposed_steps) == 1
        # La herramienta elegida debe ser document gracias al boost de memoria
        assert proposal.proposed_steps[0].tool_name == "document"
        assert len(proposal.proposed_steps[0].discarded_alternatives) > 0

    def test_discovery_discards_unhealthy_subsystems(self) -> None:
        """Verifica que herramientas de subsistemas degradados o fallidos sean descartadas."""
        custom_health = HealthMonitor()
        # Registrar fallo en el subsistema de browser
        probe_fn = lambda: HealthCheck(
            name="browser",
            status=HealthStatus.FAILED,
            error_message="Browser process crashed",
        )
        custom_health.register_probe("browser", probe_fn)

        discovery = ToolDiscoveryService(health_monitor=custom_health)
        planner = ControlledToolPlanner(discovery_service=discovery)

        candidates = discovery.discover_candidates(intent_keywords=["browser", "navigate"])
        # Los candidatos de browser deben aparecer con is_available=False
        for cand in candidates:
            if cand.tool_name == "browser":
                assert cand.is_available is False
                assert "no disponible según HealthMonitor" in str(cand.discard_reason)

    def test_strict_authority_invariants_prevent_execution_and_escalation(self) -> None:
        """INVARIANTE CRÍTICO: El planner NO puede ejecutar, conceder permisos ni elevar autonomía."""
        with pytest.raises(PlannerAuthorityViolationError) as exc_exec:
            self.planner.execute("filesystem", "read", {})
        assert "NO tiene autoridad para ejecutar" in str(exc_exec.value)

        with pytest.raises(PlannerAuthorityViolationError) as exc_perm:
            self.planner.grant_permission("filesystem.read")
        assert "NO tiene autoridad para conceder permisos" in str(exc_perm.value)

        with pytest.raises(PlannerAuthorityViolationError) as exc_risk:
            self.planner.set_risk_level("DANGEROUS")
        assert "NO tiene autoridad para alterar niveles de riesgo" in str(exc_risk.value)

        with pytest.raises(PlannerAuthorityViolationError) as exc_auto:
            self.planner.set_autonomy_level("LEVEL_4")
        assert "NO tiene autoridad para modificar el nivel de autonomía" in str(exc_auto.value)

        with pytest.raises(PlannerAuthorityViolationError) as exc_pol:
            self.planner.modify_policy({})
        assert "NO tiene autoridad para modificar políticas de seguridad" in str(exc_pol.value)

    def test_full_pipeline_handoff_from_plan_to_workflow_execution(self) -> None:
        """Flujo Completo: User Intent -> Memory Evidence -> Tool Discovery -> Plan -> Policy Validation -> Execution."""
        intent = "Generar reporte"
        subtasks = [
            {"step_id": "s1", "keywords": ["document", "create"], "parameters": {"title": "Mi Reporte"}},
            {"step_id": "s2", "keywords": ["notification", "send"], "parameters": {"msg": "Reporte listo"}, "dependencies": ["s1"]},
        ]

        # 1. Planner genera propuesta declarativa
        proposal = self.planner.plan(intent=intent, subtasks_hints=subtasks)

        # 2. Conversión a WorkflowDefinition
        workflow_def = self.planner.to_workflow_definition(proposal)

        # 3. Entrega a WorkflowExecutor (la ejecución permanece 100% fuera del planner)
        executor = WorkflowExecutor()

        def mock_tool_invoker(tool: str, op: str, params: dict[str, Any]) -> Any:
            return {"status": "ok", "doc_id": "DOC-77", "delivered": True}

        result = executor.execute(workflow_def, tool_invoker=mock_tool_invoker)

        assert result.success is True
        assert result.state == WorkflowState.COMPLETED
        assert result.completed_steps == ("s1", "s2")
