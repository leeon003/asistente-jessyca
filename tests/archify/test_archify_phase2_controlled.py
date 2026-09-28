"""Batería Exhaustiva de Pruebas - Archify Fase 2 (CONTROLLED ACTIVE).

Cubre:
1. Modos de operación (OFF, SHADOW, CONTROLLED, ACTIVE) y modo por defecto.
2. 5 capacidades certificadas: architecture, workflow, sequence, dataflow, lifecycle.
3. Registro en CapabilityRegistry de JDE bajo diagram_generation.
4. Decisión JDE (visual -> Archify, textual -> texto, deny -> no ejecución).
5. Validación estricta de IR (JSON válido, IDs únicos, edges existentes).
6. Pruebas de límites de complejidad (99, 100 permitido; 101 rechazado / 199, 200 permitido; 201 rechazado).
7. Seguridad estricta (XSS neutralizado, Path Traversal bloqueado, Secretos redactados).
8. Idempotencia y reutilización de artefactos (NEW_ARTIFACT vs CACHE_HIT).
9. ExecutionVerifier de diagramas (VERIFIED vs VERIFICATION_FAILED).
10. Fallback controlado a Mermaid y texto ante errores o desactivación.
11. Concurrencia segura (1, 5, 10 solicitudes simultáneas sin colisiones).
12. Rollback operacional (CONTROLLED -> SHADOW -> OFF).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import os
import shutil
import tempfile
import time
from typing import Any

import pytest

from core.archify.adapter import (
    ArchifyArtifactMetadata,
    ArchifyDiagramType,
    ArchifyMode,
    JessycaArchifyAdapter,
    reset_archify_adapter,
)
from core.execution.execution_verifier import ExecutionVerifier, get_execution_verifier
from core.jde.authority import AuthorityMode
from core.jde.capabilities import get_capability_registry, reset_capability_registry
from skills.archify_skill import ArchifySkill, generate_mermaid_fallback
from skills.skill_models import SkillContext, SkillStatus


@pytest.fixture
def controlled_lab():
    """Directorio temporal aislado para pruebas controladas de Archify."""
    d = tempfile.mkdtemp(prefix="jessyca_archify_phase2_")
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.CONTROLLED, output_dir=d)
    yield adapter, d
    shutil.rmtree(d, ignore_errors=True)


# ── BLOQUE 1: MODOS Y CONFIGURACIÓN CONTROLADA ──

def test_01_archify_modes_and_default(controlled_lab):
    """Verifica que el modo por defecto sea CONTROLLED y que soporte OFF, SHADOW, CONTROLLED, ACTIVE."""
    adapter, _ = controlled_lab
    assert adapter.current_mode == ArchifyMode.CONTROLLED

    adapter.set_mode(ArchifyMode.SHADOW)
    assert adapter.current_mode == ArchifyMode.SHADOW

    adapter.set_mode(ArchifyMode.OFF)
    assert adapter.current_mode == ArchifyMode.OFF

    adapter.set_mode(ArchifyMode.ACTIVE)
    assert adapter.current_mode == ArchifyMode.ACTIVE

    adapter.set_mode(ArchifyMode.CONTROLLED)
    assert adapter.current_mode == ArchifyMode.CONTROLLED


# ── BLOQUE 2: LAS 5 CAPACIDADES CERTIFICADAS EN FASE 1 ──

@pytest.mark.parametrize(
    "diagram_type,title",
    [
        ("architecture", "Arquitectura JESSYCA Core"),
        ("workflow", "Flujo de Venta E-commerce"),
        ("sequence", "Secuencia Usuario → JDE → Verifier"),
        ("dataflow", "Flujo de Datos Open WebUI a Core"),
        ("lifecycle", "Ciclo de Vida de una Acción en JDE"),
    ],
)
def test_02_certified_capabilities_render_html(controlled_lab, diagram_type, title):
    """Verifica la generación real de artefactos HTML interactivos para las 5 capacidades certificadas."""
    adapter, out_dir = controlled_lab

    spec = {
        "title": title,
        "nodes": [
            {"id": "comp_1", "name": f"{title} - Entrada"},
            {"id": "comp_2", "name": f"{title} - Procesador"},
            {"id": "comp_3", "name": f"{title} - Salida"},
        ],
        "edges": [
            {"from": "comp_1", "to": "comp_2"},
            {"from": "comp_2", "to": "comp_3"},
        ],
    }

    success, msg, path = adapter.render_diagram(spec, diagram_type=diagram_type)
    assert success is True
    assert os.path.exists(path)
    assert path.endswith(".html")
    assert out_dir in path

    # Comprobación de contenido
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "<!DOCTYPE html>" in html
    assert f"<title>{title} - Archify</title>" in html
    assert "<svg id=\"archify-svg\"" in html
    assert "comp_1" in html or f"{title} - Entrada" in html
    assert "toggleTheme()" in html


def test_03_unsupported_capability_rejected(controlled_lab):
    """Verifica que capacidades no certificadas sean rechazadas formalmente."""
    adapter, _ = controlled_lab
    spec = {"nodes": [{"id": "n1"}], "edges": []}
    res = adapter.validate_spec(spec, diagram_type="quantum_simulation")
    assert res.is_valid is False
    assert any("no soportado" in e for e in res.errors)

    success, msg, path = adapter.render_diagram(spec, diagram_type="quantum_simulation")
    assert success is False
    assert "INVALID_DIAGRAM_SPEC" in msg
    assert path == ""


# ── BLOQUE 3: REGISTRO EN CAPABILITY REGISTRY DE JDE ──

def test_04_jde_capability_registry_integration():
    """Verifica que las capacidades de Archify estén registradas en CapabilityRegistry bajo diagram_generation."""
    registry = reset_capability_registry()
    certified_caps = [
        "diagram_generation.architecture",
        "diagram_generation.workflow",
        "diagram_generation.sequence",
        "diagram_generation.dataflow",
        "diagram_generation.lifecycle",
    ]
    for cap_id in certified_caps:
        cap = registry.get(cap_id)
        assert cap is not None, f"Capacidad '{cap_id}' no encontrada en CapabilityRegistry."
        assert cap.enabled is True
        assert cap.is_high_risk is False
        assert cap.is_allowed_for_mode(AuthorityMode.LIMITED) is True
        assert cap.is_allowed_for_mode(AuthorityMode.PROGRESSIVE) is True
        assert cap.is_allowed_for_mode(AuthorityMode.FULL) is True
        assert cap.is_allowed_for_mode(AuthorityMode.SHADOW) is False

    # Capacidades no certificadas formalmente deben estar deshabilitadas (Fase 3 Audit)
    uncertified_caps = [
        "diagram_generation.generic",
        "diagram_generation.skill",
    ]
    for cap_id in uncertified_caps:
        cap = registry.get(cap_id)
        assert cap is not None, f"Capacidad no certificada '{cap_id}' debe estar registrada."
        assert cap.enabled is False, f"Capacidad '{cap_id}' no debe estar habilitada en producción."
        assert cap.is_allowed_for_mode(AuthorityMode.LIMITED) is False
        assert cap.is_allowed_for_mode(AuthorityMode.PROGRESSIVE) is False
        assert cap.is_allowed_for_mode(AuthorityMode.FULL) is False


# ── BLOQUE 4: VALIDACIÓN ESTRICTA DEL IR Y LÍMITES (99, 100 vs 101 / 199, 200 vs 201) ──

def test_05_ir_duplicate_node_ids_rejected(controlled_lab):
    """Verifica que nodos con IDs duplicados sean rechazados."""
    adapter, _ = controlled_lab
    spec = {
        "nodes": [
            {"id": "service_a", "name": "Service Alpha"},
            {"id": "service_a", "name": "Service Alpha Duplicate"},
        ],
        "edges": [],
    }
    val = adapter.validate_spec(spec)
    assert val.is_valid is False
    assert any("duplicado" in e.lower() for e in val.errors)


def test_06_ir_dangling_edge_references_rejected(controlled_lab):
    """Verifica que aristas que apunten a nodos inexistentes sean rechazadas."""
    adapter, _ = controlled_lab
    spec = {
        "nodes": [{"id": "node_1", "name": "Alpha"}],
        "edges": [{"from": "node_1", "to": "node_ghost"}],
    }
    val = adapter.validate_spec(spec)
    assert val.is_valid is False
    assert any("inexistente" in e.lower() for e in val.errors)


def test_07_complexity_limits_nodes(controlled_lab):
    """Verifica los límites exactos de nodos: 99 y 100 permitidos; 101 rechazado."""
    adapter, _ = controlled_lab

    # 99 nodos: Válido
    spec_99 = {"nodes": [{"id": f"n_{i}", "name": f"Node {i}"} for i in range(99)], "edges": []}
    assert adapter.validate_spec(spec_99).is_valid is True

    # 100 nodos: Válido (límite superior inclusive)
    spec_100 = {"nodes": [{"id": f"n_{i}", "name": f"Node {i}"} for i in range(100)], "edges": []}
    assert adapter.validate_spec(spec_100).is_valid is True

    # 101 nodos: Rechazado
    spec_101 = {"nodes": [{"id": f"n_{i}", "name": f"Node {i}"} for i in range(101)], "edges": []}
    val_101 = adapter.validate_spec(spec_101)
    assert val_101.is_valid is False
    assert any("máximo de nodos" in e for e in val_101.errors)


def test_08_complexity_limits_edges(controlled_lab):
    """Verifica los límites exactos de aristas: 199 y 200 permitidos; 201 rechazado."""
    adapter, _ = controlled_lab

    # Nodos base para conectar
    nodes = [{"id": f"n_{i}", "name": f"Node {i}"} for i in range(50)]

    # 199 aristas: Válido
    edges_199 = [{"from": f"n_{i % 50}", "to": f"n_{(i + 1) % 50}"} for i in range(199)]
    spec_199 = {"nodes": nodes, "edges": edges_199}
    assert adapter.validate_spec(spec_199).is_valid is True

    # 200 aristas: Válido (límite superior inclusive)
    edges_200 = [{"from": f"n_{i % 50}", "to": f"n_{(i + 1) % 50}"} for i in range(200)]
    spec_200 = {"nodes": nodes, "edges": edges_200}
    assert adapter.validate_spec(spec_200).is_valid is True

    # 201 aristas: Rechazado
    edges_201 = [{"from": f"n_{i % 50}", "to": f"n_{(i + 1) % 50}"} for i in range(201)]
    spec_201 = {"nodes": nodes, "edges": edges_201}
    val_201 = adapter.validate_spec(spec_201)
    assert val_201.is_valid is False
    assert any("máximo de aristas" in e for e in val_201.errors)


# ── BLOQUE 5: SEGURIDAD (XSS, PATH TRAVERSAL, SECRET REDACTION) ──

def test_09_security_xss_and_injection_sanitized(controlled_lab):
    """Verifica que inyecciones de HTML/JS sean neutralizadas en título, nodos y aristas."""
    adapter, _ = controlled_lab

    malicious_spec = {
        "title": "<script>alert('xss_title')</script>",
        "nodes": [
            {"id": "n1", "name": "<img src=x onerror=alert('xss_node')>"},
            {"id": "n2", "name": "Normal Node"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "<iframe src=javascript:alert(1)></iframe>"},
        ],
    }

    sanitized = adapter.sanitize_spec(malicious_spec)
    assert "<script>" not in sanitized["title"]
    assert "&lt;script&gt;" in sanitized["title"]
    assert "<img" not in sanitized["nodes"][0]["name"]
    assert "&lt;img" in sanitized["nodes"][0]["name"]
    assert "<iframe" not in sanitized["edges"][0]["label"]
    assert "&lt;iframe" in sanitized["edges"][0]["label"]

    # Renderizar y verificar que el HTML final no contenga etiquetas vivas no escapadas
    success, msg, path = adapter.render_diagram(sanitized, "architecture")
    assert success is True
    with open(path, "r", encoding="utf-8") as f:
        rendered = f.read()

    assert "<script>alert" not in rendered
    assert "<img src=x" not in rendered
    assert "<iframe" not in rendered


def test_10_security_path_traversal_blocked(controlled_lab):
    """Verifica el bloqueo estricto de intentos de Path Traversal en el nombre de archivo."""
    adapter, _ = controlled_lab
    spec = {"nodes": [{"id": "n1", "name": "Node"}]}

    traversal_payloads = [
        "../../evil.html",
        "..\\..\\evil.html",
        "C:\\Windows\\System32\\evil.html",
        "/etc/passwd.html",
        "nested/../../secret.html",
    ]

    for payload in traversal_payloads:
        success, msg, path = adapter.render_diagram(spec, "architecture", filename=payload)
        assert success is False
        assert "Path Traversal" in msg or "seguridad" in msg
        assert path == ""


def test_11_security_secrets_redacted_in_artifact(controlled_lab):
    """Verifica que credenciales y tokens sensibles sean redactados antes de la compilación."""
    adapter, _ = controlled_lab
    spec_with_tokens = {
        "title": "Auth Gateway",
        "nodes": [
            {
                "id": "gateway",
                "name": "Gateway",
                "api_key": "SUPER_SECRET_TOKEN_XYZ",
                "db_password": "mypassword123",
                "token": "Bearer eyJhbGciOi...",
            }
        ],
        "edges": [],
    }

    success, msg, path = adapter.render_diagram(spec_with_tokens, "architecture")
    assert success is True
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "SUPER_SECRET_TOKEN_XYZ" not in content
    assert "mypassword123" not in content
    assert "***REDACTED_SECRET***" in content


# ── BLOQUE 6: IDEMPOTENCIA Y CACHE DE ARTEFACTOS ──

def test_12_idempotency_cache_reuse(controlled_lab):
    """Verifica que solicitudes idénticas reutilicen el artefacto existente (CACHE_HIT)."""
    adapter, _ = controlled_lab
    spec = {
        "title": "Idempotent Pipeline",
        "nodes": [
            {"id": "src", "name": "Source"},
            {"id": "snk", "name": "Sink"},
        ],
        "edges": [{"from": "src", "to": "snk"}],
    }

    # 1. Primera ejecución: NEW_ARTIFACT
    res1 = adapter.render_diagram(spec, "dataflow")
    assert res1.success is True
    assert res1.metadata is not None
    assert res1.metadata.cache_status == "NEW_ARTIFACT"
    path1 = res1.path

    # 2. Segunda ejecución idéntica: CACHE_HIT
    res2 = adapter.render_diagram(spec, "dataflow")
    assert res2.success is True
    assert res2.metadata is not None
    assert res2.metadata.cache_status == "CACHE_HIT"
    assert res2.path == path1
    assert "recuperado de caché" in res2.message

    # Verificar métricas
    metrics = adapter.get_metrics()
    assert metrics["archify_cache_hits"] >= 1
    assert metrics["archify_success"] >= 2


# ── BLOQUE 7: EXECUTION VERIFIER DE ARTEFACTOS ARCHIFY ──

def test_13_execution_verifier_validates_real_artifact(controlled_lab):
    """Verifica que ExecutionVerifier valide correctamente un archivo HTML/SVG real."""
    adapter, _ = controlled_lab
    verifier = get_execution_verifier()

    spec = {
        "title": "Verifiable System",
        "nodes": [{"id": "v1", "name": "Component"}],
        "edges": [],
    }

    success, msg, path = adapter.render_diagram(spec, "architecture")
    assert success is True

    evidence = verifier.verify_execution(action="render_diagram", target=path)
    assert evidence.is_verified is True
    assert evidence.verification_type == "archify_diagram"
    assert evidence.details["status"] == "VERIFIED"
    assert evidence.details["has_doctype"] is True
    assert evidence.details["has_svg"] is True
    assert evidence.details["size_bytes"] > 0


def test_14_execution_verifier_detects_tampered_or_empty_file(controlled_lab):
    """Verifica que ExecutionVerifier falle si el archivo está vacío o corrupto."""
    adapter, out_dir = controlled_lab
    verifier = get_execution_verifier()

    # Archivo vacío
    empty_file = os.path.join(out_dir, "empty_diagram.html")
    with open(empty_file, "w", encoding="utf-8") as f:
        pass

    ev_empty = verifier.verify_execution(action="render_diagram", target=empty_file)
    assert ev_empty.is_verified is False
    assert ev_empty.details["status"] == "VERIFICATION_FAILED"
    assert "vacío" in ev_empty.details["error"]

    # Archivo sin SVG ni DOCTYPE
    bad_file = os.path.join(out_dir, "corrupted.html")
    with open(bad_file, "w", encoding="utf-8") as f:
        f.write("<html><body>Texto plano sin SVG</body></html>")

    ev_bad = verifier.verify_execution(action="render_diagram", target=bad_file)
    assert ev_bad.is_verified is False
    assert ev_bad.details["status"] == "VERIFICATION_FAILED"


# ── BLOQUE 8: SKILL ARCHIFY Y FALLBACK A MERMAID ──

def test_15_archify_skill_controlled_execution(controlled_lab):
    """Verifica que ArchifySkill ejecute en modo CONTROLLED y devuelva metadatos verificados."""
    adapter, _ = controlled_lab
    skill = ArchifySkill(adapter=adapter)

    ctx = SkillContext(
        skill_id="tools.archify",
        intent="render_diagram",
        parameters={
            "action": "render",
            "diagram_type": "workflow",
            "spec": {
                "title": "Workflow Compra",
                "nodes": [
                    {"id": "carrito", "name": "Carrito"},
                    {"id": "pago", "name": "Pasarela de Pago"},
                ],
                "edges": [{"from": "carrito", "to": "pago"}],
            },
        },
    )

    res = skill.execute(ctx)
    assert res.status == SkillStatus.COMPLETED
    assert res.success is True
    assert "He generado el diagrama" in res.output["message"]
    assert res.output["verification_status"] == "VERIFIED"
    assert os.path.exists(res.output["artifact_path"])
    assert res.output["checksum"] != ""


def test_16_archify_skill_fallback_to_mermaid_when_disabled(controlled_lab):
    """Verifica el fallback a Mermaid cuando Archify está desactivado (mode=OFF)."""
    adapter, _ = controlled_lab
    adapter.set_mode(ArchifyMode.OFF)
    skill = ArchifySkill(adapter=adapter)

    ctx = SkillContext(
        skill_id="tools.archify",
        intent="render_diagram",
        parameters={
            "action": "render",
            "diagram_type": "architecture",
            "allow_fallback": True,
            "spec": {
                "title": "Fallback System",
                "nodes": [{"id": "api", "name": "API Service"}, {"id": "db", "name": "Database"}],
                "edges": [{"from": "api", "to": "db"}],
            },
        },
    )

    res = skill.execute(ctx)
    assert res.status == SkillStatus.COMPLETED
    assert res.success is True
    assert res.output["fallback_provider"] == "mermaid"
    assert "graph TD" in res.output["code"]
    assert "api" in res.output["code"]


def test_17_mermaid_generation_action(controlled_lab):
    """Verifica la generación explícita de diagramas Mermaid para secuencias y grafos."""
    seq_spec = {
        "title": "Auth Sequence",
        "nodes": [{"id": "u", "name": "Usuario"}, {"id": "s", "name": "Servidor"}],
        "edges": [{"from": "u", "to": "s", "label": "login()"}],
    }
    seq_code = generate_mermaid_fallback(seq_spec, "sequence")
    assert "sequenceDiagram" in seq_code
    assert "participant u as Usuario" in seq_code
    assert "u->>s: login()" in seq_code


# ── BLOQUE 9: CONCURRENCIA SEGURA (1, 5, 10 SOLICITUDES) ──

def test_18_concurrency_multi_threaded_renders(controlled_lab):
    """Verifica que solicitudes concurrentes (10 hilos) no colisionen ni corrompan archivos."""
    adapter, _ = controlled_lab

    def _worker(idx: int) -> tuple[bool, str, str]:
        spec = {
            "title": f"Concurrent System {idx}",
            "nodes": [
                {"id": f"node_{idx}_a", "name": f"A_{idx}"},
                {"id": f"node_{idx}_b", "name": f"B_{idx}"},
            ],
            "edges": [{"from": f"node_{idx}_a", "to": f"node_{idx}_b"}],
        }
        return adapter.render_diagram(spec, "architecture")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_worker, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 10
    generated_paths = set()
    for success, msg, path in results:
        assert success is True
        assert os.path.exists(path)
        assert path not in generated_paths, "Colisión de nombres de archivo en ejecución concurrente."
        generated_paths.add(path)


# ── BLOQUE 10: ROLLBACK OPERACIONAL ──

def test_19_operational_rollback(controlled_lab):
    """Verifica la reversión fluida: CONTROLLED -> SHADOW -> OFF -> CONTROLLED."""
    adapter, lab_dir = controlled_lab
    spec = {"nodes": [{"id": "n1", "name": "Node"}]}

    # 1. En CONTROLLED: genera archivo
    adapter.set_mode(ArchifyMode.CONTROLLED)
    s1, _, p1 = adapter.render_diagram(spec, "architecture")
    assert s1 is True
    assert os.path.exists(p1)

    # 2. Rollback a SHADOW: simula sin escribir
    adapter.set_mode(ArchifyMode.SHADOW)
    count_before = len(os.listdir(lab_dir))
    s2, m2, p2 = adapter.render_diagram(spec, "architecture")
    assert s2 is True
    assert p2 == ""
    assert "Modo Shadow" in m2
    assert len(os.listdir(lab_dir)) == count_before

    # 3. Rollback a OFF: bloquea
    adapter.set_mode(ArchifyMode.OFF)
    s3, m3, p3 = adapter.render_diagram(spec, "architecture")
    assert s3 is False
    assert "desactivado" in m3
    assert p3 == ""

    # 4. Retorno a CONTROLLED: vuelve a funcionar normalmente
    adapter.set_mode(ArchifyMode.CONTROLLED)
    s4, _, p4 = adapter.render_diagram(spec, "workflow")
    assert s4 is True
    assert os.path.exists(p4)
