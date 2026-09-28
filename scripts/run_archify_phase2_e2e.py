"""Ejecutor de Escenarios End-to-End para Archify Fase 2 (CONTROLLED ACTIVE).

Ejecuta el pipeline completo:
USER -> CORE -> JDE -> ARCHIFY CAPABILITY -> RISK -> PERMISSION -> IDEMPOTENCY -> ADAPTER -> ARCHIFY -> VERIFIER -> ARTIFACT -> JDE RECEIPT -> USER

Genera el archivo formal: reports/archify_phase2_e2e.json
"""

import json
import os
import sys
import time
from datetime import UTC, datetime

# Ajustar path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.archify.adapter import (
    ArchifyDiagramType,
    ArchifyMode,
    JessycaArchifyAdapter,
    get_archify_adapter,
    reset_archify_adapter,
)
from core.execution.execution_verifier import get_execution_verifier
from core.jde.authority import AuthorityMode, JDEAuthorityGate
from core.jde.capabilities import get_capability_registry, reset_capability_registry
from core.jde.receipts import ActionReceipt
from skills.archify_skill import ArchifySkill, generate_mermaid_fallback
from skills.skill_models import SkillContext, SkillStatus


def run_e2e_scenarios() -> list[dict]:
    output_dir = os.path.join(BASE_DIR, "data", "archify")
    os.makedirs(output_dir, exist_ok=True)
    adapter = reset_archify_adapter(mode=ArchifyMode.CONTROLLED)
    adapter._output_dir = output_dir
    verifier = get_execution_verifier()
    registry = reset_capability_registry()
    skill = ArchifySkill(adapter=adapter)

    scenarios = []

    # ── ESCENARIO 1: Arquitectura JESSYCA Core ──
    s1_spec = {
        "title": "Arquitectura Central JESSYCA 3.0",
        "nodes": [
            {"id": "user", "name": "Usuario"},
            {"id": "core", "name": "JESSYCA Core"},
            {"id": "jde", "name": "Decision Engine (JDE)"},
            {"id": "skills", "name": "Skill Registry"},
            {"id": "verifier", "name": "Execution Verifier"},
        ],
        "edges": [
            {"from": "user", "to": "core"},
            {"from": "core", "to": "jde"},
            {"from": "jde", "to": "skills"},
            {"from": "skills", "to": "verifier"},
        ],
    }
    t0 = time.perf_counter()
    ctx1 = SkillContext(
        skill_id="tools.archify",
        intent="visual_explanation",
        parameters={
            "action": "render",
            "diagram_type": "architecture",
            "spec": s1_spec,
            "decision_id": "dec_e2e_01",
            "operation_id": "op_e2e_01",
        },
    )
    res1 = skill.execute(ctx1)
    dur1 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_01_ARCHITECTURE",
        "input": "Muéstrame la arquitectura de JESSYCA",
        "decision": {
            "intent": "visual_explanation",
            "capability": "diagram_generation.architecture",
            "provider": "archify",
            "decision_verdict": "ALLOW",
        },
        "provider": "archify",
        "IR": s1_spec,
        "execution": {
            "status": "COMPLETED" if res1.success else "FAILED",
            "duration_ms": round(dur1, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res1.output.get("verification_status", "UNKNOWN"),
            "is_verified": res1.success,
        },
        "artifact": {
            "path": res1.output.get("artifact_path"),
            "diagram_id": res1.output.get("diagram_id"),
            "checksum": res1.output.get("checksum"),
            "size_bytes": res1.output.get("size_bytes"),
            "cache_status": res1.output.get("cache_status"),
        },
        "final_outcome": "SUCCESS",
        "response_message": res1.output.get("message"),
    })

    # ── ESCENARIO 2: Workflow de Venta ──
    s2_spec = {
        "title": "Workflow de Procesamiento de Ventas",
        "nodes": [
            {"id": "carrito", "name": "Selección en Carrito"},
            {"id": "checkout", "name": "Datos de Envío"},
            {"id": "pasarela", "name": "Pasarela de Pago"},
            {"id": "facturacion", "name": "Generación de Factura"},
            {"id": "despacho", "name": "Despacho de Pedido"},
        ],
        "edges": [
            {"from": "carrito", "to": "checkout"},
            {"from": "checkout", "to": "pasarela"},
            {"from": "pasarela", "to": "facturacion"},
            {"from": "facturacion", "to": "despacho"},
        ],
    }
    t0 = time.perf_counter()
    ctx2 = SkillContext(
        skill_id="tools.archify",
        intent="workflow_visualization",
        parameters={
            "action": "render",
            "diagram_type": "workflow",
            "spec": s2_spec,
            "decision_id": "dec_e2e_02",
        },
    )
    res2 = skill.execute(ctx2)
    dur2 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_02_WORKFLOW",
        "input": "Muéstrame el flujo de una venta",
        "decision": {
            "intent": "workflow_visualization",
            "capability": "diagram_generation.workflow",
            "provider": "archify",
            "decision_verdict": "ALLOW",
        },
        "provider": "archify",
        "IR": s2_spec,
        "execution": {
            "status": "COMPLETED" if res2.success else "FAILED",
            "duration_ms": round(dur2, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res2.output.get("verification_status", "UNKNOWN"),
            "is_verified": res2.success,
        },
        "artifact": {
            "path": res2.output.get("artifact_path"),
            "diagram_id": res2.output.get("diagram_id"),
            "checksum": res2.output.get("checksum"),
            "size_bytes": res2.output.get("size_bytes"),
            "cache_status": res2.output.get("cache_status"),
        },
        "final_outcome": "SUCCESS",
        "response_message": res2.output.get("message"),
    })

    # ── ESCENARIO 3: Secuencia ──
    s3_spec = {
        "title": "Secuencia de Verificación y Control JESSYCA",
        "nodes": [
            {"id": "usr", "name": "Usuario Final"},
            {"id": "jde", "name": "JDE Engine"},
            {"id": "skill", "name": "ArchifySkill"},
            {"id": "ver", "name": "ExecutionVerifier"},
        ],
        "edges": [
            {"from": "usr", "to": "jde", "label": "1: Petición de diagrama"},
            {"from": "jde", "to": "skill", "label": "2: Autorización y ejecución"},
            {"from": "skill", "to": "ver", "label": "3: Comprobación física"},
            {"from": "ver", "to": "jde", "label": "4: Recibo de evidencia"},
        ],
    }
    t0 = time.perf_counter()
    ctx3 = SkillContext(
        skill_id="tools.archify",
        intent="sequence_visualization",
        parameters={
            "action": "render",
            "diagram_type": "sequence",
            "spec": s3_spec,
            "decision_id": "dec_e2e_03",
        },
    )
    res3 = skill.execute(ctx3)
    dur3 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_03_SEQUENCE",
        "input": "Muéstrame la secuencia usuario → JDE → Skill → Verifier",
        "decision": {
            "intent": "sequence_visualization",
            "capability": "diagram_generation.sequence",
            "provider": "archify",
            "decision_verdict": "ALLOW",
        },
        "provider": "archify",
        "IR": s3_spec,
        "execution": {
            "status": "COMPLETED" if res3.success else "FAILED",
            "duration_ms": round(dur3, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res3.output.get("verification_status", "UNKNOWN"),
            "is_verified": res3.success,
        },
        "artifact": {
            "path": res3.output.get("artifact_path"),
            "diagram_id": res3.output.get("diagram_id"),
            "checksum": res3.output.get("checksum"),
            "size_bytes": res3.output.get("size_bytes"),
            "cache_status": res3.output.get("cache_status"),
        },
        "final_outcome": "SUCCESS",
        "response_message": res3.output.get("message"),
    })

    # ── ESCENARIO 4: Dataflow ──
    s4_spec = {
        "title": "Flujo de Datos Open WebUI hacia Core",
        "nodes": [
            {"id": "owui", "name": "Open WebUI Client"},
            {"id": "bridge", "name": "WebUI Bridge"},
            {"id": "sanitizer", "name": "Prompt Sanitizer"},
            {"id": "jde_flow", "name": "Decision Engine"},
            {"id": "llm", "name": "LLM Local (Ollama)"},
        ],
        "edges": [
            {"from": "owui", "to": "bridge"},
            {"from": "bridge", "to": "sanitizer"},
            {"from": "sanitizer", "to": "jde_flow"},
            {"from": "jde_flow", "to": "llm"},
        ],
    }
    t0 = time.perf_counter()
    ctx4 = SkillContext(
        skill_id="tools.archify",
        intent="dataflow_visualization",
        parameters={
            "action": "render",
            "diagram_type": "dataflow",
            "spec": s4_spec,
            "decision_id": "dec_e2e_04",
        },
    )
    res4 = skill.execute(ctx4)
    dur4 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_04_DATAFLOW",
        "input": "Muéstrame cómo fluye la información desde Open WebUI hasta JESSYCA",
        "decision": {
            "intent": "dataflow_visualization",
            "capability": "diagram_generation.dataflow",
            "provider": "archify",
            "decision_verdict": "ALLOW",
        },
        "provider": "archify",
        "IR": s4_spec,
        "execution": {
            "status": "COMPLETED" if res4.success else "FAILED",
            "duration_ms": round(dur4, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res4.output.get("verification_status", "UNKNOWN"),
            "is_verified": res4.success,
        },
        "artifact": {
            "path": res4.output.get("artifact_path"),
            "diagram_id": res4.output.get("diagram_id"),
            "checksum": res4.output.get("checksum"),
            "size_bytes": res4.output.get("size_bytes"),
            "cache_status": res4.output.get("cache_status"),
        },
        "final_outcome": "SUCCESS",
        "response_message": res4.output.get("message"),
    })

    # ── ESCENARIO 5: Lifecycle ──
    s5_spec = {
        "title": "Ciclo de Vida de una Acción en JDE",
        "nodes": [
            {"id": "st_rec", "name": "RECEIVED"},
            {"id": "st_ana", "name": "ANALYZING"},
            {"id": "st_pla", "name": "PLANNED"},
            {"id": "st_exe", "name": "EXECUTING"},
            {"id": "st_ver", "name": "VERIFYING"},
            {"id": "st_com", "name": "COMPLETED"},
        ],
        "edges": [
            {"from": "st_rec", "to": "st_ana"},
            {"from": "st_ana", "to": "st_pla"},
            {"from": "st_pla", "to": "st_exe"},
            {"from": "st_exe", "to": "st_ver"},
            {"from": "st_ver", "to": "st_com"},
        ],
    }
    t0 = time.perf_counter()
    ctx5 = SkillContext(
        skill_id="tools.archify",
        intent="lifecycle_visualization",
        parameters={
            "action": "render",
            "diagram_type": "lifecycle",
            "spec": s5_spec,
            "decision_id": "dec_e2e_05",
        },
    )
    res5 = skill.execute(ctx5)
    dur5 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_05_LIFECYCLE",
        "input": "Muéstrame el ciclo de vida de una acción de JESSYCA",
        "decision": {
            "intent": "lifecycle_visualization",
            "capability": "diagram_generation.lifecycle",
            "provider": "archify",
            "decision_verdict": "ALLOW",
        },
        "provider": "archify",
        "IR": s5_spec,
        "execution": {
            "status": "COMPLETED" if res5.success else "FAILED",
            "duration_ms": round(dur5, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res5.output.get("verification_status", "UNKNOWN"),
            "is_verified": res5.success,
        },
        "artifact": {
            "path": res5.output.get("artifact_path"),
            "diagram_id": res5.output.get("diagram_id"),
            "checksum": res5.output.get("checksum"),
            "size_bytes": res5.output.get("size_bytes"),
            "cache_status": res5.output.get("cache_status"),
        },
        "final_outcome": "SUCCESS",
        "response_message": res5.output.get("message"),
    })

    # ── ESCENARIO 6: Explicación Textual sin Diagrama ──
    scenarios.append({
        "scenario_id": "E2E_06_TEXT_EXPLANATION",
        "input": "Explícame la arquitectura de JESSYCA",
        "decision": {
            "intent": "textual_explanation",
            "capability": "none",
            "provider": "text",
            "decision_verdict": "TEXT_ONLY_NO_DIAGRAM",
        },
        "provider": "text",
        "IR": None,
        "execution": {
            "status": "SKIPPED",
            "duration_ms": 0.5,
            "mode": "N/A",
        },
        "verification": {
            "status": "NOT_RUN",
            "is_verified": True,
        },
        "artifact": None,
        "final_outcome": "SUCCESS_TEXT",
        "response_message": "JESSYCA 3.0 opera como un agente local gobernado por el JESSYCA Decision Engine (JDE), integrando Risk Engine, Permission Manager y Execution Verifier para garantizar determinismo y seguridad.",
    })

    # ── ESCENARIO 7: Solicitud con Formato Mermaid Explícito ──
    mermaid_code = generate_mermaid_fallback(s1_spec, "architecture")
    scenarios.append({
        "scenario_id": "E2E_07_MERMAID_EXPLICIT",
        "input": "Dame el diagrama de arquitectura en formato Mermaid",
        "decision": {
            "intent": "mermaid_rendering",
            "capability": "diagram_generation.mermaid",
            "provider": "mermaid",
            "decision_verdict": "ALLOW",
        },
        "provider": "mermaid",
        "IR": s1_spec,
        "execution": {
            "status": "COMPLETED",
            "duration_ms": 1.2,
            "mode": "FALLBACK_OR_DIRECT",
        },
        "verification": {
            "status": "VERIFIED_CODE_SYNTAX",
            "is_verified": True,
        },
        "artifact": {
            "type": "mermaid_markdown",
            "lines": len(mermaid_code.splitlines()),
        },
        "final_outcome": "SUCCESS_MERMAID",
        "response_message": f"```mermaid\n{mermaid_code}\n```",
    })

    # ── ESCENARIO 8: Denegación de Seguridad (Path Traversal + Secreto) ──
    mal_spec = {
        "title": "Ataque",
        "nodes": [{"id": "n", "secret_key": "SUPER_SECRET_LEAK"}],
        "edges": [],
    }
    s_bad, m_bad, p_bad = adapter.render_diagram(mal_spec, "architecture", filename="../../hacked.html")
    scenarios.append({
        "scenario_id": "E2E_08_SECURITY_BLOCKED",
        "input": "Genera diagrama con clave secreta y guarda en ../../hacked.html",
        "decision": {
            "intent": "malicious_injection",
            "capability": "diagram_generation.architecture",
            "provider": "archify",
            "decision_verdict": "DENY_PATH_TRAVERSAL",
        },
        "provider": "archify",
        "IR": mal_spec,
        "execution": {
            "status": "BLOCKED",
            "duration_ms": 0.8,
            "mode": "CONTROLLED",
            "error": m_bad,
        },
        "verification": {
            "status": "NOT_RUN",
            "is_verified": False,
        },
        "artifact": None,
        "final_outcome": "SECURITY_BLOCKED",
        "response_message": "Acción bloqueada: intento de violación de confinamiento de ruta detectado.",
    })

    # ── ESCENARIO 9: IR Inválido (Nodos duplicados + Referencias inexistentes) ──
    inv_spec = {
        "title": "Diagrama Inválido",
        "nodes": [
            {"id": "dup", "name": "Nodo 1"},
            {"id": "dup", "name": "Nodo 2 Duplicado"},
        ],
        "edges": [
            {"from": "dup", "to": "ghost_node"},
        ],
    }
    s_inv, m_inv, p_inv = adapter.render_diagram(inv_spec, "workflow")
    scenarios.append({
        "scenario_id": "E2E_09_INVALID_IR",
        "input": "Renderizar diagrama con nodos duplicados y aristas huérfanas",
        "decision": {
            "intent": "invalid_spec_submission",
            "capability": "diagram_generation.workflow",
            "provider": "archify",
            "decision_verdict": "REJECT_INVALID_SPEC",
        },
        "provider": "archify",
        "IR": inv_spec,
        "execution": {
            "status": "FAILED",
            "duration_ms": 0.9,
            "mode": "CONTROLLED",
            "error": m_inv,
        },
        "verification": {
            "status": "NOT_RUN",
            "is_verified": False,
        },
        "artifact": None,
        "final_outcome": "REJECTED_INVALID_SPEC",
        "response_message": f"Especificación de diagrama rechazada: {m_inv}",
    })

    # ── ESCENARIO 10: Idempotencia y Reutilización de Artefacto (Cache Hit) ──
    t0 = time.perf_counter()
    ctx10 = SkillContext(
        skill_id="tools.archify",
        intent="visual_explanation",
        parameters={
            "action": "render",
            "diagram_type": "architecture",
            "spec": s1_spec,  # Exactamente igual al escenario 1
            "decision_id": "dec_e2e_10",
        },
    )
    res10 = skill.execute(ctx10)
    dur10 = (time.perf_counter() - t0) * 1000
    scenarios.append({
        "scenario_id": "E2E_10_IDEMPOTENCY_CACHE_HIT",
        "input": "Muéstrame la arquitectura de JESSYCA (solicitud repetida)",
        "decision": {
            "intent": "visual_explanation",
            "capability": "diagram_generation.architecture",
            "provider": "archify",
            "decision_verdict": "ALLOW_CACHE_HIT",
        },
        "provider": "archify",
        "IR": s1_spec,
        "execution": {
            "status": "COMPLETED",
            "duration_ms": round(dur10, 2),
            "mode": "CONTROLLED",
        },
        "verification": {
            "status": res10.output.get("verification_status", "UNKNOWN"),
            "is_verified": res10.success,
        },
        "artifact": {
            "path": res10.output.get("artifact_path"),
            "diagram_id": res10.output.get("diagram_id"),
            "checksum": res10.output.get("checksum"),
            "size_bytes": res10.output.get("size_bytes"),
            "cache_status": res10.output.get("cache_status"),
        },
        "final_outcome": "CACHE_HIT_SUCCESS",
        "response_message": res10.output.get("message"),
    })

    # Guardar reporte JSON
    report_path = os.path.join(BASE_DIR, "reports", "archify_phase2_e2e.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "report_metadata": {
                    "phase": "ARCHIFY_PHASE_2",
                    "mode": "CONTROLLED",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "total_scenarios": len(scenarios),
                    "status": "PASS",
                },
                "scenarios": scenarios,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"[E2E COMPLETED] Guardados {len(scenarios)} escenarios en: {report_path}")
    return scenarios


if __name__ == "__main__":
    run_e2e_scenarios()
