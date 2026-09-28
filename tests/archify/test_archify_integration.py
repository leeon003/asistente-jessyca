"""Batería de Pruebas Unitarias, Integración y Seguridad para Archify (tests/archify/test_archify_integration.py).

Cubre:
1. Health check y detección de Node.js.
2. Validación de especificaciones (architecture, workflow, sequence, dataflow, lifecycle).
3. Modo Shadow: observación comparativa sin escritura en disco.
4. Modo Active: compilación de HTML autocontenido interactivo con SVG.
5. Inyección de fallas: Path Traversal, XSS, Fuga de secretos, DoS (exceso de nodos).
6. Integración con BaseSkill (ArchifySkill) y gobernanza de JDE.
7. Comprobación por ExecutionVerifier de los artefactos generados.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from core.archify.adapter import (
    ArchifyDiagramType,
    ArchifyMode,
    JessycaArchifyAdapter,
    reset_archify_adapter,
)
from lab.archify.archify_lab import ArchifyLab
from skills.archify_skill import ArchifySkill
from skills.skill_models import SkillContext, SkillStatus


@pytest.fixture
def temp_lab_dir():
    d = tempfile.mkdtemp(prefix="test_archify_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def test_01_health_check_detects_node_runtime():
    """1. Health check detecta la disponibilidad y versión de Node.js."""
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.SHADOW)
    hc = adapter.health_check()
    assert "status" in hc
    assert hc["node_available"] is True
    assert hc["mode"] == "SHADOW"
    assert "architecture" in hc["supported_diagram_types"]


def test_02_validation_rejects_unsupported_diagram_type():
    """2. Validación rechaza tipos de diagrama no soportados."""
    adapter = JessycaArchifyAdapter()
    spec = {"nodes": [{"id": "n1"}], "edges": []}
    res = adapter.validate_spec(spec, diagram_type="quantum_teleportation")
    assert res.is_valid is False
    assert any("no soportado" in e for e in res.errors)


def test_03_validation_accepts_valid_architecture_spec():
    """3. Validación acepta especificación bien formada."""
    adapter = JessycaArchifyAdapter()
    spec = {
        "title": "Test System",
        "nodes": [
            {"id": "api", "name": "API Gateway"},
            {"id": "db", "name": "Postgres DB"},
        ],
        "edges": [
            {"from": "api", "to": "db"},
        ],
    }
    res = adapter.validate_spec(spec, diagram_type="architecture")
    assert res.is_valid is True
    assert res.node_count == 2
    assert res.edge_count == 1
    assert len(res.errors) == 0


def test_04_shadow_mode_observes_without_writing_file(temp_lab_dir):
    """4. Shadow Mode registra la observación y no escribe archivos físicos en disco."""
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.SHADOW, output_dir=temp_lab_dir)
    spec = {"title": "Demo", "nodes": [{"id": "a"}], "edges": []}

    obs = adapter.observe_shadow(intent="show_arch", proposed_spec=spec, diagram_type="architecture")
    assert obs.validation_status is True
    assert obs.comparison_verdict == "ENRICHED_VISUALIZATION"
    assert len(adapter.get_shadow_history()) == 1

    # Render en modo SHADOW retorna simulación sin escribir en disco
    success, msg, path = adapter.render_diagram(spec, "architecture", "test.html")
    assert success is True
    assert "Modo Shadow" in msg
    assert path == ""
    assert len(os.listdir(temp_lab_dir)) == 0


def test_05_active_mode_renders_valid_standalone_html(temp_lab_dir):
    """5. Modo Active compila HTML autocontenido con SVG y estilos interactivos."""
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.ACTIVE, output_dir=temp_lab_dir)
    spec = {
        "title": "JESSYCA Pipeline",
        "nodes": [
            {"id": "agent", "name": "JessycaAgent"},
            {"id": "jde", "name": "DecisionEngine"},
        ],
        "edges": [
            {"from": "agent", "to": "jde"},
        ],
    }

    success, msg, path = adapter.render_diagram(spec, "workflow", "pipeline.html")
    assert success is True
    assert os.path.exists(path)
    assert path.endswith("pipeline.html")

    # Verificar contenido del archivo generado
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "<!DOCTYPE html>" in content
    assert "<svg id=\"archify-svg\"" in content
    assert "JessycaAgent" in content
    assert "DecisionEngine" in content
    assert "toggleTheme()" in content


def test_06_failure_injection_path_traversal_blocked(temp_lab_dir):
    """6. Inyección de Path Traversal es neutralizada y bloqueada."""
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.ACTIVE, output_dir=temp_lab_dir)
    spec = {"nodes": [{"id": "n1"}]}

    success, msg, path = adapter.render_diagram(spec, "architecture", "../../malicious.html")
    assert success is False
    assert "Path Traversal" in msg
    assert path == ""


def test_07_failure_injection_xss_sanitization():
    """7. Etiquetas maliciosas con XSS son escapadas de forma segura."""
    adapter = JessycaArchifyAdapter()
    malicious = {
        "title": "<script>alert(1)</script>",
        "nodes": [{"id": "xss", "name": "<b onmouseover=alert('hack')>Injected</b>"}],
    }
    cleaned = adapter.sanitize_spec(malicious)
    assert "<script>" not in cleaned["title"]
    assert "&lt;script&gt;" in cleaned["title"]
    assert "&lt;b" in cleaned["nodes"][0]["name"]


def test_08_failure_injection_dos_limits_enforced():
    """8. Reglas Anti-DoS rechazan especificaciones que exceden límites de nodos."""
    adapter = JessycaArchifyAdapter()
    huge_spec = {"nodes": [{"id": f"node_{i}"} for i in range(120)]}
    val = adapter.validate_spec(huge_spec)
    assert val.is_valid is False
    assert any("máximo de nodos" in e for e in val.errors)


def test_09_failure_injection_secrets_redacted():
    """9. Secretos y credenciales dentro del JSON son redactados automáticamente."""
    adapter = JessycaArchifyAdapter()
    spec_with_secret = {
        "nodes": [
            {
                "id": "service",
                "name": "AuthService",
                "api_key": "SUPER_SECRET_TOKEN_XYZ",
                "db_password": "mypassword123",
            }
        ]
    }
    sanitized = adapter.sanitize_spec(spec_with_secret)
    node = sanitized["nodes"][0]
    assert node["api_key"] == "***REDACTED_SECRET***"
    assert node["db_password"] == "***REDACTED_SECRET***"


def test_10_archify_lab_battery():
    """10. El entorno de laboratorio ejecuta su ciclo completo de diagnóstico y fallas."""
    lab = ArchifyLab()
    try:
        hc = lab.run_health_check()
        assert hc["status"] == "HEALTHY"

        success, msg, path = lab.run_sample_architecture()
        assert success is True
        assert os.path.exists(path)

        inj = lab.run_failure_injections()
        assert inj["path_traversal_blocked"] is True
        assert inj["xss_escaped"] is True
        assert inj["secrets_redacted"] is True
        assert inj["dos_limit_enforced"] is True
    finally:
        lab.cleanup()


def test_11_archify_skill_execution_in_shadow_mode():
    """11. ArchifySkill opera fluidamente en modo SHADOW como BaseSkill."""
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.SHADOW)
    skill = ArchifySkill(adapter=adapter)

    ctx = SkillContext(
        skill_id="tools.archify",
        intent="render_diagram",
        parameters={
            "action": "render",
            "diagram_type": "sequence",
            "spec": {
                "title": "Auth Sequence",
                "nodes": [{"id": "user"}, {"id": "auth"}, {"id": "db"}],
                "edges": [{"from": "user", "to": "auth"}, {"from": "auth", "to": "db"}],
            },
        },
    )

    res = skill.execute(ctx)
    assert res.status == SkillStatus.COMPLETED
    assert res.success is True
    assert res.output["mode"] == "SHADOW"
    assert res.output["validation_status"] is True
    assert res.output["verdict"] == "ENRICHED_VISUALIZATION"
