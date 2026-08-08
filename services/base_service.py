"""Clase abstracta base para todos los servicios de aplicación en Jessyca.

Implementa la interfaz IService y administra el ciclo de vida seguro del servicio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.contracts import IService
from core.logger import get_logger


class BaseService(IService, ABC):
    """Clase base abstracta para servicios con control de ciclo de vida."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._initialized = False
        self._logger = get_logger(f"jessyca.services.{name}")

    @property
    def service_name(self) -> str:
        return self._name

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> None:
        """Inicializa el servicio si no ha sido inicializado previamente."""
        if self._initialized:
            self._logger.warning(f"El servicio '{self._name}' ya se encuentra inicializado.")
            return

        self._logger.info(f"Inicializando servicio '{self._name}'...")
        self._on_initialize()
        self._initialized = True
        self._logger.info(f"Servicio '{self._name}' inicializado con éxito.")

    def shutdown(self) -> None:
        """Finaliza y libera los recursos del servicio."""
        if not self._initialized:
            self._logger.warning(f"El servicio '{self._name}' no está inicializado.")
            return

        self._logger.info(f"Deteniendo servicio '{self._name}'...")
        self._on_shutdown()
        self._initialized = False
        self._logger.info(f"Servicio '{self._name}' detenido correctamente.")

    @abstractmethod
    def _on_initialize(self) -> None:
        """Hook abstracto para la inicialización específica de recursos en subclases."""
        pass

    @abstractmethod
    def _on_shutdown(self) -> None:
        """Hook abstracto para la liberación específica de recursos en subclases."""
        pass
