"""Registro centralizado y thread-safe de Integration Adapters para JESSYCA 4.0.

Gestiona el catálogo de adaptadores registrados, mapeo de capacidades hacia adapters,
habilitación por configuración y consulta de estado.
"""

from __future__ import annotations

import threading
from typing import Any

from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationInfo,
    IntegrationStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.integration.registry")


class IntegrationRegistry:
    """Registro thread-safe de adapters y capacidades de integración."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, IntegrationAdapter] = {}
        self._enabled_map: dict[str, bool] = {}
        self._capability_to_adapters: dict[str, set[str]] = {}

    def register(self, adapter: IntegrationAdapter, enabled: bool = True) -> bool:
        """Registra un adapter en el sistema.

        Args:
            adapter: Instancia del IntegrationAdapter a registrar.
            enabled: Si la integración se encuentra habilitada inicialmente.

        Returns:
            True si se registró exitosamente; False si ya existía un adapter con ese nombre.
        """
        name = adapter.name.strip()
        with self._lock:
            if name in self._adapters:
                logger.warning(f"Intento de registrar adapter duplicado: '{name}'. Ignorando.")
                return False

            self._adapters[name] = adapter
            self._enabled_map[name] = enabled
            if not enabled:
                adapter.status = IntegrationStatus.DISABLED

            # Indexar capacidades declaradas
            for cap in adapter.capabilities:
                cap_name = cap.name.strip()
                if cap_name not in self._capability_to_adapters:
                    self._capability_to_adapters[cap_name] = set()
                self._capability_to_adapters[cap_name].add(name)

            logger.info(f"Adapter '{name}' v{adapter.version} registrado [enabled={enabled}].")
            return True

    def unregister(self, adapter_name: str) -> bool:
        """Desregistra un adapter del sistema.

        Args:
            adapter_name: Nombre canónico del adapter a remover.

        Returns:
            True si fue desregistrado; False si no existía.
        """
        name = adapter_name.strip()
        with self._lock:
            if name not in self._adapters:
                return False

            adapter = self._adapters.pop(name)
            self._enabled_map.pop(name, None)

            # Remover de indexación de capacidades
            for cap in adapter.capabilities:
                cap_name = cap.name.strip()
                if cap_name in self._capability_to_adapters:
                    self._capability_to_adapters[cap_name].discard(name)
                    if not self._capability_to_adapters[cap_name]:
                        del self._capability_to_adapters[cap_name]

            logger.info(f"Adapter '{name}' desregistrado.")
            return True

    def get(self, adapter_name: str) -> IntegrationAdapter | None:
        """Obtiene un adapter registrado por su nombre."""
        with self._lock:
            return self._adapters.get(adapter_name.strip())

    def get_for_capability(
        self,
        capability: str,
        only_ready: bool = True,
    ) -> list[IntegrationAdapter]:
        """Obtiene la lista de adapters que proveen una capacidad específica.

        Args:
            capability: Nombre de la capacidad buscada.
            only_ready: Si True, filtra únicamente adapters habilitados y en estado READY.

        Returns:
            Lista de IntegrationAdapter coincidentes.
        """
        cap = capability.strip()
        with self._lock:
            adapter_names = self._capability_to_adapters.get(cap, set())
            results: list[IntegrationAdapter] = []
            for name in adapter_names:
                adapter = self._adapters.get(name)
                if not adapter:
                    continue
                if not self._enabled_map.get(name, False):
                    continue
                if only_ready and adapter.status != IntegrationStatus.READY:
                    continue
                results.append(adapter)
            return results

    def list_integrations(self) -> list[IntegrationInfo]:
        """Devuelve un resumen de todos los adapters registrados."""
        with self._lock:
            infos: list[IntegrationInfo] = []
            for name, adapter in self._adapters.items():
                infos.append(
                    IntegrationInfo(
                        name=name,
                        version=adapter.version,
                        status=adapter.status,
                        capabilities=[c.name for c in adapter.capabilities],
                        dependencies=adapter.dependencies,
                        enabled=self._enabled_map.get(name, False),
                    )
                )
            return infos

    def list_capabilities(self) -> dict[str, list[str]]:
        """Devuelve un mapa de todas las capacidades registradas hacia los nombres de adapters que las ofrecen."""
        with self._lock:
            return {
                cap: list(names)
                for cap, names in self._capability_to_adapters.items()
            }

    def set_enabled(self, adapter_name: str, enabled: bool) -> bool:
        """Habilita o deshabilita un adapter registrado."""
        name = adapter_name.strip()
        with self._lock:
            if name not in self._adapters:
                return False
            self._enabled_map[name] = enabled
            if not enabled:
                self._adapters[name].status = IntegrationStatus.DISABLED
            elif self._adapters[name].status == IntegrationStatus.DISABLED:
                self._adapters[name].status = IntegrationStatus.AVAILABLE
            logger.info(f"Adapter '{name}' estado de habilitación modificado a: {enabled}.")
            return True

    def is_enabled(self, adapter_name: str) -> bool:
        """Verifica si un adapter está habilitado."""
        with self._lock:
            return self._enabled_map.get(adapter_name.strip(), False)

    def update_status(self, adapter_name: str, status: IntegrationStatus) -> None:
        """Actualiza el estado de un adapter."""
        name = adapter_name.strip()
        with self._lock:
            adapter = self._adapters.get(name)
            if adapter:
                adapter.status = status

    def reset(self) -> None:
        """Limpia todo el registro (útil para pruebas unitarias)."""
        with self._lock:
            self._adapters.clear(
)
            self._enabled_map.clear()
            self._capability_to_adapters.clear()


_global_registry = IntegrationRegistry()


def get_integration_registry() -> IntegrationRegistry:
    """Devuelve la instancia global del IntegrationRegistry."""
    return _global_registry
