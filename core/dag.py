"""Módulo de utilidades puras para Grafos Dirigidos Acíclicos (DAG) y Ordenamiento Topológico.

Proporciona un algoritmo de ordenamiento topológico determinista (Algoritmo de Kahn)
con soporte de desempate configurable, detección estricta de ciclos, autodependencias,
referencias inexistentes e identificadores de nodos duplicados.

Este módulo es 100% puro: no depende de adaptadores, ni de librerías externas,
ni genera ciclos de importación.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar("T")


class DAGError(ValueError):
    """Excepción base para todos los errores de estructura o validación en grafos DAG."""

    pass


class MissingDependencyError(DAGError):
    """Lanzada cuando un nodo referencia una dependencia inexistente en el grafo."""

    pass


class SelfDependencyError(DAGError):
    """Lanzada cuando un nodo depende directamente de sí mismo (autodependencia)."""

    pass


class CircularDependencyError(DAGError):
    """Lanzada cuando se detecta un ciclo de dependencias circulares."""

    pass


class DuplicateNodeError(DAGError):
    """Lanzada cuando existen identificadores de nodos o subtareas duplicados."""

    pass


class InvalidPlanError(DAGError):
    """Lanzada cuando un plan no es válido ni ejecutable por defectos estructurales."""

    pass


def topological_sort(
    items: Iterable[T],
    get_id: Callable[[T], str] = lambda x: getattr(x, "task_id", getattr(x, "id", str(x))),
    get_dependencies: Callable[[T], Iterable[str]] = lambda x: getattr(
        x, "dependencies", getattr(x, "depends_on", [])
    ),
    tie_breaker: Callable[[T], Any] | None = None,
) -> list[T]:
    """Calcula el orden topológico determinista de un conjunto de elementos usando el Algoritmo de Kahn.

    Garantías de ordenamiento y precedencia:
    1. Si la tarea B depende de la tarea A, A SIEMPRE precederá a B en el resultado final,
       independientemente de sus valores de prioridad o execution_order.
    2. tie_breaker y get_id se utilizan EXCLUSIVAMENTE para desempatar entre nodos que ya están
       listos para ejecutarse simultáneamente (in-degree == 0).
    3. Rechaza referencias inexistentes (MissingDependencyError), autodependencias (SelfDependencyError),
       identificadores duplicados (DuplicateNodeError) y ciclos circulares (CircularDependencyError).
    4. El orden es 100% determinista y estable ante llamadas repetidas.

    Args:
        items: Colección de elementos o nodos a ordenar.
        get_id: Función que extrae el identificador único de cada elemento.
        get_dependencies: Función que extrae la lista de IDs de dependencias requeridas.
        tie_breaker: Función opcional que devuelve una clave de ordenamiento (ej. execution_order)
                     para desempatar nodos con dependencias satisfechas.

    Returns:
        list[T]: Lista de elementos ordenada topológicamente.

    Raises:
        DuplicateNodeError: Si existen IDs duplicados.
        SelfDependencyError: Si algún nodo depende de sí mismo.
        MissingDependencyError: Si algún nodo depende de un ID inexistente.
        CircularDependencyError: Si se detecta un ciclo de dependencias.
    """
    item_list = list(items)
    if not item_list:
        return []

    # 1. Comprobación y mapeo de IDs únicos
    node_map: dict[str, T] = {}
    for item in item_list:
        raw_id = get_id(item)
        node_id = str(raw_id).strip() if raw_id is not None else ""
        if not node_id:
            raise DAGError("El identificador del nodo no puede ser nulo ni vacío.")
        if node_id in node_map:
            raise DuplicateNodeError(f"Se detectó un identificador de nodo duplicado: '{node_id}'.")
        node_map[node_id] = item

    # 2. Construcción de grados de entrada (in-degree) y grafo de adyacencia directa
    in_degree: dict[str, int] = dict.fromkeys(node_map, 0)
    adj_list: dict[str, list[str]] = {node_id: [] for node_id in node_map}

    for node_id, item in node_map.items():
        raw_deps = get_dependencies(item)
        deps = [str(d).strip() for d in (raw_deps or []) if d is not None]
        for dep in deps:
            if dep == node_id:
                raise SelfDependencyError(
                    f"El nodo '{node_id}' depende de sí mismo (autodependencia detectada)."
                )
            if dep not in node_map:
                raise MissingDependencyError(
                    f"El nodo '{node_id}' depende de '{dep}', la cual no existe en el grafo."
                )
            adj_list[dep].append(node_id)
            in_degree[node_id] += 1

    # 3. Cola de prioridad determinista (heapq) para desempatar nodos listos
    # Tupla en el heap: (sort_key, counter, item)
    # 'counter' garantiza desempate determinista sin comparar 'item' directamente.
    ready_heap: list[tuple[Any, int, T]] = []
    counter = 0

    def _make_sort_key(it: T, nid: str) -> Any:
        if tie_breaker is not None:
            tb = tie_breaker(it)
            return (tb, nid)
        return (0, nid)

    for node_id, item in node_map.items():
        if in_degree[node_id] == 0:
            sort_key = _make_sort_key(item, node_id)
            counter += 1
            heapq.heappush(ready_heap, (sort_key, counter, item))

    ordered: list[T] = []

    # 4. Proceso de Kahn
    while ready_heap:
        _, _, curr_item = heapq.heappop(ready_heap)
        ordered.append(curr_item)
        curr_id = str(get_id(curr_item)).strip()

        for neighbor_id in adj_list[curr_id]:
            in_degree[neighbor_id] -= 1
            if in_degree[neighbor_id] == 0:
                neighbor_item = node_map[neighbor_id]
                sort_key = _make_sort_key(neighbor_item, neighbor_id)
                counter += 1
                heapq.heappush(ready_heap, (sort_key, counter, neighbor_item))

    # 5. Validación de aciclicidad
    if len(ordered) != len(node_map):
        unresolved = sorted(nid for nid, deg in in_degree.items() if deg > 0)
        raise CircularDependencyError(
            f"El grafo de tareas contiene dependencias circulares (ciclo detectado). "
            f"Nodos no resueltos: {unresolved}"
        )

    return ordered
