"""Utilidades de detección e inspección del sistema operativo Windows 10 y 11.

Proporciona funciones para verificar la versión exacta del SO, el número de build,
el estado de privilegios de administrador y métricas básicas del sistema.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass
from typing import Any

from core.constants import WINDOWS_MIN_BUILD_WIN10, WINDOWS_MIN_BUILD_WIN11
from core.types import WindowsVersion


@dataclass
class WindowsCompatibilityInfo:
    """Información de compatibilidad con la plataforma Windows."""

    is_windows: bool
    version: WindowsVersion
    build_number: int
    architecture: str
    is_compatible: bool
    details: str


def is_windows() -> bool:
    """Verifica si la plataforma de ejecución actual es Windows."""
    return sys.platform == "win32" or os.name == "nt"


def is_admin() -> bool:
    """Verifica si el proceso actual se ejecuta con privilegios de Administrador en Windows."""
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_windows_build_number() -> int:
    """Obtiene el número de build exacto del sistema operativo Windows."""
    if not is_windows():
        return 0
    try:
        version_str = platform.version()
        # Formato habitual en Windows: '10.0.19045'
        parts = version_str.split(".")
        if len(parts) >= 3:
            return int(parts[2])
    except Exception:
        pass
    return 0


def check_windows_compatibility() -> WindowsCompatibilityInfo:
    """Evalúa la compatibilidad del sistema operativo con Jessyca Windows MCP.

    Soporta Windows 10 (Build >= 19041) y Windows 11 (Build >= 22000).
    """
    if not is_windows():
        return WindowsCompatibilityInfo(
            is_windows=False,
            version=WindowsVersion.UNSUPPORTED,
            build_number=0,
            architecture=platform.architecture()[0],
            is_compatible=False,
            details="Sistema operativo no es Windows.",
        )

    build = get_windows_build_number()
    arch = platform.architecture()[0]

    if build >= WINDOWS_MIN_BUILD_WIN11:
        version = WindowsVersion.WINDOWS_11
        is_comp = True
        msg = f"Sistema plenamente compatible: Windows 11 (Build {build}, {arch})."
    elif build >= WINDOWS_MIN_BUILD_WIN10:
        version = WindowsVersion.WINDOWS_10
        is_comp = True
        msg = f"Sistema plenamente compatible: Windows 10 (Build {build}, {arch})."
    else:
        version = WindowsVersion.UNSUPPORTED
        is_comp = False
        msg = f"Versión de Windows desactualizada (Build {build}). Se requiere Windows 10 Build >= 19041 o Windows 11."

    return WindowsCompatibilityInfo(
        is_windows=True,
        version=version,
        build_number=build,
        architecture=arch,
        is_compatible=is_comp,
        details=msg,
    )


def get_system_metrics() -> dict[str, Any]:
    """Obtiene métricas básicas del hardware y rendimiento del sistema."""
    import psutil

    cpu_percent = psutil.cpu_percent(interval=0.1)
    virtual_mem = psutil.virtual_memory()

    return {
        "cpu_usage_percent": cpu_percent,
        "memory_total_bytes": virtual_mem.total,
        "memory_available_bytes": virtual_mem.available,
        "memory_usage_percent": virtual_mem.percent,
        "python_version": platform.python_version(),
    }
