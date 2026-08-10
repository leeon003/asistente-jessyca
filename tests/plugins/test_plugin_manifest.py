"""Pruebas unitarias del Validador de Manifiesto de Plugins (Etapa 14.1).

REQUISITOS PROBADOS:
1. Validación de Esquema y Campos Requeridos: Rechaza campos faltantes o malformados.
2. Validación de Versión (SemVer): Rechaza versiones no estándar.
3. Validación de Identificador: Rechaza identificadores inválidos o con traversal.
4. Seguridad de Rutas (Path Security): Rechaza rutas absolutas y path traversal (../).
5. Rechazo de Capacidades Duplicadas.
6. Rechazo de Capacidades Desconocidas / Inventadas.
7. Rechazo de Autoelevación de Riesgo.
8. Flujo Obligatorio: Manifest -> Validation (is_approved=False) -> Approval (is_approved=True).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.plugin_manifest import (
    PluginManifestValidator,
    PluginPathSecurityError,
    PluginValidationError,
    PluginVersionError,
)
from core.plugin_security import (
    PluginCapabilityViolationError,
    PluginPrivilegeElevationError,
)


def test_schema_required_fields() -> None:
    """Verifica que manifiestos faltos de campos obligatorios sean rechazados."""
    validator = PluginManifestValidator()

    bad_manifest = {
        "id": "valid-plugin-id",
        "name": "Test Plugin",
        # Falta 'version', 'entrypoint', 'capabilities'
    }

    with pytest.raises(PluginValidationError) as exc_info:
        validator.validate_manifest_dict(bad_manifest)

    assert "carece del campo obligatorio" in str(exc_info.value)


def test_version_semver_validation() -> None:
    """Verifica el rechazo de cadenas de versión que no siguen SemVer."""
    validator = PluginManifestValidator()

    invalid_versions = ["v1.0", "1.0", "beta-1", "abc", "2.1"]

    for bad_ver in invalid_versions:
        manifest_data = {
            "id": "valid-plugin-id",
            "name": "Test Plugin",
            "version": bad_ver,
            "description": "Test",
            "author": "Tester",
            "entrypoint": "main.py",
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginVersionError):
            validator.validate_manifest_dict(manifest_data)


def test_identifier_validation() -> None:
    """Verifica el rechazo de identificadores de plugin malformados o inválidos."""
    validator = PluginManifestValidator()

    invalid_ids = ["Invalid_ID", "plugin id with space", "../../bad_id", "PL!UG"]

    for bad_id in invalid_ids:
        manifest_data = {
            "id": bad_id,
            "name": "Test Plugin",
            "version": "1.0.0",
            "description": "Test",
            "author": "Tester",
            "entrypoint": "main.py",
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginValidationError):
            validator.validate_manifest_dict(manifest_data)


def test_path_security_traversal_rejection() -> None:
    """Verifica que se rechacen entrypoints absolutos o con Path Traversal (../)."""
    validator = PluginManifestValidator()

    dangerous_paths = [
        "../outside.py",
        "../../etc/passwd",
        "/usr/bin/python",
        "C:\\Windows\\System32\\cmd.exe",
        "src/../../hacked.py",
    ]

    for bad_path in dangerous_paths:
        manifest_data = {
            "id": "test-plugin-id",
            "name": "Test Plugin",
            "version": "1.0.0",
            "description": "Test",
            "author": "Tester",
            "entrypoint": bad_path,
            "capabilities": ["filesystem.read"],
        }
        with pytest.raises(PluginPathSecurityError):
            validator.validate_manifest_dict(manifest_data)


def test_duplicate_capabilities_rejection() -> None:
    """Verifica el rechazo de manifiestos con capacidades duplicadas."""
    validator = PluginManifestValidator()

    manifest_data = {
        "id": "test-plugin-id",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "Tester",
        "entrypoint": "main.py",
        "capabilities": ["filesystem.read", "filesystem.read"],  # Duplicado
    }

    with pytest.raises(PluginValidationError) as exc_info:
        validator.validate_manifest_dict(manifest_data)

    assert "Capacidad duplicada detectada" in str(exc_info.value)


def test_unknown_capabilities_rejection() -> None:
    """Verifica el rechazo de capacidades desconocidas o inventadas."""
    validator = PluginManifestValidator()

    manifest_data = {
        "id": "test-plugin-id",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "Tester",
        "entrypoint": "main.py",
        "capabilities": ["system.bypass"],  # Capacidad inventada
    }

    with pytest.raises(PluginCapabilityViolationError):
        validator.validate_manifest_dict(manifest_data)


def test_privilege_escalation_rejection() -> None:
    """Verifica el rechazo si el manifiesto intenta clasificar engañosamente el riesgo de sus herramientas."""
    validator = PluginManifestValidator()

    manifest_data = {
        "id": "test-plugin-id",
        "name": "Test Plugin",
        "version": "1.0.0",
        "description": "Test",
        "author": "Tester",
        "entrypoint": "main.py",
        "capabilities": ["process.execute"],
        "tools": [
            {
                "name": "powershell.execute",
                "operation": "run_script",
                "claimed_risk": "READ_ONLY",
            }
        ],
    }

    with pytest.raises(PluginPrivilegeElevationError):
        validator.validate_manifest_dict(manifest_data)


def test_full_validation_approval_flow(tmp_path: Path) -> None:
    """Verifica el flujo obligatorio: Manifest -> Validation (is_approved=False) -> Approval (is_approved=True)."""
    validator = PluginManifestValidator()

    valid_dict = {
        "id": "jessyca-plugin-notes",
        "name": "Notes Plugin",
        "version": "1.2.0",
        "description": "Plugin para lectura de notas",
        "author": "Jessyca Dev",
        "entrypoint": "src/notes.py",
        "capabilities": ["filesystem.read", "clipboard"],
        "permissions": [],
        "tools": [
            {"name": "file.read", "operation": "read_notes"}
        ],
    }

    # 1. Validación de Diccionario -> Retorna manifiesto validado pero NO aprobado automáticamente
    manifest = validator.validate_manifest_dict(valid_dict)
    assert manifest.metadata.plugin_id == "jessyca-plugin-notes"
    assert manifest.metadata.version == "1.2.0"
    assert manifest.is_approved is False

    # 2. Guardar a archivo JSON y validar desde archivo
    json_file = tmp_path / "plugin.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(valid_dict, f)

    manifest_from_file = validator.validate_manifest_file(json_file)
    assert manifest_from_file.metadata.plugin_id == "jessyca-plugin-notes"
    assert manifest_from_file.is_approved is False

    # 3. Aprobación Formal
    approved_manifest = validator.approve_manifest(manifest_from_file, reviewer_id="admin_user")
    assert approved_manifest.is_approved is True
    assert approved_manifest.metadata.plugin_id == "jessyca-plugin-notes"
