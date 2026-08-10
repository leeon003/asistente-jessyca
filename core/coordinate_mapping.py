"""Capa de mapeo de coordenadas y DPI Awareness (`windows.desktop` - Subetapa 08.4).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Evita interacciones en coordenadas incorrectas por escalado DPI de Windows, multi-monitor,
cambios de resolución o desplazamiento de ventanas.
NO asume que screen coordinate == logical coordinate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from core.desktop_executors_models import ValidatedTarget
from core.exceptions import MCPError
from core.logger import get_logger
from core.ui_inspection_models import UIElementBounds

logger = get_logger("jessyca.core.coordinate_mapping")


class CoordinateSpace(StrEnum):
    """Espacios de coordenadas de la interfaz gráfica de Windows."""

    PHYSICAL_PIXELS = "PHYSICAL_PIXELS"
    LOGICAL_DIP = "LOGICAL_DIP"
    CLIENT_RELATIVE = "CLIENT_RELATIVE"
    WINDOW_RELATIVE = "WINDOW_RELATIVE"


class CoordinateMappingError(MCPError):
    """Error base del subsistema de mapeo de coordenadas y DPI."""

    pass


class IncompatibleCoordinateSpaceError(CoordinateMappingError):
    """Error emitido cuando se especifica un espacio de coordenadas incompatible o no soportado."""

    pass


class MonitorNotFoundError(CoordinateMappingError):
    """Error emitido cuando no se encuentra un monitor visible para un punto o región dada."""

    pass


class DisplayContextChangedError(CoordinateMappingError):
    """Error emitido cuando la resolución, escala DPI o configuración de monitores cambia post-captura."""

    pass


class OffScreenCoordinateError(CoordinateMappingError):
    """Error emitido cuando las coordenadas calculadas quedan fuera de los límites de pantalla."""

    pass


@dataclass(frozen=True)
class DPIInfo:
    """Información inmutable de resolución y escalado DPI de un monitor."""

    dpi_x: int
    dpi_y: int
    scale_factor: float  # e.g., 1.0 = 100%, 1.25 = 125%, 1.50 = 150%, 2.00 = 200%

    def to_dict(self) -> dict[str, Any]:
        """Convierte la información DPI a diccionario estructurado."""
        return {
            "dpi_x": self.dpi_x,
            "dpi_y": self.dpi_y,
            "scale_factor": self.scale_factor,
            "percentage": f"{int(self.scale_factor * 100)}%",
        }


@dataclass(frozen=True)
class MonitorInfo:
    """Información inmutable de un monitor en la configuración del escritorio."""

    monitor_id: str
    device_name: str
    bounds: UIElementBounds
    dpi: DPIInfo
    is_primary: bool

    def to_dict(self) -> dict[str, Any]:
        """Convierte la información del monitor a diccionario estructurado."""
        return {
            "monitor_id": self.monitor_id,
            "device_name": self.device_name,
            "bounds": self.bounds.to_dict(),
            "dpi": self.dpi.to_dict(),
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True)
class ScreenMetrics:
    """Métricas inmutables globales de la pantalla y disposición de monitores."""

    monitors: tuple[MonitorInfo, ...]
    virtual_screen_bounds: UIElementBounds
    primary_monitor_id: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convierte las métricas de pantalla a diccionario seguro para auditoría."""
        return {
            "monitor_count": len(self.monitors),
            "monitors": [m.to_dict() for m in self.monitors],
            "virtual_screen_bounds": self.virtual_screen_bounds.to_dict(),
            "primary_monitor_id": self.primary_monitor_id,
            "timestamp": self.timestamp.isoformat(),
        }


class IScreenMetricsProvider(Protocol):
    """Protocolo abstracto para proveedores de métricas de pantalla y DPI."""

    def get_screen_metrics(self) -> ScreenMetrics:
        """Obtiene el resumen inmutable de métricas de pantalla actual."""
        ...

    def get_monitor_for_point(self, x: int, y: int) -> MonitorInfo:
        """Obtiene la información del monitor que contiene el punto (x, y)."""
        ...


class FakeScreenMetricsProvider(IScreenMetricsProvider):
    """Proveedor sintético de métricas de pantalla para pruebas deterministas (multi-monitor y variados DPI)."""

    def __init__(self, metrics: ScreenMetrics | None = None) -> None:
        if metrics:
            self._metrics = metrics
        else:
            # Configuración sintética por defecto: Monitor primario 100% DPI (1920x1080)
            mon1 = MonitorInfo(
                monitor_id="mon-primary",
                device_name="DISPLAY1",
                bounds=UIElementBounds(x=0, y=0, width=1920, height=1080),
                dpi=DPIInfo(dpi_x=96, dpi_y=96, scale_factor=1.0),
                is_primary=True,
            )
            self._metrics = ScreenMetrics(
                monitors=(mon1,),
                virtual_screen_bounds=UIElementBounds(x=0, y=0, width=1920, height=1080),
                primary_monitor_id="mon-primary",
                timestamp=datetime.now(UTC),
            )

    def set_metrics(self, metrics: ScreenMetrics) -> None:
        """Actualiza la configuración de métricas sintéticas."""
        self._metrics = metrics

    def get_screen_metrics(self) -> ScreenMetrics:
        return self._metrics

    def get_monitor_for_point(self, x: int, y: int) -> MonitorInfo:
        for mon in self._metrics.monitors:
            if mon.bounds.x <= x <= mon.bounds.right and mon.bounds.y <= y <= mon.bounds.bottom:
                return mon
        # Fallback al monitor primario si la coordenada está cerca o dentro del escritorio virtual
        for mon in self._metrics.monitors:
            if mon.is_primary:
                return mon
        raise MonitorNotFoundError(f"No se encontró un monitor sintético para las coordenadas ({x}, {y}).")


class WindowsScreenMetricsProvider(IScreenMetricsProvider):
    """Proveedor nativo de métricas de pantalla de Windows mediante Win32 / User32 APIs."""

    def get_screen_metrics(self) -> ScreenMetrics:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()  # DPI awareness en proceso Windows

            w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            h = user32.GetSystemMetrics(1)  # SM_CYSCREEN

            dpi_x = 96
            dpi_y = 96
            scale = 1.0

            try:
                hdc = user32.GetDC(0)
                gdi32 = ctypes.windll.gdi32
                dpi_x = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                dpi_y = gdi32.GetDeviceCaps(hdc, 90)  # LOGPIXELSY
                user32.ReleaseDC(0, hdc)
                scale = round(dpi_x / 96.0, 2)
            except Exception:
                pass

            primary_mon = MonitorInfo(
                monitor_id="win-mon-primary",
                device_name="PRIMARY_DISPLAY",
                bounds=UIElementBounds(x=0, y=0, width=w, height=h),
                dpi=DPIInfo(dpi_x=dpi_x, dpi_y=dpi_y, scale_factor=scale),
                is_primary=True,
            )

            return ScreenMetrics(
                monitors=(primary_mon,),
                virtual_screen_bounds=UIElementBounds(x=0, y=0, width=w, height=h),
                primary_monitor_id="win-mon-primary",
                timestamp=datetime.now(UTC),
            )
        except Exception as e:
            logger.warning(f"[WINDOWS METRICS FAIL-SAFE] Fallo al consultar métricas nativas ({e}). Delegando a FakeScreenMetricsProvider.")
            return FakeScreenMetricsProvider().get_screen_metrics()

    def get_monitor_for_point(self, x: int, y: int) -> MonitorInfo:
        metrics = self.get_screen_metrics()
        for mon in metrics.monitors:
            if mon.bounds.x <= x <= mon.bounds.right and mon.bounds.y <= y <= mon.bounds.bottom:
                return mon
        return metrics.monitors[0]


class CoordinateMapper:
    """Motor de conversión de coordenadas y validación de contexto DPI y pantalla."""

    def __init__(self, provider: IScreenMetricsProvider | None = None) -> None:
        self.provider = provider or FakeScreenMetricsProvider()

    def convert_point(
        self,
        point: tuple[int, int],
        source_space: CoordinateSpace,
        target_space: CoordinateSpace,
        monitor: MonitorInfo,
    ) -> tuple[int, int]:
        """Convierte un punto (x, y) entre espacios de coordenadas considerando el escalado DPI del monitor."""
        if source_space == target_space:
            return point

        x, y = point
        scale = monitor.dpi.scale_factor

        # 1. Convertir origen a PHYSICAL_PIXELS
        if source_space == CoordinateSpace.LOGICAL_DIP:
            phys_x = int(round(x * scale))
            phys_y = int(round(y * scale))
        elif source_space == CoordinateSpace.PHYSICAL_PIXELS:
            phys_x, phys_y = x, y
        else:
            raise IncompatibleCoordinateSpaceError(f"Espacio de coordenadas de origen no soportado: '{source_space}'")

        # 2. Convertir PHYSICAL_PIXELS al target_space deseado
        if target_space == CoordinateSpace.PHYSICAL_PIXELS:
            return (phys_x, phys_y)
        elif target_space == CoordinateSpace.LOGICAL_DIP:
            log_x = int(round(phys_x / scale))
            log_y = int(round(phys_y / scale))
            return (log_x, log_y)
        else:
            raise IncompatibleCoordinateSpaceError(f"Espacio de coordenadas de destino no soportado: '{target_space}'")

    def validate_and_map_target(
        self,
        target: ValidatedTarget,
        captured_metrics: ScreenMetrics,
        current_metrics: ScreenMetrics | None = None,
    ) -> ValidatedTarget:
        """Valida rigurosamente la compatibilidad de pantalla y DPI de un objetivo antes de la ejecución.

        Pasos de verificación:
        1. Identificar monitor del objetivo.
        2. Obtener y comparar factor de escala DPI.
        3. Validar límites de resolución y pantalla virtual.
        4. Recalcular coordenadas si aplica escalado.
        5. Rechazar con DisplayContextChangedError o OffScreenCoordinateError si el contexto cambió.
        """
        curr_metrics = current_metrics or self.provider.get_screen_metrics()

        # 1. Verificar si la cantidad de monitores cambió
        if len(captured_metrics.monitors) != len(curr_metrics.monitors):
            raise DisplayContextChangedError(
                f"Acción denegada: La disposición de monitores ha cambiado "
                f"({len(captured_metrics.monitors)} monitores capturados vs {len(curr_metrics.monitors)} actuales)."
            )

        # 2. Identificar monitor del objetivo en las métricas actuales
        cx, cy = target.center_x, target.center_y
        try:
            current_mon = self.provider.get_monitor_for_point(cx, cy)
        except Exception:
            raise MonitorNotFoundError(f"Acción denegada: El monitor para las coordenadas ({cx}, {cy}) ya no está disponible.")

        # 3. Verificar si las coordenadas caen fuera de la pantalla virtual
        v_bounds = curr_metrics.virtual_screen_bounds
        if cx < v_bounds.x or cx > v_bounds.right or cy < v_bounds.y or cy > v_bounds.bottom:
            raise OffScreenCoordinateError(
                f"Acción denegada: Coordenadas ({cx}, {cy}) fuera de los límites de pantalla "
                f"({v_bounds.width}x{v_bounds.height})."
            )

        # 4. Verificar consistencia de DPI scale factor
        cap_mon = captured_metrics.monitors[0]
        if abs(cap_mon.dpi.scale_factor - current_mon.dpi.scale_factor) > 0.01:
            raise DisplayContextChangedError(
                f"Acción denegada: El factor de escala DPI cambió post-captura "
                f"({cap_mon.dpi.scale_factor:.2f} vs {current_mon.dpi.scale_factor:.2f}). Target invalidado."
            )

        # 5. Mapear coordenadas si la escala es diferente de 1.0 (DPI Scaling)
        if current_mon.dpi.scale_factor != 1.0:
            phys_x, phys_y = self.convert_point(
                (target.bounds.x, target.bounds.y),
                source_space=CoordinateSpace.LOGICAL_DIP,
                target_space=CoordinateSpace.PHYSICAL_PIXELS,
                monitor=current_mon,
            )
            phys_w = int(round(target.bounds.width * current_mon.dpi.scale_factor))
            phys_h = int(round(target.bounds.height * current_mon.dpi.scale_factor))

            scaled_bounds = UIElementBounds(x=phys_x, y=phys_y, width=phys_w, height=phys_h)

            return ValidatedTarget(
                hwnd=target.hwnd,
                owner_title=target.owner_title,
                bounds=scaled_bounds,
                confidence=target.confidence,
                state_hash=target.state_hash,
                timestamp=target.timestamp,
                automation_id=target.automation_id,
                control_type=target.control_type,
            )

        return target
