"""Gestión centralizada de rutas del proyecto y directorios de aplicación."""

from __future__ import annotations

from pathlib import Path


def get_project_root() -> Path:
    """Devuelve la ruta absoluta al directorio raíz del proyecto."""
    return Path(__file__).resolve().parent.parent


def get_logs_dir() -> Path:
    """Devuelve la ruta al directorio de logs, creándolo si no existe."""
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_config_dir() -> Path:
    """Devuelve la ruta al directorio de configuración."""
    config_dir = get_project_root() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_docs_dir() -> Path:
    """Devuelve la ruta al directorio de documentación."""
    docs_dir = get_project_root() / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    return docs_dir
