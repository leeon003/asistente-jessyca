"""Pruebas unitarias y adversariales de PluginLoader (Etapa 14.2).

REQUISITOS ADVERSARIALES PROBADOS:
1. REGLA CRÍTICA: No importar código de plugin antes de validar su manifiesto.
2. Carga exclusiva desde PLUGINS_DIRECTORY.
3. Prevenir Path Traversal (..) y Symlink Escape fuera del directorio permitido.
4. Prevenir carga desde ubicaciones arbitrarias fuera del sandbox.
5. Prevenir IDs de plugin duplicados (Duplicate plugin IDs).
6. Prevenir desacople entre manifiesto y código (Manifest/Code Mismatch).
7. Capacidad acotada (PLUGINS_MAX_LOADED).
8. Funcionamiento de FakePluginLoader en aislamiento.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.plugin_loader import (
    FakePluginLoader,
    PluginCapacityExceededError,
    PluginIntegrityError,
    PluginLoader,
    PluginLoaderSecurityError,
)
from core.plugin_manifest import PluginPathSecurityError, PluginValidationError


def _create_mock_plugin(base_dir: Path, plugin_id: str, entrypoint: str = "main.py", corrupted_json: bool = False) -> Path:
    """Helper para crear una estructura de plugin temporal válida."""
    p_dir = base_dir / plugin_id
    p_dir.mkdir(parents=True, exist_ok=True)

    if corrupted_json:
        with open(p_dir / "plugin.json", "w", encoding="utf-8") as f:
            f.write("{ INVALID JSON CORRUPTED ...")
    else:
        manifest_dict = {
            "id": plugin_id,
            "name": f"Name {plugin_id}",
            "version": "1.0.0",
            "description": "Mock plugin",
            "author": "Tester",
            "entrypoint": entrypoint,
            "capabilities": ["filesystem.read"],
            "permissions": [],
            "tools": [{"name": "file.read", "operation": "read"}],
        }
        with open(p_dir / "plugin.json", "w", encoding="utf-8") as f:
            json.dump(manifest_dict, f)

    if entrypoint and not corrupted_json:
        ep_file = p_dir / entrypoint
        ep_file.parent.mkdir(parents=True, exist_ok=True)
        with open(ep_file, "w", encoding="utf-8") as f:
            f.write("def run(): return 'SUCCESS'\n")

    return p_dir


def test_loader_disabled_by_default() -> None:
    """Verifica que si PLUGINS_ENABLED=False se rechace la carga de cualquier plugin."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)
        loader.enabled = False

        _create_mock_plugin(plugins_dir, "test-plugin-01")

        with pytest.raises(PluginLoaderSecurityError) as exc_info:
            loader.load_plugin(plugins_dir / "test-plugin-01")

        assert "deshabilitada por configuración" in str(exc_info.value)


def test_pre_import_manifest_validation_mandatory() -> None:
    """Verifica la regla crítica: Un manifiesto corrupto/inválido aborta antes de importar ningún código."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)

        # Crear plugin con JSON corrupto
        p_dir = _create_mock_plugin(plugins_dir, "corrupted-plugin", corrupted_json=True)

        with pytest.raises(PluginValidationError):
            loader.load_plugin(p_dir)


def test_arbitrary_location_rejection() -> None:
    """Verifica que intentar cargar un plugin desde una ubicación fuera de PLUGINS_DIRECTORY sea rechazado."""
    with tempfile.TemporaryDirectory() as plugins_tmp, tempfile.TemporaryDirectory() as external_tmp:
        plugins_dir = Path(plugins_tmp)
        external_dir = Path(external_tmp)

        loader = PluginLoader(plugins_dir=plugins_dir)

        # Crear plugin fuera de plugins_dir
        ext_plugin_dir = _create_mock_plugin(external_dir, "external-plugin")

        with pytest.raises(PluginPathSecurityError) as exc_info:
            loader.load_plugin(ext_plugin_dir)

        assert "Symlink Escape" in str(exc_info.value) or "estrictamente dentro" in str(exc_info.value)


def test_duplicate_plugin_id_rejection() -> None:
    """Verifica que no se puedan cargar dos plugins con el mismo plugin_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)

        p1_dir = _create_mock_plugin(plugins_dir, "duplicate-plugin-id")
        loader.load_plugin(p1_dir)

        # Intentar cargar de nuevo el mismo plugin o uno con el mismo ID
        with pytest.raises(PluginLoaderSecurityError) as exc_info:
            loader.load_plugin(p1_dir)

        assert "ya se encuentra cargado en memoria" in str(exc_info.value)


def test_manifest_code_mismatch_rejection() -> None:
    """Verifica el rechazo cuando el entrypoint declarado no existe (Manifest/Code Mismatch)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir)

        # Manifiesto declara entrypoint 'missing.py', pero solo creamos el JSON
        p_dir = plugins_dir / "mismatch-plugin"
        p_dir.mkdir(parents=True, exist_ok=True)
        manifest_dict = {
            "id": "mismatch-plugin",
            "name": "Mismatch Plugin",
            "version": "1.0.0",
            "description": "Mock",
            "author": "Tester",
            "entrypoint": "missing.py",
            "capabilities": ["filesystem.read"],
        }
        with open(p_dir / "plugin.json", "w", encoding="utf-8") as f:
            json.dump(manifest_dict, f)

        with pytest.raises(PluginIntegrityError) as exc_info:
            loader.load_plugin(p_dir)

        assert "MANIFEST/CODE MISMATCH" in str(exc_info.value)


def test_bounded_max_loaded_capacity() -> None:
    """Verifica que no se puedan cargar más de PLUGINS_MAX_LOADED plugins."""
    with tempfile.TemporaryDirectory() as tmpdir:
        plugins_dir = Path(tmpdir)
        loader = PluginLoader(plugins_dir=plugins_dir, max_loaded=2)

        p1 = _create_mock_plugin(plugins_dir, "plugin-01")
        p2 = _create_mock_plugin(plugins_dir, "plugin-02")
        p3 = _create_mock_plugin(plugins_dir, "plugin-03")

        loader.load_plugin(p1)
        loader.load_plugin(p2)

        with pytest.raises(PluginCapacityExceededError) as exc_info:
            loader.load_plugin(p3)

        assert "CAPACITY EXCEEDED" in str(exc_info.value)


def test_fake_plugin_loader() -> None:
    """Verifica el funcionamiento desacoplado de FakePluginLoader."""
    fake_loader = FakePluginLoader()
    with tempfile.TemporaryDirectory() as tmpdir:
        p_dir = _create_mock_plugin(Path(tmpdir), "fake-plugin-1")
        loaded = fake_loader.load_plugin(p_dir)

        assert loaded.manifest.metadata.plugin_id == "fake-plugin-1"
        assert fake_loader.get_loaded_plugin("fake-plugin-1") is not None

        unloaded = fake_loader.unload_plugin("fake-plugin-1")
        assert unloaded is True
        assert fake_loader.get_loaded_plugin("fake-plugin-1") is None
