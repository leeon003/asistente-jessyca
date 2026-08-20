"""Registro desacoplado y seguro de Capabilities (CapabilityRegistry - Subetapa 06.1).

Almacena, valida y proporciona acceso thread-safe a las ToolCapabilities registradas.
Garantiza la inmutabilidad en tiempo de ejecución de las capacidades declaradas.
"""

from __future__ import annotations

import threading
from typing import Protocol

from core.capabilities import CapabilityOperation, ToolCapability
from core.capability_validator import check_and_assert_capability
from core.exceptions import SecurityValidationError
from core.logger import get_logger

logger = get_logger("jessyca.core.capability_registry")


class ICapabilityRegistry(Protocol):
    """Protocolo abstracto para el Registro de Capabilities de Jessyca."""

    def register(self, capability: ToolCapability) -> None:
        """Registra una nueva ToolCapability valida."""
        ...

    def unregister(self, capability_id: str) -> bool:
        """Elimina una capability si no es inmutable."""
        ...

    def get(self, capability_id: str) -> ToolCapability | None:
        """Obtiene una capability por su ID."""
        ...

    def get_tool(self, tool_name: str) -> ToolCapability | None:
        """Obtiene la capability asociada a una herramienta."""
        ...

    def get_operation(self, tool_name: str, operation_name: str) -> CapabilityOperation | None:
        """Obtiene una operación específica de una herramienta."""
        ...

    def list_tools(self) -> list[str]:
        """Lista los nombres de herramientas con capability registrada."""
        ...

    def list_capabilities(self) -> list[ToolCapability]:
        """Lista todas las capabilities registradas."""
        ...

    def has_tool(self, tool_name: str) -> bool:
        """Verifica si existe capability para la herramienta."""
        ...

    def has_operation(self, tool_name: str, operation_name: str) -> bool:
        """Verifica si existe una operación específica registrada."""
        ...

    def get_fingerprint(self, tool_name: str, operation_name: str) -> str | None:
        """Obtiene el fingerprint SHA-256 de una operación registrada."""
        ...


class CapabilityRegistry:
    """Implementación desacoplada y thread-safe del ICapabilityRegistry."""

    def __init__(self) -> None:
        self._capabilities_by_id: dict[str, ToolCapability] = {}
        self._capabilities_by_tool: dict[str, ToolCapability] = {}
        self._lock = threading.Lock()
        self._is_locked: bool = False

    def lock_registry(self) -> None:
        """Bloquea el registro impidiendo nuevas altas o bajas en runtime."""
        with self._lock:
            self._is_locked = True
            logger.info("CapabilityRegistry bloqueado para modificaciones en runtime.")

    @property
    def is_locked(self) -> bool:
        """Indica si el registro fue sellado contra modificaciones."""
        return self._is_locked

    def register(self, capability: ToolCapability) -> None:
        """Valida y registra una ToolCapability. Rechaza duplicados y fuentes no autorizadas."""
        with self._lock:
            if self._is_locked:
                raise SecurityValidationError("El CapabilityRegistry está sellado. No se pueden registrar nuevas capabilities.")

            # Validar explícitamente mediante CapabilityValidator
            check_and_assert_capability(capability)

            cap_id = capability.capability_id.strip()
            tool_name = capability.tool_name.strip().lower()

            if cap_id in self._capabilities_by_id or tool_name in self._capabilities_by_tool:
                raise SecurityValidationError(
                    f"Registro de Capability rechazado: Herramienta o Capability ID '{capability.tool_name}' ya registrada."
                )

            self._capabilities_by_id[cap_id] = capability
            self._capabilities_by_tool[tool_name] = capability

            logger.info(f"Capability registrada exitosamente: [{capability.capability_id}] '{capability.tool_name}' (Fuente: {capability.source.value})")

    def unregister(self, capability_id: str) -> bool:
        """Intenta desregistrar una capability. Impide eliminar capabilities inmutables."""
        with self._lock:
            if self._is_locked:
                raise SecurityValidationError("El CapabilityRegistry está sellado. No se pueden eliminar capabilities.")

            cap_id = capability_id.strip()
            capability = self._capabilities_by_id.get(cap_id)

            if not capability:
                return False

            if capability.is_immutable:
                raise SecurityValidationError(
                    f"Inviolabilidad de Capability: La capability '{capability.tool_name}' es inmutable y no puede ser eliminada."
                )

            tool_name = capability.tool_name.lower()
            del self._capabilities_by_id[cap_id]
            if tool_name in self._capabilities_by_tool:
                del self._capabilities_by_tool[tool_name]

            logger.info(f"Capability desregistrada: [{capability_id}] '{tool_name}'")
            return True

    def get(self, capability_id: str) -> ToolCapability | None:
        """Obtiene una capability por su ID o por su nombre de herramienta."""
        with self._lock:
            key = capability_id.strip()
            return self._capabilities_by_id.get(key) or self._capabilities_by_tool.get(key.lower())

    def get_tool(self, tool_name: str) -> ToolCapability | None:
        """Obtiene la capability de una herramienta."""
        with self._lock:
            return self._capabilities_by_tool.get(tool_name.strip().lower())

    def get_operation(self, tool_name: str, operation_name: str) -> CapabilityOperation | None:
        """Obtiene la especificación de una operación."""
        cap = self.get_tool(tool_name)
        if not cap:
            return None
        return cap.get_operation(operation_name)

    def list_tools(self) -> list[str]:
        """Lista los nombres de herramientas registradas."""
        with self._lock:
            return sorted(list(self._capabilities_by_tool.keys()))

    def list_capabilities(self) -> list[ToolCapability]:
        """Lista todas las capabilities activas."""
        with self._lock:
            return list(self._capabilities_by_id.values())

    def has_tool(self, tool_name: str) -> bool:
        """Verifica existencia de la herramienta."""
        with self._lock:
            return tool_name.strip().lower() in self._capabilities_by_tool

    def has_operation(self, tool_name: str, operation_name: str) -> bool:
        """Verifica existencia de la operación."""
        return self.get_operation(tool_name, operation_name) is not None

    def get_fingerprint(self, tool_name: str, operation_name: str) -> str | None:
        """Obtiene el fingerprint SHA-256 de una operación registrada."""
        cap = self.get_tool(tool_name)
        if not cap:
            return None
        return cap.get_operation_fingerprint(operation_name)


# Instancia Singleton Global del CapabilityRegistry
_global_capability_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    """Obtiene la instancia global del CapabilityRegistry."""
    global _global_capability_registry
    if _global_capability_registry is None:
        _global_capability_registry = CapabilityRegistry()
    return _global_capability_registry
