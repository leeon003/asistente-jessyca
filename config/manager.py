"""Gestor central de configuración para Jessyca Windows MCP.

Implementa el patrón Singleton para garantizar una única fuente de verdad
para los parámetros del sistema y permitir recarga dinámica de variables.
"""

from __future__ import annotations

from config.settings import AppSettings
from core.exceptions import ConfigurationError
from core.logger import get_logger

logger = get_logger("jessyca.config")


class ConfigManager:
    """Gestor de configuración centralizado."""

    _instance: ConfigManager | None = None
    _settings: AppSettings | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_settings(self, env_file: str | None = None) -> AppSettings:
        """Carga o recarga la configuración desde el archivo .env especificado o variables de entorno.

        Args:
            env_file: Ruta opcional a un archivo de variables de entorno custom.

        Returns:
            Instancia validada de AppSettings.
        """
        try:
            if env_file:
                self._settings = AppSettings(_env_file=env_file)  # type: ignore[call-arg]
            else:
                self._settings = AppSettings()

            logger.info(
                f"Configuración cargada exitosamente [Entorno: {self._settings.ENVIRONMENT.value}, LogLevel: {self._settings.LOG_LEVEL.value}]"
            )
            return self._settings
        except Exception as e:
            msg = f"Error crítico al cargar la configuración: {e}"
            logger.error(msg)
            raise ConfigurationError(msg) from e

    def get_settings(self) -> AppSettings:
        """Obtiene la configuración activa. Si no ha sido cargada, la inicializa."""
        if self._settings is None:
            return self.load_settings()
        return self._settings

    def reload(self) -> AppSettings:
        """Fuerza la recarga de los valores de configuración."""
        logger.info("Recargando configuración...")
        return self.load_settings()


def get_settings() -> AppSettings:
    """Función de conveniencia para acceder a la configuración global."""
    return ConfigManager().get_settings()
