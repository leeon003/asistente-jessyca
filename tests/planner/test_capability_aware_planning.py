"""Tests de Capability-Aware Planning para ControlledToolPlanner (Etapa 19.1).

Verifica:
1. Unavailable tool: Descarte de herramientas no disponibles por estado en HealthMonitor.
2. Unauthorized tool: Descarte de herramientas cuyo minimum_autonomy_level > current_level.
3. High risk tool: Identificación de herramientas de alto riesgo y requerimiento de confirmación.
4. Alternative tool: Propuesta automática de alternativa segura ante herramientas no autorizadas.
5. Plugin tool: Evaluación en contexto de plugin (is_plugin=True).
6. Scheduled task tool: Bloqueo de acciones peligrosas en contexto programado (is_scheduled=True).
"""

from __future__ import annotations

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.diagnostics.models import HealthCheck, HealthStatus
from core.diagnostics.monitor import HealthMonitor
from core.tool_planner import (
    ControlledToolPlanner,
    PlanningContext,
    ToolDiscoveryService,
)


class TestCapabilityAwarePlanning:
    """Pruebas de conocimiento de capacidades, riesgos, limitaciones y alternativas seguras."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.planner = ControlledToolPlanner()

    def test_unavailable_tool_is_discarded(self) -> None:
        """Verifica que una herramienta no disponible en HealthMonitor sea descartada."""
        custom_health = HealthMonitor()
        custom_health.register_probe(
            "ocr",
            lambda: HealthCheck(name="ocr", status=HealthStatus.FAILED, message="OCR engine missing"),
        )
        discovery = ToolDiscoveryService(health_monitor=custom_health)
        planner = ControlledToolPlanner(discovery_service=discovery)

        candidates = discovery.discover_candidates(intent_keywords=["ocr", "read"])
        ocr_cands = [c for c in candidates if c.operation == "ocr" or c.tool_name == "ocr" or "ocr" in c.capability]
        assert len(ocr_cands) > 0
        for cand in ocr_cands:
            assert cand.is_available is False
            assert "no disponible según HealthMonitor" in str(cand.discard_reason)

    def test_unauthorized_tool_under_low_autonomy_level(self) -> None:
        """Verifica que herramientas que requieren mayor nivel de autonomía no sean autorizadas."""
        # Nivel OBSERVE (LEVEL_0): Solo READ_ONLY permitido
        p_ctx = PlanningContext(
            user_intent="Escribir archivo en disco",
            current_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
        )

        subtasks = [
            {"step_id": "s1", "keywords": ["filesystem", "write"], "parameters": {"path": "C:\\out.txt"}},
        ]

        proposal = self.planner.plan(
            intent=p_ctx.user_intent,
            subtasks_hints=subtasks,
            planning_context=p_ctx,
        )

        # filesystem.write requiere LEVEL_3. En LEVEL_0, no debe seleccionarse como ejecutable directo
        # Si no hay alternativa de escritura, step debe descartar filesystem.write
        assert "s1:filesystem.write" in proposal.discarded_tools_summary
        assert "nivel de autonomía insuficiente" in proposal.discarded_tools_summary["s1:filesystem.write"].lower()

    def test_high_risk_tool_reflects_confirmation_and_limitations(self) -> None:
        """Verifica que herramientas DANGEROUS/CRITICAL reflejen riesgo y confirmación requerida."""
        p_ctx = PlanningContext(
            user_intent="Eliminar directorio de sistema",
            current_autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        )
        subtasks = [
            {"step_id": "s1", "keywords": ["filesystem", "delete"], "parameters": {"path": "C:\\temp"}},
        ]

        proposal = self.planner.plan(
            intent=p_ctx.user_intent,
            subtasks_hints=subtasks,
            planning_context=p_ctx,
        )

        assert len(proposal.proposed_steps) == 1
        step = proposal.proposed_steps[0]
        assert step.declared_risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)
        assert step.requires_confirmation is True
        assert "IRREVERSIBLE" in step.reversibility

    def test_safe_alternative_proposed_when_primary_is_unauthorized(self) -> None:
        """Verifica que el planner proponga una alternativa segura cuando la primaria no está autorizada."""
        # Nivel SUGGEST (LEVEL_1): No permite filesystem.write, pero permite filesystem.read
        p_ctx = PlanningContext(
            user_intent="Inspeccionar o preparar archivo",
            current_autonomy_level=AutonomyLevel.LEVEL_1_SUGGEST,
        )

        subtasks = [
            {"step_id": "s1", "keywords": ["filesystem", "read", "write"], "parameters": {}},
        ]

        proposal = self.planner.plan(
            intent=p_ctx.user_intent,
            subtasks_hints=subtasks,
            planning_context=p_ctx,
        )

        assert len(proposal.proposed_steps) == 1
        step = proposal.proposed_steps[0]
        # Debe haber elegido la alternativa de lectura autorizada (filesystem.read)
        assert step.tool_name == "filesystem"
        assert step.operation == "read"
        assert step.declared_risk == TaskActionRisk.READ_ONLY

    def test_plugin_tool_context_awareness(self) -> None:
        """Verifica la planificación en contexto de plugin (is_plugin=True)."""
        p_ctx = PlanningContext(
            user_intent="Ejecutar acción de plugin",
            is_plugin=True,
            plugin_id="plugin_analytics",
            current_autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        )

        subtasks = [
            {"step_id": "s1", "keywords": ["plugin", "execute"], "parameters": {"plugin_id": "plugin_analytics"}},
        ]

        proposal = self.planner.plan(
            intent=p_ctx.user_intent,
            subtasks_hints=subtasks,
            planning_context=p_ctx,
        )

        assert len(proposal.proposed_steps) == 1
        step = proposal.proposed_steps[0]
        assert step.tool_name == "plugin"
        assert step.operation == "execute"

    def test_scheduled_task_tool_blocks_dangerous_actions(self) -> None:
        """Verifica que tareas programadas bloqueen automáticamente operaciones de alto riesgo."""
        p_ctx = PlanningContext(
            user_intent="Eliminación programada en segundo plano",
            is_scheduled=True,
            current_autonomy_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
        )

        subtasks = [
            {"step_id": "s1", "keywords": ["filesystem", "delete"], "parameters": {"path": "C:\\cache"}},
        ]

        proposal = self.planner.plan(
            intent=p_ctx.user_intent,
            subtasks_hints=subtasks,
            planning_context=p_ctx,
        )

        # La herramienta peligrosa filesystem.delete debe ser descartada en contexto de scheduler
        assert "s1:filesystem.delete" in proposal.discarded_tools_summary
        assert "tarea programada" in proposal.discarded_tools_summary["s1:filesystem.delete"].lower()
