"""Contrato base abstracto para Adapters de Integración de JESSYCA 4.0.

Define la interfaz común que deben implementar todos los adaptadores hacia tecnologías
externas (Jarvis-py, ARE, Windows computer-use, LLM Router, etc.), garantizando aislamiento
estricto de dependencias, ciclo de vida asíncrono y reporte de salud.
"""

from __future__ import annotations

import abc
import importlib.util
from typing import Any

from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger

logger = get_logger("jessyca.integration.adapter")


class IntegrationAdapter(abc.ABC):
    """Clase base abstracta para todos los adapters de tecnologías externas."""

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        dependencies: list[str] | None = None,
    ) -> None:
        self._name = name
        self._version = version
        self._dependencies = dependencies or []
        self._capabilities: dict[str, IntegrationCapability] = {}
        self._status: IntegrationStatus = IntegrationStatus.AVAILABLE

    @property
    def name(self) -> str:
        """Nombre canónico del adapter."""
        return self._name

    @property
    def version(self) -> str:
        """Versión del adapter."""
        return self._version

    @property
    def status(self) -> IntegrationStatus:
        """Estado actual del adapter."""
        return self._status

    @status.setter
    def status(self, new_status: IntegrationStatus) -> None:
        self._status = new_status

    @property
    def dependencies(self) -> list[str]:
        """Lista de nombres de paquetes/módulos Python requeridos."""
        return list(self._dependencies)

    @property
    def capabilities(self) -> list[IntegrationCapability]:
        """Lista de capacidades registradas en este adapter."""
        return list(self._capabilities.values())

    def get_capability(self, capability_name: str) -> IntegrationCapability | None:
        """Obtiene una capacidad declarada por su nombre."""
        return self._capabilities.get(capability_name)

    def register_capability(self, capability: IntegrationCapability) -> None:
        """Registra una nueva capacidad en el adapter."""
        self._capabilities[capability.name] = capability

    def check_dependencies(self) -> tuple[bool, list[str]]:
        """Comprueba de forma segura y aislada si las dependencias requeridas están instaladas.

        Utiliza `importlib.util.find_spec` sin importar los módulos en el espacio global,
        evitando efectos secundarios, fallos de importación o dependencias circulares.

        Returns:
            Tuple (all_satisfied: bool, missing_dependencies: list[str]).
        """
        missing: list[str] = []
        for dep in self._dependencies:
            try:
                spec = importlib.util.find_spec(dep)
                if spec is None:
                    missing.append(dep)
            except (ImportError, ValueError, AttributeError):
                missing.append(dep)

        return (len(missing) == 0, missing)

    @abc.abstractmethod
    async def initialize(self) -> bool:
        """Inicializa el adapter y sus recursos asociados de forma asíncrona.

        Returns:
            True si la inicialización fue exitosa; False en caso contrario.
        """
        ...

    @abc.abstractmethod
    async def health_check(self) -> IntegrationHealth:
        """Ejecuta una comprobación de salud y diagnóstico del adapter.

        Returns:
            IntegrationHealth con métricas, estado y detalles.
        """
        ...

    @abc.abstractmethod
    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad específica expuesta por el adapter.

        IMPORTANTE: Debe adherirse al principio EXECUTE → VERIFY → REPORT.
        No debe auto-declarar verificación a menos que se obtenga evidencia real comprobable.

        Args:
            capability: Nombre de la capacidad a ejecutar.
            context: Parámetros y contexto de ejecución.

        Returns:
            IntegrationExecutionResult con el estado y los resultados.
        """
        ...

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Libera de forma ordenada todos los recursos asociados al adapter."""
        ...
