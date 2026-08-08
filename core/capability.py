"""Capability Manager para Jessyca Windows MCP.

Desacopla la ejecución de tareas de los nombres concretos de las herramientas,
permitiendo invocar herramientas por su capacidad declarada (ej. 'filesystem', 'network'),
acción (ej. 'read', 'ping'), categoría y alias alternativos (ej. 'leer_archivo').
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
    category: str = "general"
    tool_name: str = ""

    def __post_init__(self) -> None:
        self.capability = self.capability.strip()
        self.action = self.action.strip()
        self.category = self.category.strip()
        self.aliases = [alias.strip().lower() for alias in self.aliases if alias.strip()]


class CapabilityManager:
    """Gestor de capacidades desacoplado para el registro y resolución dinámica de herramientas."""

    def __init__(self) -> None:
        # Mapa (capability.lower(), action.lower()) -> ITool
        self._capability_map: dict[tuple[str, str], ITool] = {}
        # Mapa alias.lower() -> (capability.lower(), action.lower())
        self._alias_map: dict[str, tuple[str, str]] = {}
        # Mapa tool_name -> ToolCapabilitySpec
        self._specs: dict[str, ToolCapabilitySpec] = {}

    def register_capability(self, tool: ITool, spec: ToolCapabilitySpec | None = None) -> bool:
        """Registra la capacidad, acción, categoría y alias de una herramienta concreta.

        Args:
            tool: Instancia de la herramienta MCP.
            spec: Especificación opcional. Si es None, extrae la especificación de la herramienta.

        Returns:
            bool: True si el registro fue exitoso.
        """
        if spec is None:
            capability = getattr(tool, "capability", "general")
            action = getattr(tool, "action", "execute")
            aliases = getattr(tool, "aliases", [])
            category = getattr(tool, "category", "general")
            description = getattr(tool, "description", "")
            spec = ToolCapabilitySpec(
                capability=capability,
                action=action,
                aliases=aliases,
                category=category,
                description=description,
            )

        spec.tool_name = tool.name
        cap_key = (spec.capability.lower(), spec.action.lower())

        if cap_key in self._capability_map:
            prev_tool = self._capability_map[cap_key]
            if prev_tool.name != tool.name:
                logger.warning(
                    f"Conflicto de Capacidad: ({spec.capability}.{spec.action}) asignada a '{tool.name}'. Sobrescribiendo previa '{prev_tool.name}'."
                )

        self._capability_map[cap_key] = tool
        self._specs[tool.name] = spec

        # Indexar alias
        for alias in spec.aliases:
            if alias in self._alias_map and self._alias_map[alias] != cap_key:
                logger.warning(f"Alias duplicado '{alias}' detectado para ({spec.capability}.{spec.action}). Sobrescribiendo.")
            self._alias_map[alias] = cap_key

        # Indexar el nombre exacto de la herramienta como alias de respaldo
        self._alias_map[tool.name.lower()] = cap_key

        logger.info(
            f"Capacidad registrada: [{spec.capability} -> {spec.action}] asignada a '{tool.name}' (Categoría: {spec.category}, Alias: {spec.aliases})"
        )
        return True

    def register_tool_capability(self, tool: ITool, spec: ToolCapabilitySpec) -> None:
        """Método de retrocompatibilidad para registrar capacidades."""
        self.register_capability(tool, spec)

    def unregister_capability(self, capability: str, action: str) -> bool:
        """Cancela el registro de una capacidad y sus alias asociados.

        Args:
            capability: Dominio de capacidad.
            action: Acción concreta.

        Returns:
            bool: True si la capacidad fue encontrada y removida.
        """
        cap_key = (capability.strip().lower(), action.strip().lower())
        if cap_key in self._capability_map:
            tool = self._capability_map.pop(cap_key)
            self._specs.pop(tool.name, None)

            # Limpiar alias asociados a esta capacidad
            to_remove = [k for k, v in self._alias_map.items() if v == cap_key]
            for alias_key in to_remove:
                self._alias_map.pop(alias_key, None)

            logger.info(f"Capacidad ({capability}.{action}) removida exitosamente.")
            return True

        return False

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
            self.register_capability(tool)
            registered_count += 1

        logger.info(f"Indexación de capacidades finalizada. Total capacidades: {registered_count}")
        return registered_count

    def get_capability(self, capability: str, action: str) -> ITool | None:
        """Obtiene una herramienta por su capacidad y acción requeridas."""
        return self.resolve(capability, action)

    def resolve(self, capability: str, action: str) -> ITool | None:
        """Resuelve y devuelve una herramienta por su capacidad y acción.

        Args:
            capability: Nombre del dominio o capacidad (ej: 'filesystem', 'network').
            action: Nombre de la acción (ej: 'read', 'ping').

        Returns:
            Instancia de ITool o None si no se encuentra.
        """
        cap_key = (capability.strip().lower(), action.strip().lower())
        tool = self._capability_map.get(cap_key)
        if tool is None:
            logger.warning(f"No se encontró herramienta para la Capacidad: ({capability}.{action})")
        return tool

    def resolve_by_alias(self, alias: str) -> ITool | None:
        """Resuelve una herramienta mediante un alias o palabra clave equivalente."""
        return self.find_tools_by_alias(alias)

    def find_tools_by_alias(self, alias: str) -> ITool | None:
        """Busca una herramienta por su alias exacto."""
        cleaned_alias = alias.strip().lower()
        cap_key = self._alias_map.get(cleaned_alias)
        if cap_key is None:
            logger.warning(f"No se encontró ninguna capacidad asociada al Alias: '{alias}'")
            return None
        return self._capability_map.get(cap_key)

    def find_tools_by_capability(self, capability: str) -> list[ITool]:
        """Obtiene todas las herramientas asociadas a un dominio de capacidad específico."""
        cap_clean = capability.strip().lower()
        return [tool for (cap, _), tool in self._capability_map.items() if cap == cap_clean]

    def find_tools_by_action(self, action: str) -> list[ITool]:
        """Obtiene todas las herramientas asociadas a una acción específica."""
        act_clean = action.strip().lower()
        return [tool for (_, act), tool in self._capability_map.items() if act == act_clean]

    def find_tools_by_category(self, category: str) -> list[ITool]:
        """Obtiene todas las herramientas pertenecientes a una categoría temática."""
        cat_clean = category.strip().lower()
        return [
            tool for tool_name, spec in self._specs.items()
            if spec.category.lower() == cat_clean and (tool := self._capability_map.get((spec.capability.lower(), spec.action.lower())))
        ]

    def list_capabilities(self) -> dict[str, list[str]]:
        """Obtiene un mapa de todas las capacidades registradas y sus acciones disponibles."""
        return self.get_available_capabilities()

    def get_available_capabilities(self) -> dict[str, list[str]]:
        """Obtiene un mapa de todas las capacidades registradas y sus acciones disponibles.

        Returns:
            dict[str, list[str]]: ej. {'Filesystem': ['copy', 'move'], 'Network': ['ping']}
        """
        result: dict[str, set[str]] = {}
        for cap, act in self._capability_map.keys():
            display_cap = cap.capitalize()
            for spec in self._specs.values():
                if spec.capability.lower() == cap:
                    display_cap = spec.capability
                    break

            if display_cap not in result:
                result[display_cap] = set()

            result[display_cap].add(act)

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
