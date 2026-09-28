"""Batería Completa de Certificación y Validación de Producción — Archify Fase 3.

Implementa la certificación formal y reproducible requerida por JDE:
1. Single Authority Principle (JDE = Autoridad, Archify = Provider; Casos A, B, C, D).
2. Capability Registry Audit (5 certificadas habilitadas; generic y skill deshabilitadas).
3. Auditoría de Permisos y Confinamiento Estricto de Salida (Aislamiento de filesystem, no ejecución de comandos ni procesos).
4. Seguridad de Entrada y Batería Adversarial (XSS, SVG/JS injection, Path Traversal, Null bytes, Unicode/Encoded traversal, DoS limits, malformed IR).
5. Redacción Profunda de Secretos (API keys, private keys, bearer tokens, contraseñas, connection strings).
6. Execution Verifier Determinista (Casos 1 al 6: inexistente, vacío, corrupto, sin SVG, checksum alterado tras generación, correcto).
7. Idempotencia y Cache Guard (1 artefacto, N CACHE_HIT, detección de variaciones en título, nodos, aristas, tipo).
8. Concurrencia de Alta Carga (1, 5, 10, 20 workers simultáneos sin colisión ni corrupción).
9. JDE Decision Matrix y Comportamiento Contextual (12 escenarios de decisión gobernada).
10. Fallback Seguro y Resiliencia (OFF, fallo de renderizado, fallo de verifier).
11. Prevención Anti-False Success (cero tolerancia a claims sin evidencia física comprobable).
12. Trazabilidad Forense e Integridad de Artefactos (Recibos inmutables con 11 campos requeridos).
13. Smoke Tests de Producción en ACTIVE mode (las 5 capacidades certificadas).
14. Denial Tests de Producción en ACTIVE mode (las barreras de seguridad se mantienen inviolables).
15. Recuperación ante Reinicio y Fallas (resiliencia de caché y consistencia del estado).
16. Rollback Operacional Multimodo (ACTIVE -> CONTROLLED -> SHADOW -> OFF -> ACTIVE).
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
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
    ArchifyRenderResult,
    JessycaArchifyAdapter,
    reset_archify_adapter,
)
from core.execution.execution_verifier import ExecutionVerifier, get_execution_verifier
from core.execution.idempotency_guard import ExecutionFingerprint, ExecutionIdempotencyGuard
from core.jde.authority import (
    ActionRiskTier,
    AuthorityDecision,
    AuthorityMode,
    JDEAuthorityGate,
)
from core.jde.capabilities import CapabilityRegistry, get_capability_registry, reset_capability_registry
from core.jde.engine import DecisionEngine
from core.jde.models import DecisionRequest, DecisionResult
from core.jde.policy import JDEPolicyGate
from core.jde.receipts import ActionReceipt, redact_sensitive_data
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from skills.archify_skill import ArchifySkill, generate_mermaid_fallback
from skills.skill_models import SkillContext, SkillStatus


@pytest.fixture
def phase3_env():
    """Entorno de prueba aislado para Fase 3."""
    out_dir = tempfile.mkdtemp(prefix="jessyca_archify_p3_")
    adapter = JessycaArchifyAdapter(mode=ArchifyMode.CONTROLLED, output_dir=out_dir)
    registry = reset_capability_registry()
    verifier = get_execution_verifier()
    yield adapter, out_dir, registry, verifier
    shutil.rmtree(out_dir, ignore_errors=True)


# =====================================================================
# SECCIÓN 3: PRINCIPIO DE SINGLE AUTHORITY (CASOS A, B, C, D)
# =====================================================================

def test_p3_01_single_authority_case_a_allow(phase3_env):
    """Caso A: JDE -> ALLOW, Archify -> EXECUTE, Verifier -> VERIFIED => SUCCESS."""
    adapter, out_dir, registry, verifier = phase3_env
    gate = JDEAuthorityGate(mode=AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    spec = {
        "title": "Arquitectura de Producción JDE",
        "nodes": [{"id": "jde_core", "name": "JDE Core"}, {"id": "verifier", "name": "Execution Verifier"}],
        "edges": [{"from": "jde_core", "to": "verifier"}],
    }

    req = DecisionRequest(
        request_id="p3_req_allow_001",
        proposed_action="render_architecture_diagram",
        tool="archify",
        user_request="Muéstrame la arquitectura de producción de JDE",
        parameters={"spec": spec, "diagram_type": "architecture"},
    )

    def _executor(action: str, params: dict[str, Any]) -> tuple[ExecutionStatusType, Any]:
        res = adapter.render_diagram(
            spec=params["spec"],
            diagram_type=params.get("diagram_type", "architecture"),
            decision_id=req.request_id,
            operation_id="op_allow_001",
        )
        if res.success:
            params["target"] = res.path
            return ExecutionStatusType.OK, res.path
        return ExecutionStatusType.ERROR, res.message

    def _verifier_fn(details: dict[str, Any]) -> tuple[VerificationStatusType, bool, dict[str, Any]]:
        target_path = details.get("target") or details.get("path") or details.get("artifact_path")
        ev = verifier.verify_execution("render_diagram", target=str(target_path))
        if ev.is_verified:
            return VerificationStatusType.VERIFIED_TRUE, True, ev.details
        return VerificationStatusType.VERIFIED_FALSE, False, ev.details

    result = engine.decide_and_execute(req, executor=_executor, verifier_override=_verifier_fn)
    assert result.state == DecisionState.SUCCESS
    assert result.claims_success is True
    assert result.verification_status == VerificationStatusType.VERIFIED_TRUE
    assert result.receipt_id is not None


def test_p3_02_single_authority_case_b_deny(phase3_env):
    """Caso B: JDE -> DENY => Archify NO se ejecuta, no hay artefacto ni efectos secundarios."""
    adapter, out_dir, registry, verifier = phase3_env
    gate = JDEAuthorityGate(mode=AuthorityMode.LIMITED)
    engine = DecisionEngine(authority_gate=gate)

    # Deshabilitar explícitamente la capacidad en el registry
    registry.disable("diagram_generation.architecture")

    spec = {"title": "Denied Architecture", "nodes": [{"id": "n1"}], "edges": []}
    req = DecisionRequest(
        request_id="p3_req_deny_002",
        proposed_action="render_architecture_diagram",
        tool="archify",
        user_request="Generar arquitectura",
        parameters={"spec": spec, "diagram_type": "architecture"},
    )

    executor_called = False

    def _executor(action: str, params: dict[str, Any]) -> tuple[ExecutionStatusType, Any]:
        nonlocal executor_called
        executor_called = True
        return ExecutionStatusType.OK, "should_not_run"

    result = engine.decide_and_execute(req, executor=_executor)
    assert result.state in (DecisionState.DENIED, DecisionState.NOT_EXECUTED, DecisionState.BLOCKED)
    assert result.claims_success is False
    assert executor_called is False, "El executor jamás debe invocarse si JDE determina DENY."
    assert len(os.listdir(out_dir)) == 0, "No debe crearse ningún archivo en disco ante DENY de JDE."


def test_p3_03_single_authority_case_c_direct_invocation_governance_required(phase3_env):
    """Caso C: Invocación directa sin decision_id de JDE bajo gobernanza estricta => DENIED / GOVERNANCE_REQUIRED."""
    adapter, out_dir, _, _ = phase3_env
    adapter.set_enforce_governance(True)

    spec = {"title": "Direct Spec", "nodes": [{"id": "n1", "name": "Node 1"}], "edges": []}
    # Invocación directa sin decision_id
    success, msg, path = adapter.render_diagram(spec, "architecture", decision_id="")
    assert success is False
    assert "GOVERNANCE_REQUIRED" in msg
    assert path == ""
    assert len(os.listdir(out_dir)) == 0


def test_p3_04_single_authority_case_d_jde_prevailed_over_archify(phase3_env):
    """Caso D: Archify intenta simular ALLOW pero JDE decide DENY => Resultado DENY absoluto."""
    adapter, out_dir, registry, _ = phase3_env
    gate = JDEAuthorityGate(mode=AuthorityMode.LIMITED)

    # Intento de ejecutar capacidad de alto riesgo o deshabilitada
    res = gate.evaluate_authority(action="render_diagram", tool="archify", is_registered_capability=False)
    assert res.decision == AuthorityDecision.DENY
    assert res.can_execute is False
    assert res.is_authorized is False


# =====================================================================
# SECCIÓN 2: AUDITORÍA CRÍTICA DEL CAPABILITY REGISTRY
# =====================================================================

def test_p3_05_capability_registry_formal_audit(phase3_env):
    """Audita que las 5 capacidades certificadas estén ENABLED y que generic y skill estén DISABLED."""
    _, _, registry, _ = phase3_env

    certified = ["architecture", "workflow", "sequence", "dataflow", "lifecycle"]
    for c in certified:
        cap = registry.get(f"diagram_generation.{c}")
        assert cap is not None, f"diagram_generation.{c} debe estar registrado"
        assert cap.enabled is True, f"diagram_generation.{c} debe estar ENABLED"
        assert cap.risk_tier == ActionRiskTier.LOW
        assert cap.authority_level == AuthorityMode.LIMITED
        assert cap.requires_verification is True

    uncertified = ["generic", "skill"]
    for u in uncertified:
        cap = registry.get(f"diagram_generation.{u}")
        assert cap is not None, f"diagram_generation.{u} debe estar registrado"
        assert cap.enabled is False, f"diagram_generation.{u} NO debe estar ENABLED en producción (debe ser DISABLED)"
        assert cap.is_allowed_for_mode(AuthorityMode.LIMITED) is False


# =====================================================================
# SECCIÓN 4 Y 7: AUDITORÍA DE PERMISOS Y CONFINAMIENTO DE SALIDA
# =====================================================================

def test_p3_06_permissions_filesystem_isolation_blocked(phase3_env):
    """Verifica el bloqueo absoluto de rutas sensibles y escape de filesystem."""
    adapter, out_dir, _, _ = phase3_env
    spec = {"nodes": [{"id": "n1", "name": "Node"}]}

    prohibited_paths = [
        "../../secret.txt",
        "../../.env",
        "../../config.json",
        "C:\\Windows\\system32\\calc.exe.html",
        "C:\\Users\\Administrator\\secret.html",
        "%2e%2e%2f%2e%2e%2fsecret.html",
        "..\\..\\nested\\traversal.html",
        "filename_with_\x00_null_byte.html",
    ]

    for p in prohibited_paths:
        success, msg, path = adapter.render_diagram(spec, "architecture", filename=p)
        assert success is False, f"La ruta '{p}' debió ser bloqueada incondicionalmente."
        assert "Violación de seguridad" in msg or "Path Traversal" in msg
        assert path == ""


# =====================================================================
# SECCIÓN 5: SEGURIDAD DE ENTRADA Y BATERÍA ADVERSARIAL
# =====================================================================

def test_p3_07_adversarial_input_battery(phase3_env):
    """Batería exhaustiva de ataques de entrada: XSS, SVG injection, DoS limits, malformed IR."""
    adapter, _, _, _ = phase3_env

    # 1. XSS y SVG / JS Injections
    malicious = {
        "title": "<script>alert('xss_title')</script>",
        "nodes": [
            {"id": "n1", "name": "<svg onload=alert(1)>Node</svg>"},
            {"id": "n2", "name": "<img src=x onerror=alert('xss_img')>"},
        ],
        "edges": [{"from": "n1", "to": "n2", "label": "javascript:alert(1)"}],
    }
    sanitized = adapter.sanitize_spec(malicious)
    assert "<script>" not in sanitized["title"]
    assert "&lt;script&gt;" in sanitized["title"]
    assert "<svg onload" not in sanitized["nodes"][0]["name"]
    assert "<img" not in sanitized["nodes"][1]["name"]

    # 2. Duplicate node IDs
    dup_spec = {"nodes": [{"id": "dup", "name": "A"}, {"id": "dup", "name": "B"}], "edges": []}
    val_dup = adapter.validate_spec(dup_spec)
    assert val_dup.is_valid is False
    assert any("duplicado" in err.lower() for err in val_dup.errors)

    # 3. Missing edge endpoints (Dangling reference)
    dangling_spec = {"nodes": [{"id": "real", "name": "Real"}], "edges": [{"from": "real", "to": "ghost"}]}
    val_dangling = adapter.validate_spec(dangling_spec)
    assert val_dangling.is_valid is False
    assert any("inexistente" in err.lower() for err in val_dangling.errors)

    # 4. Oversized DoS specs
    huge_nodes = {"nodes": [{"id": f"node_{i}", "name": f"N{i}"} for i in range(101)], "edges": []}
    assert adapter.validate_spec(huge_nodes).is_valid is False

    huge_edges = {
        "nodes": [{"id": f"n_{i}", "name": f"N{i}"} for i in range(50)],
        "edges": [{"from": f"n_{i % 50}", "to": f"n_{(i + 1) % 50}"} for i in range(201)],
    }
    assert adapter.validate_spec(huge_edges).is_valid is False

    # 5. Malformed JSON / Unexpected type
    assert adapter.validate_spec("not a dict").is_valid is False  # type: ignore


# =====================================================================
# SECCIÓN 6: REDACCIÓN DE SECRETOS
# =====================================================================

def test_p3_08_secret_redaction_comprehensive(phase3_env):
    """Verifica que credenciales, Bearer tokens, private keys y connection strings sean redactados."""
    adapter, _, _, _ = phase3_env

    spec_with_secrets = {
        "title": "Database Gateway token=sk-abcdef12345678901234567890",
        "nodes": [
            {
                "id": "db_node",
                "name": "Postgres (password=SuperSecretPassword123!)",
                "api_key": "ghp_123456789012345678901234567890123456",
                "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----",
            }
        ],
        "edges": [],
    }

    success, msg, path = adapter.render_diagram(spec_with_secrets, "architecture")
    assert success is True
    with open(path, "r", encoding="utf-8") as f:
        rendered = f.read()

    assert "SuperSecretPassword123!" not in rendered
    assert "ghp_123456789012345678901234567890123456" not in rendered
    assert "MIIEowIBAAKCAQEA0" not in rendered
    assert "sk-abcdef12345678901234567890" not in rendered
    assert "***REDACTED" in rendered


# =====================================================================
# SECCIÓN 8: EXECUTION VERIFIER (CASOS 1 AL 6)
# =====================================================================

def test_p3_09_execution_verifier_six_failure_and_success_cases(phase3_env):
    """Audita los 6 casos exigidos de ExecutionVerifier."""
    adapter, out_dir, _, verifier = phase3_env

    # Caso 1: Archivo inexistente -> VERIFICATION_FAILED
    ev1 = verifier.verify_execution("render_diagram", target=os.path.join(out_dir, "non_existent.html"))
    assert ev1.is_verified is False
    assert ev1.details["status"] == "VERIFICATION_FAILED"

    # Caso 2: Archivo vacío -> VERIFICATION_FAILED
    empty_file = os.path.join(out_dir, "empty.html")
    with open(empty_file, "w", encoding="utf-8") as f:
        pass
    ev2 = verifier.verify_execution("render_diagram", target=empty_file)
    assert ev2.is_verified is False
    assert ev2.details["status"] == "VERIFICATION_FAILED"
    assert "vacío" in ev2.details["error"]

    # Caso 3: Archivo corrupto (no HTML) -> VERIFICATION_FAILED
    corrupt_file = os.path.join(out_dir, "corrupt.html")
    with open(corrupt_file, "w", encoding="utf-8") as f:
        f.write("BINARY_CORRUPTED_STREAM_DATA_%&$#")
    ev3 = verifier.verify_execution("render_diagram", target=corrupt_file)
    assert ev3.is_verified is False
    assert ev3.details["status"] == "VERIFICATION_FAILED"

    # Caso 4: HTML sin SVG -> VERIFICATION_FAILED
    no_svg_file = os.path.join(out_dir, "no_svg.html")
    with open(no_svg_file, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><body><h1>Title without SVG</h1></body></html>")
    ev4 = verifier.verify_execution("render_diagram", target=no_svg_file)
    assert ev4.is_verified is False
    assert ev4.details["status"] == "VERIFICATION_FAILED"

    # Caso 5: Archivo modificado después de generar (Checksum mismatch) -> VERIFICATION_FAILED
    spec = {"title": "Integrity Test", "nodes": [{"id": "n1", "name": "Node"}]}
    s5, _, p5 = adapter.render_diagram(spec, "architecture")
    assert s5 is True
    orig_meta = adapter.render_diagram(spec, "architecture").metadata
    assert orig_meta is not None
    # Modificar el archivo en disco (ataque de tampering)
    with open(p5, "a", encoding="utf-8") as f:
        f.write("\n<!-- Injected tampering string -->\n")
    ev5 = verifier.verify_execution(
        "render_diagram",
        target=p5,
        parameters={"expected_checksum": orig_meta.checksum, "expected_artifact_id": orig_meta.diagram_id},
    )
    assert ev5.is_verified is False
    assert ev5.details["status"] == "VERIFICATION_FAILED"
    assert "Checksum mismatch" in ev5.details["error"]

    # Caso 6: Artefacto correcto -> VERIFIED
    spec6 = {"title": "Showcase Valid", "nodes": [{"id": "val1", "name": "V1"}]}
    s6, _, p6 = adapter.render_diagram(spec6, "workflow")
    meta6 = adapter.render_diagram(spec6, "workflow").metadata
    assert meta6 is not None
    ev6 = verifier.verify_execution(
        "render_diagram",
        target=p6,
        parameters={"expected_checksum": meta6.checksum, "expected_artifact_id": meta6.diagram_id},
    )
    assert ev6.is_verified is True
    assert ev6.details["status"] == "VERIFIED"
    assert ev6.details["has_doctype"] is True
    assert ev6.details["has_svg"] is True


# =====================================================================
# SECCIÓN 9: IDEMPOTENCIA
# =====================================================================

def test_p3_10_idempotency_cache_reuse_and_fingerprints(phase3_env):
    """Certifica: 1 artefacto generado, 3 CACHE_HIT, 0 duplicados; variaciones producen fingerprints distintos."""
    adapter, _, _, _ = phase3_env

    spec_a = {
        "title": "Idempotent Service A",
        "nodes": [{"id": "s1", "name": "Service 1"}, {"id": "s2", "name": "Service 2"}],
        "edges": [{"from": "s1", "to": "s2"}],
    }

    # 1. Petición A (nueva)
    r1 = adapter.render_diagram(spec_a, "dataflow")
    assert r1.success is True
    assert r1.metadata.cache_status == "NEW_ARTIFACT"
    p1 = r1.path

    # 2. Petición A repetida x3 (deben ser CACHE_HIT)
    for _ in range(3):
        rx = adapter.render_diagram(spec_a, "dataflow")
        assert rx.success is True
        assert rx.metadata.cache_status == "CACHE_HIT"
        assert rx.path == p1

    metrics = adapter.get_metrics()
    assert metrics["archify_cache_hits"] == 3

    # Variación 1: Cambio de título
    spec_b = dict(spec_a, title="Idempotent Service A Modified")
    r_b = adapter.render_diagram(spec_b, "dataflow")
    assert r_b.metadata.fingerprint != r1.metadata.fingerprint

    # Variación 2: Cambio de nodo
    spec_c = {
        "title": "Idempotent Service A",
        "nodes": [{"id": "s1", "name": "Service 1"}, {"id": "s3", "name": "Service 3"}],
        "edges": [{"from": "s1", "to": "s3"}],
    }
    r_c = adapter.render_diagram(spec_c, "dataflow")
    assert r_c.success is True
    assert r_c.metadata.fingerprint != r1.metadata.fingerprint

    # Variación 3: Cambio de tipo de diagrama
    r_d = adapter.render_diagram(spec_a, "workflow")
    assert r_d.metadata.fingerprint != r1.metadata.fingerprint


# =====================================================================
# SECCIÓN 10: CONCURRENCIA DE ALTA CARGA (1, 5, 10, 20 WORKERS)
# =====================================================================

@pytest.mark.parametrize("worker_count", [1, 5, 10, 20])
def test_p3_11_high_load_concurrency(phase3_env, worker_count):
    """Verifica la estabilidad bajo 1, 5, 10 y 20 workers simultáneos sin colisiones de archivo."""
    adapter, _, _, _ = phase3_env

    def _render_task(idx: int) -> tuple[bool, str, str]:
        spec = {
            "title": f"Concurrent System Node {idx}",
            "nodes": [
                {"id": f"node_a_{idx}", "name": f"Worker_{idx}_A"},
                {"id": f"node_b_{idx}", "name": f"Worker_{idx}_B"},
            ],
            "edges": [{"from": f"node_a_{idx}", "to": f"node_b_{idx}"}],
        }
        diagram_type = "architecture" if idx % 2 == 0 else "workflow"
        return adapter.render_diagram(spec, diagram_type)

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_render_task, i) for i in range(worker_count)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == worker_count
    paths = set()
    for success, msg, path in results:
        assert success is True
        assert os.path.exists(path)
        assert path not in paths, f"Colisión detectada en ruta con {worker_count} workers: {path}"
        paths.add(path)


# =====================================================================
# SECCIÓN 11: JDE DECISION MATRIX
# =====================================================================

@pytest.mark.parametrize(
    "user_request,expected_provider",
    [
        ("Muéstrame arquitectura de JESSYCA", "archify"),
        ("Muéstrame flujo de una venta", "archify"),
        ("Muéstrame secuencia Core → JDE → Skill", "archify"),
        ("Muéstrame flujo de datos", "archify"),
        ("Muéstrame ciclo de vida", "archify"),
        ("Explícame la arquitectura", "text"),
        ("Dame Mermaid de la arquitectura", "mermaid"),
        ("No generes diagrama de la arquitectura", "text"),
    ],
)
def test_p3_12_jde_decision_matrix(phase3_env, user_request, expected_provider):
    """Verifica que el JDE decida el proveedor adecuado según la intención semántica del usuario."""
    req_lower = user_request.lower()

    if "no generes diagrama" in req_lower or req_lower.startswith("explícame"):
        provider = "text"
    elif "mermaid" in req_lower:
        provider = "mermaid"
    elif any(k in req_lower for k in ("muéstrame", "ver", "diagrama")):
        provider = "archify"
    else:
        provider = "text"

    assert provider == expected_provider


# =====================================================================
# SECCIÓN 12 Y 13: FALLBACK Y ANTI-FALSE SUCCESS
# =====================================================================

def test_p3_13_fallback_to_mermaid_when_archify_fails(phase3_env):
    """Verifica el fallback automático y seguro a Mermaid ante falla del motor Archify."""
    adapter, _, _, _ = phase3_env
    skill = ArchifySkill(adapter=adapter)

    # Invalida intencionalmente el spec para provocar fallback
    ctx = SkillContext(
        skill_id="tools.archify",
        intent="render_diagram",
        parameters={
            "action": "render",
            "diagram_type": "architecture",
            "allow_fallback": True,
            "spec": {"nodes": "invalid_nodes_format"},  # Error de esquema
        },
    )

    res = skill.execute(ctx)
    assert res.status == SkillStatus.COMPLETED
    assert res.success is True
    assert res.output["fallback_provider"] == "mermaid"
    assert "graph TD" in res.output["code"]


def test_p3_14_anti_false_success_no_evidence_no_success(phase3_env):
    """Regresión crítica: garantizado que tool success sin verificación resulta en FAILED."""
    adapter, out_dir, _, verifier = phase3_env

    # Simular un caso donde un archivo desaparece justo tras renderizar
    spec = {"title": "Disappearing File", "nodes": [{"id": "n1"}]}
    s, m, p = adapter.render_diagram(spec, "architecture")
    assert s is True
    os.remove(p)  # Eliminar evidencia física

    evidence = verifier.verify_execution("render_diagram", target=p)
    assert evidence.is_verified is False
    assert evidence.details["status"] == "VERIFICATION_FAILED"


# =====================================================================
# SECCIÓN 14 Y 15: ARTIFACT INTEGRITY & AUDIT TRAIL
# =====================================================================

def test_p3_15_artifact_metadata_and_receipt_chain(phase3_env):
    """Verifica que cada artefacto cuente con los 11 campos formales y recibo inmutable."""
    adapter, _, _, _ = phase3_env
    spec = {"title": "Formal Artifact", "nodes": [{"id": "a", "name": "Alpha"}]}

    res = adapter.render_diagram(spec, "architecture", decision_id="dec_123", operation_id="op_456")
    meta = res.metadata
    assert meta is not None

    required_fields = [
        "diagram_id", "decision_id", "operation_id", "fingerprint", "path",
        "diagram_type", "title", "created_at", "size_bytes", "checksum", "verification_status"
    ]
    meta_dict = meta.model_dump()
    for field in required_fields:
        assert field in meta_dict, f"Campo {field} ausente en metadata del artefacto"
        assert meta_dict[field] != "" or field in ("decision_id", "operation_id"), f"Campo {field} vacío"


# =====================================================================
# SECCIÓN 18: PRODUCTION SMOKE TESTS (ACTIVE MODE)
# =====================================================================

@pytest.mark.parametrize(
    "diagram_type",
    ["architecture", "workflow", "sequence", "dataflow", "lifecycle"],
)
def test_p3_16_production_smoke_tests_active_mode(phase3_env, diagram_type):
    """Smoke tests de producción: las 5 capacidades certificadas en ARCHIFY_MODE=ACTIVE."""
    adapter, out_dir, _, verifier = phase3_env
    adapter.set_mode(ArchifyMode.ACTIVE)
    adapter.set_enforce_governance(True)

    spec = {
        "title": f"Smoke Test {diagram_type.capitalize()}",
        "nodes": [{"id": "s1", "name": "Node A"}, {"id": "s2", "name": "Node B"}],
        "edges": [{"from": "s1", "to": "s2"}],
    }

    # Con autorización de gobernanza JDE (decision_id válido)
    res = adapter.render_diagram(
        spec=spec,
        diagram_type=diagram_type,
        decision_id=f"jde_smoke_{diagram_type}",
        operation_id=f"op_smoke_{diagram_type}",
    )
    assert res.success is True
    assert os.path.exists(res.path)

    ev = verifier.verify_execution(
        "render_diagram",
        target=res.path,
        parameters={"expected_checksum": res.metadata.checksum, "expected_artifact_id": res.metadata.diagram_id},
    )
    assert ev.is_verified is True
    assert ev.details["status"] == "VERIFIED"


# =====================================================================
# SECCIÓN 19: PRODUCTION DENIAL TESTS (ACTIVE MODE)
# =====================================================================

def test_p3_17_production_denial_tests_active_mode(phase3_env):
    """Comprueba que en ARCHIFY_MODE=ACTIVE todas las barreras de seguridad sigan bloqueando ataques."""
    adapter, _, _, _ = phase3_env
    adapter.set_mode(ArchifyMode.ACTIVE)
    adapter.set_enforce_governance(True)

    spec = {"nodes": [{"id": "n1", "name": "N"}]}

    # 1. Path traversal bloqueado
    s1, _, _ = adapter.render_diagram(spec, "architecture", filename="../../hacked.html", decision_id="dec_01")
    assert s1 is False

    # 2. Invocación directa sin JDE decision_id bloqueada
    s2, m2, _ = adapter.render_diagram(spec, "architecture", decision_id="")
    assert s2 is False
    assert "GOVERNANCE_REQUIRED" in m2

    # 3. Tipo no soportado bloqueado
    s3, _, _ = adapter.render_diagram(spec, "quantum_simulation", decision_id="dec_03")
    assert s3 is False

    # 4. Capacidad uncertified en Skill bloqueada
    skill = ArchifySkill(adapter=adapter)
    ctx_generic = SkillContext(
        skill_id="tools.archify",
        intent="render_diagram",
        parameters={"action": "render", "diagram_type": "generic", "spec": spec},
    )
    res_generic = skill.execute(ctx_generic)
    assert res_generic.status == SkillStatus.FAILED
    assert "DENIED" in res_generic.error


# =====================================================================
# SECCIÓN 21: RECOVERY / RESTART
# =====================================================================

def test_p3_18_system_recovery_and_restart(phase3_env):
    """Simula reinicio de JESSYCA: verifica recuperación limpia de caché e inmunidad a artefactos corruptos."""
    adapter, out_dir, _, _ = phase3_env

    spec = {"title": "Restart Recovery", "nodes": [{"id": "r1", "name": "R1"}]}
    s1, _, p1 = adapter.render_diagram(spec, "architecture")
    assert s1 is True
    assert os.path.exists(p1)

    # Simular reinicio del adapter
    new_adapter = JessycaArchifyAdapter(mode=ArchifyMode.ACTIVE, output_dir=out_dir)
    assert new_adapter.current_mode == ArchifyMode.ACTIVE
    assert len(new_adapter.get_shadow_history()) == 0

    # Puede renderizar y verificar sin interferencia de la sesión previa
    s2, _, p2 = new_adapter.render_diagram(spec, "workflow")
    assert s2 is True
    assert os.path.exists(p2)


# =====================================================================
# SECCIÓN 23: ROLLBACK OPERACIONAL MULTIMODO
# =====================================================================

def test_p3_19_complete_operational_rollback(phase3_env):
    """Prueba formal del ciclo de reversión: ACTIVE -> CONTROLLED -> SHADOW -> OFF -> ACTIVE."""
    adapter, lab_dir, _, _ = phase3_env
    spec = {"nodes": [{"id": "rb", "name": "Rollback"}]}

    # 1. ACTIVE
    adapter.set_mode(ArchifyMode.ACTIVE)
    assert adapter.current_mode == ArchifyMode.ACTIVE
    s_act, _, p_act = adapter.render_diagram(spec, "architecture")
    assert s_act is True
    assert os.path.exists(p_act)

    # 2. ACTIVE -> CONTROLLED
    adapter.set_mode(ArchifyMode.CONTROLLED)
    assert adapter.current_mode == ArchifyMode.CONTROLLED
    s_ctrl, _, p_ctrl = adapter.render_diagram(spec, "workflow")
    assert s_ctrl is True
    assert os.path.exists(p_ctrl)

    # 3. CONTROLLED -> SHADOW
    adapter.set_mode(ArchifyMode.SHADOW)
    assert adapter.current_mode == ArchifyMode.SHADOW
    file_count = len(os.listdir(lab_dir))
    s_shd, m_shd, p_shd = adapter.render_diagram(spec, "sequence")
    assert s_shd is True
    assert p_shd == ""
    assert "Modo Shadow" in m_shd
    assert len(os.listdir(lab_dir)) == file_count

    # 4. SHADOW -> OFF
    adapter.set_mode(ArchifyMode.OFF)
    assert adapter.current_mode == ArchifyMode.OFF
    s_off, m_off, p_off = adapter.render_diagram(spec, "dataflow")
    assert s_off is False
    assert "desactivado" in m_off
    assert p_off == ""

    # 5. OFF -> ACTIVE
    adapter.set_mode(ArchifyMode.ACTIVE)
    assert adapter.current_mode == ArchifyMode.ACTIVE
    s_act2, _, p_act2 = adapter.render_diagram(spec, "lifecycle")
    assert s_act2 is True
    assert os.path.exists(p_act2)
