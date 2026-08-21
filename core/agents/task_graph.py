"""Grafo de tareas dirigidas acíclicas para colaboración multi-agente (task_graph.py - Fase 9).

Permite orquestar secuencias y paralelismos de tareas entre agentes especializados garantizando
la ausencia de ciclos (DAG) y el seguimiento riguroso de dependencias y presupuestos.

GARANTÍA DE SEGURIDAD:
- Detección determinista de ciclos antes de la ejecución.
- Cada nodo del grafo está acotado por un AgentBudget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.control_plane.models import AgentBudget


@dataclass
class TaskNode:
    """Nodo individual de tarea en el grafo de colaboración."""

    node_id: str
    agent_id: str
    intent: str
    scope: str = "default"
    dependencies: list[str] = field(default_factory=list)
    budget: AgentBudget | None = None
    status: str = "PENDING"
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "intent": self.intent,
            "scope": self.scope,
            "dependencies": list(self.dependencies),
            "status": self.status,
            "has_result": self.result is not None,
            "error": self.error,
        }


class TaskGraph:
    """Estructura de Grafo Dirigido Acíclico (DAG) para flujos de trabajo multi-agente."""

    def __init__(self) -> None:
        self._nodes: dict[str, TaskNode] = {}

    def add_node(self, node: TaskNode) -> None:
        """Agrega un nodo de tarea al grafo."""
        self._nodes[node.node_id] = node

    def add_dependency(self, child_node_id: str, parent_node_id: str) -> None:
        """Establece que child_node depende de la finalización de parent_node."""
        if child_node_id not in self._nodes:
            raise KeyError(f"Nodo hijo '{child_node_id}' no existe en el grafo.")
        if parent_node_id not in self._nodes:
            raise KeyError(f"Nodo padre '{parent_node_id}' no existe en el grafo.")

        if parent_node_id not in self._nodes[child_node_id].dependencies:
            self._nodes[child_node_id].dependencies.append(parent_node_id)

    def detect_cycles(self) -> bool:
        """Detecta si existen dependencias cíclicas en el grafo mediante algoritmo de Kahn / DFS."""
        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        adj_list: dict[str, list[str]] = {node_id: [] for node_id in self._nodes}

        for node_id, node in self._nodes.items():
            for dep in node.dependencies:
                if dep in adj_list:
                    adj_list[dep].append(node_id)
                    in_degree[node_id] += 1

        queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            current = queue.pop(0)
            visited_count += 1
            for neighbor in adj_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return visited_count != len(self._nodes)

    def get_topological_order(self) -> list[TaskNode]:
        """Retorna los nodos ordenados topológicamente según sus dependencias."""
        if self.detect_cycles():
            raise ValueError("El grafo de tareas contiene ciclos o dependencias recursivas.")

        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        adj_list: dict[str, list[str]] = {node_id: [] for node_id in self._nodes}

        for node_id, node in self._nodes.items():
            for dep in node.dependencies:
                if dep in adj_list:
                    adj_list[dep].append(node_id)
                    in_degree[node_id] += 1

        queue = [node_id for node_id, deg in in_degree.items() if deg == 0]
        order: list[TaskNode] = []

        while queue:
            current_id = queue.pop(0)
            order.append(self._nodes[current_id])
            for neighbor in adj_list[current_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def get_node(self, node_id: str) -> TaskNode | None:
        """Obtiene un nodo por su identificador."""
        return self._nodes.get(node_id)

    @property
    def node_count(self) -> int:
        return len(self._nodes)
