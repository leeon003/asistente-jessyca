"""Paquete de controladores de escritorio desacoplados de JESSYCA (core/desktop)."""

from core.desktop.cua_adapter import (
    CuaDriverAdapter,
    CuaDriverConfig,
    CuaSecurityViolationError,
    CuaUnavailableError,
)
from core.desktop.driver_protocol import (
    DesktopActionResult,
    DesktopDriverProtocol,
    NativeWindowsDriver,
)
from core.desktop.unified_controller import (
    DesktopControllerProtocol,
    DesktopSecurityError,
    SessionExecutionLock,
    SessionLockBusyError,
    StaleCoordinatesError,
    UnifiedDesktopController,
)

__all__ = [
    "CuaDriverAdapter",
    "CuaDriverConfig",
    "CuaSecurityViolationError",
    "CuaUnavailableError",
    "DesktopActionResult",
    "DesktopControllerProtocol",
    "DesktopDriverProtocol",
    "DesktopSecurityError",
    "NativeWindowsDriver",
    "SessionExecutionLock",
    "SessionLockBusyError",
    "StaleCoordinatesError",
    "UnifiedDesktopController",
]
