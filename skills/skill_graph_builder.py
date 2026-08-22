"""Builder declarativo y Fluent API para el Skill Graph (Fase 36).

Permite construir grafos estructurados conectando Skills, Tools, Agentes, Modelos,
Capacidades, Entradas, Salidas y Condiciones con relaciones fuertemente tipadas.

GARANTÍA DE SEGURIDAD:
- Inmutabilidad de construcciones intermedias.
- Conversión determinista desde SkillComposition y TaskGraph.
"""

from __future__ import annotations

from typing import Any

from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel
from skills.skill_composition_models import SkillComposition
from skills.skill_graph import SkillGraph
from skills.skill_graph_models import (
    SkillGraphEdge,
    SkillGraphEdgeType,
    SkillGraphNode,
    SkillGraphNodeType,
)


class SkillGraphBuilder:
    """Fluent Builder para construir instancias estructuradas de SkillGraph."""

    def __init__(
        self,
        graph_id: str,
        name: str = "",
        description: str = "",
        risk_ceiling: SecurityLevel | None = None,
    ) -> None:
        self.graph = SkillGraph(
            graph_id=graph_id,
            name=name,
            description=description,
            risk_ceiling=risk_ceiling,
        )

    def add_skill_node(
        self,
        node_id: str,
        skill_id: str,
        label: str = "",
        inputs: dict[str, Any] | None = None,
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        timeout_seconds: float = 60.0,
        condition: str | dict[str, Any] | None = None,
        requires_confirmation: bool = False,
        budget: AgentBudget | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo de ejecución de Skill."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.SKILL,
            ref_id=skill_id,
            label=label or skill_id,
            inputs=inputs or {},
            risk_level=risk_level,
            timeout_seconds=timeout_seconds,
            condition=condition,
            requires_confirmation=requires_confirmation,
            budget=budget,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_composition_node(
        self,
        node_id: str,
        composition_id: str,
        label: str = "",
        inputs: dict[str, Any] | None = None,
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        timeout_seconds: float = 120.0,
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo que invoca una SkillComposition completa."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.COMPOSITION,
            ref_id=composition_id,
            label=label or composition_id,
            inputs=inputs or {},
            risk_level=risk_level,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_tool_node(
        self,
        node_id: str,
        tool_name: str,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo representativo de una Tool subyacente."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.TOOL,
            ref_id=tool_name,
            label=label or tool_name,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_agent_node(
        self,
        node_id: str,
        agent_id: str,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo representativo de un Agente especializado."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.AGENT,
            ref_id=agent_id,
            label=label or agent_id,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_model_node(
        self,
        node_id: str,
        model_id: str,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo representativo de un Modelo LLM."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.MODEL,
            ref_id=model_id,
            label=label or model_id,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_capability_node(
        self,
        node_id: str,
        capability_name: str,
        label: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Agrega un nodo representativo de una Capacidad requerida."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.CAPABILITY,
            ref_id=capability_name,
            label=label or capability_name,
            metadata=metadata or {},
        )
        self.graph.add_node(node)
        return self

    def add_input_node(
        self,
        node_id: str,
        param_name: str,
        default_value: Any = None,
        label: str = "",
    ) -> SkillGraphBuilder:
        """Agrega un nodo de entrada de parámetros al grafo."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.INPUT,
            ref_id=param_name,
            label=label or param_name,
            result=default_value,
        )
        self.graph.add_node(node)
        return self

    def add_output_node(
        self,
        node_id: str,
        output_name: str,
        label: str = "",
    ) -> SkillGraphBuilder:
        """Agrega un nodo de salida o agregación final."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.OUTPUT,
            ref_id=output_name,
            label=label or output_name,
        )
        self.graph.add_node(node)
        return self

    def add_condition_node(
        self,
        node_id: str,
        condition_expr: str | dict[str, Any],
        label: str = "",
    ) -> SkillGraphBuilder:
        """Agrega un nodo de bifurcación condicional."""
        node = SkillGraphNode(
            node_id=node_id,
            node_type=SkillGraphNodeType.CONDITION,
            ref_id=node_id,
            label=label or "Condition",
            condition=condition_expr,
        )
        self.graph.add_node(node)
        return self

    def add_dependency(
        self,
        source_node_id: str,
        target_node_id: str,
        mapping_rules: dict[str, str] | None = None,
        condition: str | dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Establece que target_node_id depende de source_node_id (DEPENDS_ON)."""
        edge = SkillGraphEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_type=SkillGraphEdgeType.DEPENDS_ON,
            mapping_rules=mapping_rules or {},
            condition=condition,
        )
        self.graph.add_edge(edge)
        return self

    def add_produces(
        self,
        source_node_id: str,
        output_node_id: str,
        mapping_rules: dict[str, str] | None = None,
    ) -> SkillGraphBuilder:
        """Establece que source_node produce datos para output_node (PRODUCES)."""
        edge = SkillGraphEdge(
            source_node_id=source_node_id,
            target_node_id=output_node_id,
            edge_type=SkillGraphEdgeType.PRODUCES,
            mapping_rules=mapping_rules or {},
        )
        self.graph.add_edge(edge)
        return self

    def add_consumes(
        self,
        input_node_id: str,
        target_node_id: str,
        mapping_rules: dict[str, str] | None = None,
    ) -> SkillGraphBuilder:
        """Establece que target_node consume datos de input_node (CONSUMES)."""
        edge = SkillGraphEdge(
            source_node_id=input_node_id,
            target_node_id=target_node_id,
            edge_type=SkillGraphEdgeType.CONSUMES,
            mapping_rules=mapping_rules or {},
        )
        self.graph.add_edge(edge)
        return self

    def add_requires(
        self,
        skill_node_id: str,
        capability_node_id: str,
    ) -> SkillGraphBuilder:
        """Establece que skill_node requiere capability_node (REQUIRES)."""
        edge = SkillGraphEdge(
            source_node_id=capability_node_id,
            target_node_id=skill_node_id,
            edge_type=SkillGraphEdgeType.REQUIRES,
        )
        self.graph.add_edge(edge)
        return self

    def add_uses(
        self,
        skill_node_id: str,
        tool_node_id: str,
    ) -> SkillGraphBuilder:
        """Establece que skill_node utiliza tool_node (USES)."""
        edge = SkillGraphEdge(
            source_node_id=tool_node_id,
            target_node_id=skill_node_id,
            edge_type=SkillGraphEdgeType.USES,
        )
        self.graph.add_edge(edge)
        return self

    def add_delegates_to(
        self,
        agent_node_id: str,
        target_node_id: str,
    ) -> SkillGraphBuilder:
        """Establece delegación de agente a nodo (DELEGATES_TO)."""
        edge = SkillGraphEdge(
            source_node_id=agent_node_id,
            target_node_id=target_node_id,
            edge_type=SkillGraphEdgeType.DELEGATES_TO,
        )
        self.graph.add_edge(edge)
        return self

    def add_selects(
        self,
        source_node_id: str,
        model_node_id: str,
    ) -> SkillGraphBuilder:
        """Establece selección de modelo LLM por un nodo (SELECTS)."""
        edge = SkillGraphEdge(
            source_node_id=model_node_id,
            target_node_id=source_node_id,
            edge_type=SkillGraphEdgeType.SELECTS,
        )
        self.graph.add_edge(edge)
        return self

    def add_fallback(
        self,
        primary_node_id: str,
        fallback_node_id: str,
        condition: str | dict[str, Any] | None = None,
    ) -> SkillGraphBuilder:
        """Establece una ruta de respaldo (FALLBACK_TO) si primary_node falla."""
        edge = SkillGraphEdge(
            source_node_id=primary_node_id,
            target_node_id=fallback_node_id,
            edge_type=SkillGraphEdgeType.FALLBACK_TO,
            condition=condition,
        )
        self.graph.add_edge(edge)
        return self

    @classmethod
    def from_composition(cls, composition: SkillComposition) -> SkillGraph:
        """Construye un SkillGraph a partir de una SkillComposition existente."""
        builder = cls(
            graph_id=f"graph_{composition.id}",
            name=composition.name,
            description=composition.description,
            risk_ceiling=composition.risk_ceiling,
        )

        # Crear nodos para cada paso
        for step in composition.steps:
            step_label = getattr(step, "label", "") or step.step_id
            step_risk = getattr(step, "risk_level", SecurityLevel.SAFE) or SecurityLevel.SAFE
            builder.add_skill_node(
                node_id=step.step_id,
                skill_id=step.skill_id,
                label=step_label,
                inputs=step.input_mapping,
                risk_level=step_risk,
                timeout_seconds=step.timeout_seconds,
                condition=step.condition,
                requires_confirmation=step.requires_confirmation,
            )

        # Conectar dependencias declaradas
        for step in composition.steps:
            for dep_id in step.depends_on:
                if dep_id in builder.graph.nodes:
                    builder.add_dependency(dep_id, step.step_id)

        # Si el modo es secuencial y no había dependencias explícitas, encadenar
        if composition.execution_mode.value == "SEQUENTIAL" and len(composition.steps) > 1:
            for i in range(len(composition.steps) - 1):
                s1 = composition.steps[i].step_id
                s2 = composition.steps[i + 1].step_id
                # Agregar dependencia sólo si no existe ya
                if s1 not in builder.graph.get_dependencies(s2):
                    builder.add_dependency(s1, s2)

        return builder.build()

    def build(self) -> SkillGraph:
        """Finaliza y retorna la instancia construida de SkillGraph."""
        return self.graph
