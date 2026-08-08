"""Capability Manager para Jessyca Windows MCP.

Desacopla la ejecución de tareas de los nombres concretos de las herramientas,
permitiendo invocar herramientas por su capacidad declarada (ej. 'Filesystem', 'Network'),
acción (ej. 'copy', 'ping') y alias alternativos (ej. 'copiar_archivo').
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.contracts import ITool
from core.logger import get_logger

logger = get_logger("jessyca.capability")


@dataclass
class ToolCapabilitySpec:
    """Especificación declarativa de capacidad y acción para una herramienta MCP."""

    capability: str
    action: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    tool_name: str = ""

    def __post_init__(self) -> None:
        self.capability = self.capability.strip()
        self.action = self.action.strip()
        self.aliases = [alias.strip().lower() for alias in self.aliases if alias.strip()]


class CapabilityManager:
    """Gestor de capacidades desacoplado para la resolución de herramientas."""

    def __init__(self) -> None:
        # Mapa (capability.lower(), action.lower()) -> ITool
        self._capability_map: dict[tuple[str, str], ITool] = {}
        # Mapa alias.lower() -> (capability.lower(), action.lower())
        self._alias_map: dict[str, tuple[str, str]] = {}
        # Mapa tool_name -> ToolCapabilitySpec
        self._specs: dict[str, ToolCapabilitySpec] = {}

    def register_tool_capability(self, tool: ITool, spec: ToolCapabilitySpec) -> None:
        """Registra la capacidad, acción y alias de una herramienta concreta.

        Args:
            tool: Instancia de la herramienta MCP.
            spec: Especificación de la capacidad.
        """
        spec.tool_name = tool.name
        cap_key = (spec.capability.lower(), spec.action.lower())

        if cap_key in self._capability_map:
            prev_tool = self._capability_map[cap_key]
            logger.warning(
                f"Conflicto de Capacidad: ({spec.capability}.{spec.action}) asignada a '{tool.name}'. Sobrescribiendo previa '{prev_tool.name}'."
            )

        self._capability_map[cap_key] = tool
        self._specs[tool.name] = spec

        # Indexar alias
        for alias in spec.aliases:
            self._alias_map[alias] = cap_key

        # Indexar también el nombre de la herramienta como alias de respaldo
        self._alias_map[tool.name.lower()] = cap_key

        logger.info(
            f"Capacidad registrada: [{spec.capability} -> {spec.action}] asignada a '{tool.name}' (Alias: {spec.aliases})"
        )

    def discover_capabilities(self, registry: Any) -> int:
        """Descubre e indexa automáticamente las capacidades declaradas en todas las herramientas del ToolRegistry.

        Args:
            registry: Instancia de ToolRegistry.

        Returns:
            int: Cantidad total de capacidades registradas.
        """
        logger.info("Iniciando indexación de capacidades desde ToolRegistry...")
        registered_count = 0

        for tool in registry.list_tools():
            capability = getattr(tool, "capability", "General")
            action = getattr(tool, "action", "execute")
            aliases = getattr(tool, "aliases", [])
            description = getattr(tool, "description", "")

            spec = ToolCapabilitySpec(
                capability=capability,
                action=action,
                aliases=aliases,
                description=description,
            )
            self.register_tool_capability(tool, spec)
            registered_count += 1

        logger.info(f"Indexación de capacidades finalizada. Total capacidades: {registered_count}")
        return registered_count

    def resolve(self, capability: str, action: str) -> ITool | None:
        """Resuelve y devuelve una herramienta por su capacidad y acción.

        Args:
            capability: Nombre del dominio o capacidad (ej: 'Filesystem', 'Network').
            action: Nombre de la acción (ej: 'copy', 'ping').

        Returns:
            Instancia de ITool o None si no se encuentra.
        """
        cap_key = (capability.strip().lower(), action.strip().lower())
        tool = self._capability_map.get(cap_key)
        if tool is None:
            logger.warning(f"No se encontró herramienta para la Capacidad: ({capability}.{action})")
        return tool

    def resolve_by_alias(self, alias: str) -> ITool | None:
        """Resuelve una herramienta mediante un alias o palabra clave equivalente.

        Args:
            alias: Alias o nombre alternativo (ej: 'copiar_archivo', 'ping').

        Returns:
            Instancia de ITool o None si no existe coincidencia.
        """
        cleaned_alias = alias.strip().lower()
        cap_key = self._alias_map.get(cleaned_alias)
        if cap_key is None:
            logger.warning(f"No se encontró ninguna capacidad asociada al Alias: '{alias}'")
            return None
        return self._capability_map.get(cap_key)

    def get_available_capabilities(self) -> dict[str, list[str]]:
        """Obtiene un mapa de todas las capacidades registradas y sus acciones disponibles.

        Returns:
            dict[str, list[str]]: ej. {'Filesystem': ['copy', 'move'], 'Network': ['ping']}
        """
        result: dict[str, set[str]] = {}
        for cap, act in self._capability_map.keys():
            # Buscar el nombre original con mayúsculas
            orig_cap = cap.capitalize()
            for spec in self._specs.values():
                if spec.capability.lower() == cap:
                    orig_cap = spec.capability
                    break

            if orig_cap not in result:
                result[orig_cap] = set()

            result[orig_cap].add(act)

        return {k: sorted(v) for k, v in result.items()}

    def search_tools(self, query: str) -> list[ITool]:
        """Busca herramientas cuyos nombres, capacidades, acciones o alias contengan el término ingresado."""
        q = query.strip().lower()
        matched_tools: set[ITool] = set()

        for (cap, act), tool in self._capability_map.items():
            if q in cap or q in act or q in tool.name.lower():
                matched_tools.add(tool)

        for alias, cap_key in self._alias_map.items():
            if q in alias and cap_key in self._capability_map:
                matched_tools.add(self._capability_map[cap_key])

        return list(matched_tools)
