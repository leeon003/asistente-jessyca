"""Servicio de Descubrimiento de Herramientas (Tool Discovery - Etapas 19.0 y 19.1).

Garantiza:
1. Inspección completa y en tiempo de sólo lectura de CapabilityAutonomyRegistry (capacidades, riesgos, reversibilidad, confirmación, limitaciones).
2. Consulta de disponibilidad y salud en HealthMonitor (descarte de subsistemas degradados o fallidos).
3. Evaluación de autorización de acuerdo al PlanningContext (nivel de autonomía, scheduler, plugin).
"""

from __future__ import annotations

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.capability_autonomy_registry import (
    CapabilityAutonomyRegistry,
    get_capability_autonomy_registry,
)
from core.diagnostics.monitor import HealthMonitor, get_health_monitor
from core.logger import get_logger
from core.tool_planner.models import PlanningContext, ToolCandidate

logger = get_logger("jessyca.planner.discovery")


class ToolDiscoveryService:
    """Descubre y pre-filtra herramientas candidatas para un objetivo dado con conocimiento de capacidades."""

    def __init__(
        self,
        registry: CapabilityAutonomyRegistry | None = None,
        health_monitor: HealthMonitor | None = None,
    ) -> None:
        self.registry = registry or get_capability_autonomy_registry()
        self.health = health_monitor or get_health_monitor()

    def discover_candidates(
        self,
        intent_keywords: list[str],
        required_capability: str | None = None,
        planning_context: PlanningContext | None = None,
    ) -> list[ToolCandidate]:
        """Descubre herramientas registradas evaluando salud, permisos, limitaciones y autorización contextual."""
        candidates: list[ToolCandidate] = []
        all_profiles = self.registry.list_profiles()
        health_report = self.health.run_all_checks()

        current_level = planning_context.current_autonomy_level if planning_context else AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        is_scheduled = planning_context.is_scheduled if planning_context else False
        is_plugin = planning_context.is_plugin if planning_context else False

        logger.debug(f"[TOOL DISCOVERY] Buscando herramientas para capability='{required_capability}', level={current_level.label}")

        for profile in all_profiles:
            cap_key = profile.capability_key
            parts = cap_key.split(".", 1)
            tool_name = parts[0]
            operation = parts[1] if len(parts) > 1 else "execute"

            # 1. Comprobar salud del subsistema asociado
            is_available = True
            discard_reason: str | None = None

            subsystem_map = {
                "browser": "browser",
                "ocr": "ocr",
                "desktop.ocr": "ocr",
                "microphone": "microphone",
                "audio": "microphone",
                "ollama": "ollama",
                "llm": "ollama",
                "vectorstore": "vector_store",
                "memory": "vector_store",
                "scheduler": "scheduler",
                "plugin": "plugin",
            }
            probe_name = subsystem_map.get(cap_key.lower()) or subsystem_map.get(tool_name.lower()) or subsystem_map.get(operation.lower())
            if probe_name and not health_report.is_component_available(probe_name):
                is_available = False
                status_str = health_report.checks[probe_name].status.value if probe_name in health_report.checks else "UNAVAILABLE"
                discard_reason = f"Subsistema '{probe_name}' no disponible según HealthMonitor (Estado: {status_str})."

            # 2. Comprobar autorización contextual (Capability & Autonomy Aware)
            is_authorized = True
            if current_level < profile.minimum_autonomy_level:
                is_authorized = False
                discard_reason = (
                    f"No autorizada para el nivel de autonomía activo "
                    f"(nivel de autonomía insuficiente: {current_level.label} < requerido {profile.minimum_autonomy_level.label})."
                )
            elif is_scheduled and profile.risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
                is_authorized = False
                discard_reason = f"Operación de alto riesgo ({profile.risk_level.value}) bloqueada en contexto de tarea programada."
            elif is_plugin and profile.category != "plugin" and profile.risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
                is_authorized = False
                discard_reason = f"Operación de alto riesgo ({profile.risk_level.value}) bloqueada desde contexto de plugin."

            # 3. Calcular score de coincidencia
            score = 0.0
            match_reasons: list[str] = []

            if required_capability and required_capability.lower() in (tool_name.lower(), cap_key.lower()):
                score += 5.0
                match_reasons.append(f"Coincidencia exacta de capability '{required_capability}'")

            for kw in intent_keywords:
                kw_lower = kw.lower().strip()
                if not kw_lower:
                    continue
                if kw_lower in cap_key.lower():
                    score += 2.0
                    match_reasons.append(f"Palabra clave '{kw}' encontrada en '{cap_key}'")
                elif kw_lower in profile.description.lower():
                    score += 1.0
                    match_reasons.append(f"Palabra clave '{kw}' encontrada en descripción")

            if score > 0.0 or (required_capability and required_capability.lower() in cap_key.lower()):
                candidate = ToolCandidate(
                    tool_name=tool_name,
                    operation=operation,
                    capability=cap_key,
                    score=score,
                    match_reason="; ".join(match_reasons) if match_reasons else "Coincidencia de registro",
                    minimum_autonomy_level=profile.minimum_autonomy_level,
                    declared_risk=profile.risk_level,
                    reversibility=profile.reversibility.value,
                    requires_confirmation=(profile.requires_confirmation.value != "NEVER"),
                    audit_requirement=profile.audit_requirement.value,
                    limitations=profile.description,
                    is_available=is_available,
                    is_authorized=is_authorized,
                    is_safe_alternative=False,
                    discard_reason=discard_reason,
                )
                candidates.append(candidate)

        return candidates
