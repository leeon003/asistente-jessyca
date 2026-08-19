# conftest.py
# Archivo de configuración para pytest
import os
import sys

# Asegurar que el directorio raíz del proyecto esté PRIMERO en sys.path
_root = os.path.abspath(os.path.dirname(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)

# Pre-cargar el paquete 'server' raíz para evitar colisión con tests/server/
# (cuando tests/server/__init__.py existe, Python podría resolver 'server' como el paquete de tests)
import importlib.util as _importlib_util

if "server" not in sys.modules:
    _server_spec = _importlib_util.spec_from_file_location(
        "server",
        os.path.join(_root, "server", "__init__.py"),
        submodule_search_locations=[os.path.join(_root, "server")],
    )
    if _server_spec and _server_spec.loader:
        _server_mod = _importlib_util.module_from_spec(_server_spec)
        sys.modules["server"] = _server_mod
        _server_spec.loader.exec_module(_server_mod)  # type: ignore[union-attr]
