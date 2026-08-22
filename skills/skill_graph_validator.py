"""Validador formal de Skill Graphs (Fase 36).

Valida exhaustivamente:
- Integridad estructural y de tipado del grafo.
- Existencia y estado activo de Skills, Tools, Agentes y Modelos.
- Detección determinista de ciclos directos e indirectos (DFS 3 colores).
- Agregación monótona de niveles de riesgo y respeto al techo de riesgo (risk_ceiling).
- Ordenamiento topológico determinista de ejecución.

GARANTÍA DE SEGURIDAD:
- Invarianza de riesgo: el riesgo del grafo es el máximo estricto entre sus nodos.
- Todo grafo con ciclos o referencias rotas es rechazado previo a la ejecución.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_graph import SkillGraph
from skills.skill_graph_models import (
    SkillGraphEdgeType,
    SkillGraphNodeType,
)
from skills.skill_models import SkillStatus
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.graph.validator")

# Jerarquía formal de severidad de riesgo (de menor a mayor)
RISK_HIERARCHY: dict[str, int] = {
    "SAFE": 1,
    "LOW": 1,
    "WARNING": 2,
    "MEDIUM": 2,
    "DANGEROUS": 3,
    "HIGH": 3,
    "CRITICAL": 4,
}


class SkillGraphValidationResult(NamedTuple):
    """Resultado formal e inmutable de la validación de un SkillGraph.

    Hereda de NamedTuple para garantizar compatibilidad dual:
    - Desempaquetado de tupla: is_valid, errors, warnings, risk, order = res
    - Acceso a propiedades: res.is_valid, res.errors, res.warnings, etc.
    """

    is_valid: bool
    errors: list[str]
    warnings: list[str]
    aggregated_risk: SecurityLevel
    topological_order: list[str]


class SkillGraphValidator:
    """Validador estático y semántico de estructuras SkillGraph."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        tool_registry: Any = None,
        agent_coordinator: Any = None,
        model_router: Any = None,
    ) -> None:
        self.registry = registry or get_skill_registry()
        self.tool_registry = tool_registry
        self.agent_coordinator = agent_coordinator
        self.model_router = model_router

    def validate_graph(
        self,
        graph: SkillGraph,
    ) -> SkillGraphValidationResult:
        """Valida formalmente el SkillGraph.

        Returns:
            SkillGraphValidationResult(is_valid, errors, warnings, aggregated_risk, topological_order)
        """
        errors: list[str] = []
        warnings: list[str] = []
        highest_risk_score = 1

        # 1. Validación de nodos vacíos
        if graph.node_count == 0:
            errors.append(f"El SkillGraph '{graph.graph_id}' no contiene ningún nodo.")
            return SkillGraphValidationResult(False, errors, warnings, SecurityLevel.SAFE, [])

        # 2. Validación individual de nodos y entidades referenciadas
        for node_id, node in graph.nodes.items():
            # Extraer y acumular riesgo del nodo
            node_risk_val = str(getattr(node.risk_level, "value", node.risk_level)).upper()
            score = RISK_HIERARCHY.get(node_risk_val, 1)
            if score > highest_risk_score:
                highest_risk_score = score

            # Validación específica por tipo de nodo
            if node.node_type == SkillGraphNodeType.SKILL:
                skill_def = self.registry.get_definition(node.ref_id)
                skill_inst = self.registry.lookup(node.ref_id)

                if not skill_def and not skill_inst:
                    errors.append(
                        f"Skill requerida '{node.ref_id}' en nodo '{node_id}' no existe o no está registrada."
                    )
                    continue

                status = self.registry.get_status(node.ref_id)
                if status in (SkillStatus.DISABLED, SkillStatus.INVALID, SkillStatus.FAILED):
                    errors.append(
                        f"Skill '{node.ref_id}' en nodo '{node_id}' está en estado '{status}' (no ejecutable)."
                    )

                # Extraer riesgo intrínseco de la Skill si es mayor
                if skill_def and skill_def.risk_level:
                    sk_risk = str(getattr(skill_def.risk_level, "value", skill_def.risk_level)).upper()
                    sk_score = RISK_HIERARCHY.get(sk_risk, 1)
                    if sk_score > highest_risk_score:
                        highest_risk_score = sk_score
                elif skill_inst and hasattr(skill_inst, "nivel_riesgo"):
                    risk_num_map = {1: "SAFE", 2: "LOW", 3: "HIGH"}
                    sk_risk = risk_num_map.get(skill_inst.nivel_riesgo, "SAFE")
                    sk_score = RISK_HIERARCHY.get(sk_risk, 1)
                    if sk_score > highest_risk_score:
                        highest_risk_score = sk_score

            elif node.node_type == SkillGraphNodeType.TOOL:
                if self.tool_registry is not None:
                    has_tool = False
                    if hasattr(self.tool_registry, "has_tool"):
                        has_tool = self.tool_registry.has_tool(node.ref_id)
                    elif hasattr(self.tool_registry, "get_tool"):
                        has_tool = self.tool_registry.get_tool(node.ref_id) is not None
                    elif hasattr(self.tool_registry, "tools"):
                        has_tool = node.ref_id in self.tool_registry.tools

                    if not has_tool:
                        errors.append(f"Tool requerida '{node.ref_id}' en nodo '{node_id}' no está registrada.")

            elif node.node_type == SkillGraphNodeType.AGENT:
                if self.agent_coordinator is not None:
                    has_agent = False
                    if hasattr(self.agent_coordinator, "get_agent"):
                        has_agent = self.agent_coordinator.get_agent(node.ref_id) is not None
                    elif hasattr(self.agent_coordinator, "has_agent"):
                        has_agent = self.agent_coordinator.has_agent(node.ref_id)
                    elif hasattr(self.agent_coordinator, "agents"):
                        has_agent = node.ref_id in self.agent_coordinator.agents

                    if not has_agent:
                        errors.append(f"Agente requerido '{node.ref_id}' en nodo '{node_id}' no está disponible.")

            elif node.node_type == SkillGraphNodeType.MODEL:
                if self.model_router is not None:
                    has_model = False
                    if hasattr(self.model_router, "is_model_available"):
                        has_model = self.model_router.is_model_available(node.ref_id)
                    elif hasattr(self.model_router, "get_model"):
                        has_model = self.model_router.get_model(node.ref_id) is not None

                    if not has_model:
                        errors.append(f"Modelo requerido '{node.ref_id}' en nodo '{node_id}' no está disponible.")

        # 3. Validación de aristas y consistencia de relaciones
        for edge in graph.edges:
            if edge.source_node_id not in graph.nodes:
                errors.append(f"Arista referencia nodo origen inexistente '{edge.source_node_id}'.")
            if edge.target_node_id not in graph.nodes:
                errors.append(f"Arista referencia nodo destino inexistente '{edge.target_node_id}'.")

            # Validación de tipos de aristas semánticos
            src_node = graph.get_node(edge.source_node_id)
            tgt_node = graph.get_node(edge.target_node_id)
            if src_node and tgt_node:
                if edge.edge_type == SkillGraphEdgeType.REQUIRES and src_node.node_type != SkillGraphNodeType.CAPABILITY:
                    warnings.append(
                        f"Arista REQUIRES desde '{src_node.node_id}' ({src_node.node_type}) no es CAPABILITY."
                    )
                if edge.edge_type == SkillGraphEdgeType.USES and src_node.node_type != SkillGraphNodeType.TOOL:
                    warnings.append(
                        f"Arista USES desde '{src_node.node_id}' ({src_node.node_type}) no es TOOL."
                    )

        # 4. Calcular nivel de riesgo agregado
        score_to_risk: dict[int, SecurityLevel] = {
            1: SecurityLevel.SAFE,
            2: SecurityLevel.WARNING,
            3: SecurityLevel.HIGH,
            4: SecurityLevel.CRITICAL,
        }
        aggregated_risk = score_to_risk.get(highest_risk_score, SecurityLevel.SAFE)

        # Comprobar si supera el techo de riesgo declarado
        if graph.risk_ceiling:
            ceiling_val = str(getattr(graph.risk_ceiling, "value", graph.risk_ceiling)).upper()
            ceiling_score = RISK_HIERARCHY.get(ceiling_val, 1)
            if highest_risk_score > ceiling_score:
                errors.append(
                    f"El riesgo agregado del grafo ({aggregated_risk}) supera el techo permitido ({graph.risk_ceiling})."
                )

        # 5. Detección de Ciclos y Ordenamiento Topológico (Kahn / DFS 3-colores)
        cycle_errors, topological_order = self._detect_cycles_and_order(graph)
        errors.extend(cycle_errors)

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(
                f"[SKILL GRAPH VALID] '{graph.graph_id}' validado con riesgo '{aggregated_risk.value}', "
                f"{len(graph.nodes)} nodos, {len(graph.edges)} aristas."
            )
        else:
            logger.warning(
                f"[SKILL GRAPH INVALID] '{graph.graph_id}' contiene {len(errors)} errores de validación."
            )

        return SkillGraphValidationResult(is_valid, errors, warnings, aggregated_risk, topological_order)

    def _detect_cycles_and_order(self, graph: SkillGraph) -> tuple[list[str], list[str]]:
        """Detecta ciclos directos e indirectos y calcula el orden topológico de ejecución."""
        errors: list[str] = []
        order: list[str] = []

        # Construir lista de adyacencia de dependencias de ejecución
        # Solo consideramos aristas de dependencia y datos para el DAG de ejecución
        adj: dict[str, list[str]] = {nid: [] for nid in graph.nodes}
        in_degree: dict[str, int] = dict.fromkeys(graph.nodes, 0)

        for edge in graph.edges:
            # Si target depende de source, la arista de precedencia va de source -> target
            if edge.edge_type in (
                SkillGraphEdgeType.DEPENDS_ON,
                SkillGraphEdgeType.PRODUCES,
                SkillGraphEdgeType.CONSUMES,
                SkillGraphEdgeType.REQUIRES,
                SkillGraphEdgeType.USES,
                SkillGraphEdgeType.DELEGATES_TO,
            ):
                if edge.source_node_id in adj and edge.target_node_id in in_degree:
                    if edge.target_node_id not in adj[edge.source_node_id]:
                        adj[edge.source_node_id].append(edge.target_node_id)
                        in_degree[edge.target_node_id] += 1

        # Algoritmo DFS de 3 colores para detección precisa del camino del ciclo
        # 0 = UNVISITED (BLANCO), 1 = VISITING (GRIS), 2 = VISITED (NEGRO)
        state: dict[str, int] = dict.fromkeys(graph.nodes, 0)
        parent: dict[str, str | None] = dict.fromkeys(graph.nodes, None)
        cycle_detected = False

        def dfs(node: str, path: list[str]) -> bool:
            nonlocal cycle_detected
            state[node] = 1  # VISITING
            path.append(node)

            for neighbor in adj.get(node, []):
                if state[neighbor] == 1:  # Encontró un nodo en la pila de recursión (Ciclo)
                    cycle_start_idx = path.index(neighbor)
                    cycle_nodes = path[cycle_start_idx:] + [neighbor]
                    cycle_str = " -> ".join(cycle_nodes)
                    errors.append(f"Ciclo de dependencias detectado en el grafo (Ciclo detectado: {cycle_str})")
                    cycle_detected = True
                    return True
                elif state[neighbor] == 0:
                    parent[neighbor] = node
                    if dfs(neighbor, path):
                        return True

            path.pop()
            state[node] = 2  # VISITED
            return False

        for node_id in graph.nodes:
            if state[node_id] == 0:
                dfs(node_id, [])

        if cycle_detected:
            return errors, []

        # Algoritmo de Kahn para cálculo de orden topológico
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for neighbor in adj.get(curr, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != graph.node_count:
            errors.append("El grafo no pudo ser resuelto en un orden topológico acíclico válido.")
            return errors, []

        return errors, order
