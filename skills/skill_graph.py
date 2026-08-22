"""Estructura central del Skill Graph (Fase 36).

Representa el grafo dirigido estructurado de Skills, Compositions, Tools, Agents,
Models, Capabilities, Inputs, Outputs y Condiciones.

GARANTÍA DE ARQUITECTURA:
- Reutiliza principios topológicos de TaskGraph sin duplicidad de motores.
- Representación inmutable de aristas y nodos validados.
- Exportación estructurada para visualización y observabilidad.
"""

from __future__ import annotations

from typing import Any

from core.security_architecture import SecurityLevel
from skills.skill_graph_models import (
    SkillGraphEdge,
    SkillGraphEdgeType,
    SkillGraphNode,
    SkillGraphNodeType,
)


class SkillGraph:
    """Estructura de Grafo Dirigido Formal para orquestación y razonamiento de Skills."""

    def __init__(
        self,
        graph_id: str,
        name: str = "",
        description: str = "",
        risk_ceiling: SecurityLevel | None = None,
    ) -> None:
        self.graph_id = graph_id
        self.name = name or graph_id
        self.description = description
        self.risk_ceiling = risk_ceiling

        self._nodes: dict[str, SkillGraphNode] = {}
        self._edges: list[SkillGraphEdge] = []
        self._adj: dict[str, list[str]] = {}  # source -> list of targets
        self._rev_adj: dict[str, list[str]] = {}  # target -> list of sources
        self._node_type_index: dict[SkillGraphNodeType, list[str]] = {t: [] for t in SkillGraphNodeType}
        self.metadata: dict[str, Any] = {}

    def add_node(self, node: SkillGraphNode) -> None:
        """Agrega un nodo tipado al grafo."""
        if node.node_id in self._nodes:
            raise ValueError(f"Nodo con ID '{node.node_id}' ya existe en el grafo '{self.graph_id}'.")

        self._nodes[node.node_id] = node
        self._adj[node.node_id] = []
        self._rev_adj[node.node_id] = []
        self._node_type_index[node.node_type].append(node.node_id)

    def add_edge(self, edge: SkillGraphEdge) -> None:
        """Agrega una arista dirigida entre dos nodos del grafo."""
        if edge.source_node_id not in self._nodes:
            raise KeyError(f"Nodo origen '{edge.source_node_id}' no existe en el grafo.")
        if edge.target_node_id not in self._nodes:
            raise KeyError(f"Nodo destino '{edge.target_node_id}' no existe en el grafo.")

        self._edges.append(edge)
        if edge.target_node_id not in self._adj[edge.source_node_id]:
            self._adj[edge.source_node_id].append(edge.target_node_id)
        if edge.source_node_id not in self._rev_adj[edge.target_node_id]:
            self._rev_adj[edge.target_node_id].append(edge.source_node_id)

    def get_node(self, node_id: str) -> SkillGraphNode | None:
        """Obtiene un nodo por su identificador."""
        return self._nodes.get(node_id)

    def get_nodes_by_type(self, node_type: SkillGraphNodeType) -> list[SkillGraphNode]:
        """Obtiene todos los nodos de un tipo específico."""
        return [self._nodes[nid] for nid in self._node_type_index.get(node_type, [])]

    def get_outgoing_edges(self, source_node_id: str) -> list[SkillGraphEdge]:
        """Obtiene todas las aristas salientes de un nodo."""
        return [e for e in self._edges if e.source_node_id == source_node_id]

    def get_incoming_edges(self, target_node_id: str) -> list[SkillGraphEdge]:
        """Obtiene todas las aristas entrantes a un nodo."""
        return [e for e in self._edges if e.target_node_id == target_node_id]

    def get_dependencies(self, node_id: str) -> list[str]:
        """Obtiene los IDs de los nodos de los cuales depende node_id directamente."""
        deps: list[str] = []
        for edge in self.get_incoming_edges(node_id):
            if edge.edge_type in (
                SkillGraphEdgeType.DEPENDS_ON,
                SkillGraphEdgeType.CONSUMES,
                SkillGraphEdgeType.REQUIRES,
                SkillGraphEdgeType.USES,
                SkillGraphEdgeType.DELEGATES_TO,
            ):
                deps.append(edge.source_node_id)
        return deps

    def get_dependents(self, node_id: str) -> list[str]:
        """Obtiene los IDs de los nodos que dependen de node_id."""
        dependents: list[str] = []
        for edge in self.get_outgoing_edges(node_id):
            if edge.edge_type in (
                SkillGraphEdgeType.DEPENDS_ON,
                SkillGraphEdgeType.CONSUMES,
                SkillGraphEdgeType.REQUIRES,
                SkillGraphEdgeType.USES,
                SkillGraphEdgeType.DELEGATES_TO,
            ):
                dependents.append(edge.target_node_id)
        return dependents

    @property
    def nodes(self) -> dict[str, SkillGraphNode]:
        """Retorna el diccionario de nodos."""
        return self._nodes

    @property
    def edges(self) -> list[SkillGraphEdge]:
        """Retorna la lista de aristas."""
        return list(self._edges)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def to_dict(self) -> dict[str, Any]:
        """Exporta la definición completa del grafo a diccionario."""
        return {
            "graph_id": self.graph_id,
            "name": self.name,
            "description": self.description,
            "risk_ceiling": str(self.risk_ceiling) if self.risk_ceiling else None,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "edges": [e.to_dict() for e in self._edges],
            "metadata": dict(self.metadata),
        }

    def to_visualization_dict(self) -> dict[str, Any]:
        """Genera una representación estructurada para monitoreo y visualización del grafo.

        Esquema requerido:
        - NODE (ID, label, tipo, ref_id)
        - STATUS (PENDING, RUNNING, COMPLETED, FAILED, etc.)
        - DEPENDENCIES (listado de dependencias entrantes)
        - RESULT (resultado parcial o final)
        - ERROR (mensaje de error si aplica)
        - TIMING (duración en ms)
        - RISK (nivel de riesgo del nodo)
        """
        nodes_viz: list[dict[str, Any]] = []
        for node_id, node in self._nodes.items():
            incoming_deps = self.get_dependencies(node_id)
            nodes_viz.append({
                "NODE": {
                    "id": node.node_id,
                    "label": node.label or node.node_id,
                    "type": node.node_type.value,
                    "ref_id": node.ref_id,
                },
                "STATUS": node.status.value,
                "DEPENDENCIES": incoming_deps,
                "RESULT": node.result,
                "ERROR": node.error,
                "TIMING": {
                    "duration_ms": node.duration_ms,
                    "timeout_seconds": node.timeout_seconds,
                },
                "RISK": node.risk_level.value,
            })

        edges_viz: list[dict[str, Any]] = [
            {
                "source": e.source_node_id,
                "target": e.target_node_id,
                "type": e.edge_type.value,
                "condition": e.condition,
            }
            for e in self._edges
        ]

        return {
            "graph_id": self.graph_id,
            "name": self.name,
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "risk_ceiling": str(self.risk_ceiling) if self.risk_ceiling else None,
            "nodes": nodes_viz,
            "edges": edges_viz,
        }
