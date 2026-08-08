"""Servicio de diagnóstico e información del sistema operativo Windows.

Proporciona información sobre la versión de Windows, métricas de CPU/RAM y estado de permisos.
"""

from __future__ import annotations

from typing import Any

from core.types import Result
from services.base_service import BaseService
from utils.platform import check_windows_compatibility, get_system_metrics, is_admin


class SystemService(BaseService):
    """Servicio para consulta y diagnóstico del entorno de plataforma Windows."""

    def __init__(self) -> None:
        super().__init__(name="SystemService")

    def _on_initialize(self) -> None:
        # Verificar compatibilidad de Windows al iniciar el servicio
        self._compatibility = check_windows_compatibility()
        self._logger.info(
            f"Diagnóstico de SO: {self._compatibility.version.value} (Build {self._compatibility.build_number})"
        )

    def _on_shutdown(self) -> None:
        pass

    def get_system_diagnostics(self) -> Result[dict[str, Any]]:
        """Obtiene un informe completo del diagnóstico del sistema."""
        if not self.is_initialized:
            return Result.fail("SystemService no ha sido inicializado.")

        try:
            metrics = get_system_metrics()
            metrics["windows_compatibility"] = {
                "is_compatible": self._compatibility.is_compatible,
                "version": self._compatibility.version.value,
                "build_number": self._compatibility.build_number,
                "architecture": self._compatibility.architecture,
            }
            metrics["is_admin"] = is_admin()
            return Result.ok(metrics)
        except Exception as e:
            self._logger.error(f"Error al recopilar diagnósticos del sistema: {e}")
            return Result.fail(e)
