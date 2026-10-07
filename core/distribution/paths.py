"""core/distribution/paths.py

Módulo canónico de segregación y resolución de rutas para la distribución de JESSYCA.
Garantiza la separación estricta entre:
1. Código instalado (read-only): Ubicación del paquete/repositorio en el sistema.
2. Configuración del usuario: Preferencias y secretos del usuario (%APPDATA%\\jessyca).
3. Memoria y datos persistentes: Bases de datos SQLite y memoria (%LOCALAPPDATA%\\jessyca\\data).
4. Logs: Registros operacionales y eventos de auditoría (%LOCALAPPDATA%\\jessyca\\logs).
5. Cachés y modelos: Runtimes efímeros y pesos LLM locales (%LOCALAPPDATA%\\jessyca\\cache, models).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JessycaPaths:
    """Rutas canónicas segregadas de la instalación y ejecución de JESSYCA."""

    code_dir: Path
    config_dir: Path
    data_dir: Path
    logs_dir: Path
    cache_dir: Path
    models_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "code_dir": str(self.code_dir),
            "config_dir": str(self.config_dir),
            "data_dir": str(self.data_dir),
            "logs_dir": str(self.logs_dir),
            "cache_dir": str(self.cache_dir),
            "models_dir": str(self.models_dir),
        }


def get_installed_code_dir() -> Path:
    """Devuelve el directorio base del código instalado (read-only en runtime)."""
    # Ubicación base relativa a este módulo dentro del paquete
    return Path(__file__).resolve().parents[2]


def get_user_config_dir() -> Path:
    """Devuelve el directorio de configuración del usuario."""
    if os.environ.get("JESSYCA_CONFIG_DIR"):
        return Path(os.environ["JESSYCA_CONFIG_DIR"]).resolve()

    if os.environ.get("JESSYCA_HOME"):
        return (Path(os.environ["JESSYCA_HOME"]) / "config").resolve()

    appdata = os.environ.get("APPDATA")
    if appdata:
        return (Path(appdata) / "jessyca").resolve()

    return (Path.home() / ".config" / "jessyca").resolve()


def get_user_data_dir() -> Path:
    """Devuelve el directorio de memoria y datos persistentes (sessions.db, ltm, etc.)."""
    if os.environ.get("JESSYCA_DATA_DIR"):
        return Path(os.environ["JESSYCA_DATA_DIR"]).resolve()

    if os.environ.get("JESSYCA_HOME"):
        return (Path(os.environ["JESSYCA_HOME"]) / "data").resolve()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return (Path(localappdata) / "jessyca" / "data").resolve()

    return (Path.home() / ".local" / "share" / "jessyca" / "data").resolve()


def get_logs_dir() -> Path:
    """Devuelve el directorio de logs y auditoría."""
    if os.environ.get("JESSYCA_LOG_DIR"):
        return Path(os.environ["JESSYCA_LOG_DIR"]).resolve()

    if os.environ.get("JESSYCA_HOME"):
        return (Path(os.environ["JESSYCA_HOME"]) / "logs").resolve()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return (Path(localappdata) / "jessyca" / "logs").resolve()

    return (Path.home() / ".local" / "state" / "jessyca" / "logs").resolve()


def get_cache_dir() -> Path:
    """Devuelve el directorio de archivos temporales y cachés efímeras."""
    if os.environ.get("JESSYCA_CACHE_DIR"):
        return Path(os.environ["JESSYCA_CACHE_DIR"]).resolve()

    if os.environ.get("JESSYCA_HOME"):
        return (Path(os.environ["JESSYCA_HOME"]) / "cache").resolve()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return (Path(localappdata) / "jessyca" / "cache").resolve()

    return (Path.home() / ".cache" / "jessyca").resolve()


def get_models_dir() -> Path:
    """Devuelve el directorio local de almacenamiento o symlinks de modelos LLM."""
    if os.environ.get("JESSYCA_MODELS_DIR"):
        return Path(os.environ["JESSYCA_MODELS_DIR"]).resolve()

    if os.environ.get("JESSYCA_HOME"):
        return (Path(os.environ["JESSYCA_HOME"]) / "models").resolve()

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return (Path(localappdata) / "jessyca" / "models").resolve()

    return (Path.home() / ".local" / "share" / "jessyca" / "models").resolve()


def get_paths() -> JessycaPaths:
    """Obtiene el conjunto completo de rutas segregadas activas."""
    return JessycaPaths(
        code_dir=get_installed_code_dir(),
        config_dir=get_user_config_dir(),
        data_dir=get_user_data_dir(),
        logs_dir=get_logs_dir(),
        cache_dir=get_cache_dir(),
        models_dir=get_models_dir(),
    )


def ensure_directories(paths: JessycaPaths | None = None) -> JessycaPaths:
    """Crea los directorios mutables necesarios en el sistema si aún no existen."""
    effective_paths = paths or get_paths()
    for directory in (
        effective_paths.config_dir,
        effective_paths.data_dir,
        effective_paths.logs_dir,
        effective_paths.cache_dir,
        effective_paths.models_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return effective_paths
