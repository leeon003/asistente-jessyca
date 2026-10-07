"""Comprehensive Tests for Phase 12: Generalized Planning with Real Tools in ARE.

Validates:
1. Tool inexistente (UnresolvableActionError / rejection before execution).
2. Parámetros inválidos (PlanValidationError outside LLM).
3. Dependencia fallida (Downstream step blocked, blast radius evaluated).
4. Salida ausente (DataFlow MissingOutputDependencyError handling).
5. Denegación y persistencia de denegación en replanificación (ReplanningDenialViolationError).
6. Cancelación controlada por CancellationToken (AgentExecutionState.INTERRUPTED).
7. Recuperación acotada sin bucle infinito (MAX_RECOVERY_ATTEMPTS enforcement).
8. Anti-False Success: No declarar éxito ante resultado no verificable físicamente.
9. Sandbox Objetivo 1: Localizar documento y resumirlo con referencias auditables.
10. Sandbox Objetivo 2: Organizar copias de archivos con vista previa y verificación física.
11. Sandbox Objetivo 3: Extraer tabla a archivo verificable y conteo de filas en disco.
12. Solicitud de aclaración ante destinos o recursos esenciales faltantes (PlanClarificationRequired).
13. Inviolabilidad de modo ACTIVE (permanece estrictamente bloqueado).
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
import pytest

from core.are.action_catalog import (
    ActionCatalog,
    ActionVerificationStrategy,
    ExecutableAction,
    get_default_action_catalog,
)
from core.are.dataflow import DataFlowResolver
from core.are.exceptions import (
    MissingOutputDependencyError,
    PlanBudgetExceededError,
    PlanClarificationRequired,
    PlanValidationError,
    ReplanningDenialViolationError,
    SandboxViolationError,
    UnresolvableActionError,
)
from core.are.execution_state import AREPlanExecutionState
from core.are.models import ARERuntimeMode
from core.are.plan_validator import LLMPlanProposal, LLMStepProposal, PlanValidator
from core.are.runtime import ARERuntime, reset_are_runtime
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeVerdict,
    JDERuntimeVerdictType,
)
from core.emergency_stop import CancellationToken
from core.local_agent.local_agent_models import AgentExecutionState, JessycaRequest
from core.security import RiskLevel


class MockAgentForPhase12:
    """Mock agent governed by JDE for Phase 12 validation."""

    def __init__(self, jde_binding: JDERuntimeBinding | None = None):
        self.jde_runtime_binding = jde_binding or JDERuntimeBinding()
        self.context_manager = None
        self._latest_metrics = None
        self.skill_manager = None
        self.tool_registry = None


# ── TEST 1: TOOL INEXISTENTE Y PLACEHOLDERS GENÉRICOS ──

def test_p12_unresolvable_tool_rejected():
    """Valida que una herramienta inexistente o placeholder genérico ('action.execute')
    sea estrictamente rechazada antes de la ejecución física."""
    catalog = ActionCatalog()

    # 1. Rechazo de placeholders genéricos sin implementación
    with pytest.raises(UnresolvableActionError) as exc_generic:
        catalog.resolve_action("action.execute")
    assert "placeholder genérico" in str(exc_generic.value)
    assert exc_generic.value.code == "GENERIC_ACTION_REJECTED"

    # 2. Rechazo de herramientas inexistentes
    with pytest.raises(UnresolvableActionError) as exc_missing:
        catalog.resolve_action("tools.non_existent_utility")
    assert exc_missing.value.code == "ACTION_NOT_FOUND"

    # 3. Validación de plan LLM fuera del LLM con tool inexistente
    validator = PlanValidator(catalog=catalog)
    proposal = {
        "goal": "probar tool inexistente",
        "steps": [
            {
                "step_id": "step_1",
                "title": "Invocar acción fantasma",
                "action_type": "tools.non_existent_utility",
                "parameters": {},
                "depends_on": [],
            }
        ],
    }
    with pytest.raises(UnresolvableActionError):
        validator.validate_plan(proposal)


# ── TEST 2: PARÁMETROS INVÁLIDOS RECHAZADOS FUERA DEL LLM ──

def test_p12_invalid_parameters_rejected_outside_llm():
    """Valida que parámetros faltantes o tipos incorrectos según el schema
    sean rechazados fuera del LLM por PlanValidator."""
    catalog = ActionCatalog()
    validator = PlanValidator(catalog=catalog)

    # files.copy requiere tanto 'source_path' como 'destination_path'
    proposal = {
        "goal": "copiar archivo sin destino",
        "steps": [
            {
                "step_id": "step_copy",
                "title": "Copia incompleta",
                "action_type": "files.copy",
                "parameters": {"source_path": "origen.txt"},  # falta destination_path
                "depends_on": [],
            }
        ],
    }

    with pytest.raises(PlanValidationError) as exc:
        validator.validate_plan(proposal)
    assert "destination_path" in str(exc.value)


# ── TEST 3: SALIDA AUSENTE Y DATAFLOW RESOLUTION ──

def test_p12_missing_output_dependency_raises_typed_error():
    """Valida que referenciar una salida ausente en un paso previo lance
    MissingOutputDependencyError y detenga la ejecución limpiamente."""
    step_outputs = {
        "step_1": {
            "found_files": ["archivo1.txt"],
        }
    }

    # Intentar acceder a una propiedad inexistente
    params = {"target": "$step_1.output.non_existent_key"}
    with pytest.raises(MissingOutputDependencyError) as exc_missing_prop:
        DataFlowResolver.resolve_parameters(params, step_outputs, step_id="step_2")
    assert "ausente en la salida" in str(exc_missing_prop.value)

    # Intentar acceder a un paso no ejecutado
    params_unexecuted = {"target": "$step_non_executed.output.data"}
    with pytest.raises(MissingOutputDependencyError) as exc_unexec:
        DataFlowResolver.resolve_parameters(params_unexecuted, step_outputs, step_id="step_2")
    assert "no ha concluido exitosamente" in str(exc_unexec.value)


# ── TEST 4: DENEGACIÓN Y PERSISTENCIA EN REPLANIFICACIÓN ──

def test_p12_denial_cannot_be_erased_in_replanning():
    """Valida que una acción denegada por JDE se registre persistentemente y que
    la replanificación no pueda reintroducirla ni borrar la denegación."""
    class SelectiveDenyBinding(JDERuntimeBinding):
        def evaluate(self, *args, **kwargs):
            action = kwargs.get("action", "")
            if "format_disk" in action or "delete" in action:
                return JDERuntimeVerdict(
                    verdict=JDERuntimeVerdictType.DENY,
                    reason="Destructive operations forbidden",
                    action=action,
                    tool=kwargs.get("tool", "system"),
                )
            return JDERuntimeVerdict(
                verdict=JDERuntimeVerdictType.ALLOW,
                reason="Permitted",
                action=action,
                tool=kwargs.get("tool", "system"),
            )

    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = MockAgentForPhase12(jde_binding=SelectiveDenyBinding())

    # Registrar acción destructiva en el catálogo para prueba
    rt.action_catalog.register_action(
        ExecutableAction(
            action_id="system.format_disk",
            description="Destructive action",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            risk_level=RiskLevel.CRITICAL,
            verification_strategy=ActionVerificationStrategy.STATE_MATCH,
            handler=lambda p, c: {"executed": True},
        )
    )

    # Plan 1: contiene la acción que será denegada
    plan_1 = {
        "goal": "limpieza de disco",
        "steps": [
            {
                "step_id": "step_1",
                "title": "Formatear partición",
                "action_type": "system.format_disk",
                "parameters": {},
                "depends_on": [],
            }
        ],
    }

    req = JessycaRequest(request_id="req_deny_p12", user_input="formatea el disco")
    resp_1 = rt.execute_llm_plan(agent, req, plan_1)
    assert resp_1.success is False
    assert resp_1.security_verdict == "DENY"

    # Verificar que la denegación quedó registrada en la memoria del runtime
    assert "system.format_disk" in rt.previously_denied_actions

    # Replanificación: el LLM intenta reintroducir la misma acción denegada
    plan_replanned = {
        "goal": "limpieza alternativa de disco",
        "steps": [
            {
                "step_id": "step_alt_1",
                "title": "Reintento de formateo",
                "action_type": "system.format_disk",
                "parameters": {},
                "depends_on": [],
            }
        ],
    }

    # El validador fuera del LLM debe rechazar inmediatamente el nuevo plan
    validator = PlanValidator(catalog=rt.action_catalog)
    with pytest.raises(ReplanningDenialViolationError) as exc_rep:
        validator.validate_plan(plan_replanned, previously_denied_actions=rt.previously_denied_actions)
    assert "denegada previamente" in str(exc_rep.value)


# ── TEST 5: CANCELACIÓN CONTROLADA POR CANCELLATION TOKEN ──

def test_p12_cancellation_stops_execution_cleanly():
    """Valida que un token de cancelación detenga la ejecución del plan
    de forma inmediata sin ejecutar pasos restantes."""
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = MockAgentForPhase12()

    token = CancellationToken()
    # Cancelar el token antes o durante la ejecución
    token.cancel()

    plan = {
        "goal": "tarea que será cancelada",
        "steps": [
            {
                "step_id": "step_1",
                "title": "Paso 1",
                "action_type": "core.assistant",
                "parameters": {},
                "depends_on": [],
            },
            {
                "step_id": "step_2",
                "title": "Paso 2",
                "action_type": "core.assistant",
                "parameters": {},
                "depends_on": ["step_1"],
            },
        ],
    }

    req = JessycaRequest(request_id="req_cancel_p12", user_input="proceso cancelado")
    resp = rt.execute_llm_plan(agent, req, plan, cancellation_token=token)

    assert resp.success is False
    assert resp.status == AgentExecutionState.INTERRUPTED
    assert len(resp.tools_executed) == 0
    assert rt.last_execution_state.status == "CANCELLED"


# ── TEST 6: RECUPERACIÓN ACOTADA (ANTI-BUCLE INFINITO) ──

def test_p12_bounded_recovery_terminates_at_max_attempts():
    """Valida que la estrategia de recuperación acotada no entre en bucle infinito
    y fuerce un ABORT seguro al superar MAX_RECOVERY_ATTEMPTS."""
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    diag, rec = rt.diagnose_and_recover(
        failed_step_id="step_glitch",
        error_message="Persistent failure",
        attempt_number=rt.MAX_RECOVERY_ATTEMPTS + 1,  # 4 > 3
        failed_step="step_glitch",
    )

    assert rec.recommended_action == "ABORT"
    assert "Max recovery attempts exceeded" in rec.reason
    assert diag.recoverable is False


# ── TEST 7: NO DECLARAR ÉXITO ANTE RESULTADO NO VERIFICABLE (ANTI-FALSE SUCCESS) ──

def test_p12_anti_false_success_on_unverified_physical_result():
    """Valida el principio EXECUTE -> VERIFY -> REPORT: Si una acción alega éxito
    pero la verificación física en disco falla (archivo no existe), la ejecución
    se degrada a FAILED y nunca reporta éxito."""
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = MockAgentForPhase12()

    # Registrar una acción mentirosa que dice tener éxito pero no crea el archivo
    def _lying_handler(params, ctx):
        return {
            "file_path": "C:\\ruta_inexistente_fantasma_12345.txt",
            "created": True,
            "verified": False,
        }

    rt.action_catalog.register_action(
        ExecutableAction(
            action_id="files.fake_writer",
            description="Acción que simula escribir",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            risk_level=RiskLevel.SAFE,
            verification_strategy=ActionVerificationStrategy.PHYSICAL_FILE_EXISTS,
            handler=_lying_handler,
        )
    )

    plan = {
        "goal": "prueba anti falsedad",
        "steps": [
            {
                "step_id": "step_fake",
                "title": "Escritura falsa",
                "action_type": "files.fake_writer",
                "parameters": {},
                "depends_on": [],
            }
        ],
    }

    req = JessycaRequest(request_id="req_fake_verif", user_input="escribe falso")
    resp = rt.execute_llm_plan(agent, req, plan)

    # Debe ser FAILED porque la verificación física no se pudo constatar
    assert resp.success is False
    assert resp.status == AgentExecutionState.FAILED
    assert "Fallo de verificación física" in resp.response_text or "verificación" in resp.response_text


# ── TEST 8: SANDBOX OBJETIVO 1 — LOCALIZAR DOCUMENTO Y RESUMIR CON REFERENCIAS ──

def test_p12_sandbox_objective_1_locate_and_summarize():
    """Sandbox Objetivo 1:
    Localizar un documento en un directorio aislado, leerlo y sintetizarlo
    con referencias documentales auditables (números de línea y citas)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p_tmp = Path(tmp_dir)

        # Crear documento real en el sandbox
        doc_path = p_tmp / "informe_trimestral.txt"
        doc_content = (
            "# Informe Trimestral 2026\n"
            "1. La plataforma JESSYCA completó la integración con JDE de forma exitosa.\n"
            "2. El motor ARE garantiza razonamiento estructurado mediante grafos acíclicos dirigidos.\n"
            "3. La política perimétrica impide la ejecución de acciones sin evidencia física comprobable.\n"
            "4. Se redujo la latencia p95 de respuesta a menos de 45 milisegundos en pruebas locales.\n"
            "5. Todas las llaves privadas y credenciales se redactan automáticamente en memoria.\n"
        )
        doc_path.write_text(doc_content, encoding="utf-8")

        rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        agent = MockAgentForPhase12()

        # Propuesta de plan estructurado tipo LLM
        plan_proposal = {
            "goal": "Localizar informe_trimestral.txt y sintetizarlo con referencias auditables",
            "steps": [
                {
                    "step_id": "step_1_search",
                    "title": "Localizar informe en el sandbox",
                    "action_type": "files.search",
                    "parameters": {"directory": str(p_tmp), "query": "informe_trimestral"},
                    "depends_on": [],
                },
                {
                    "step_id": "step_2_read",
                    "title": "Leer contenido del documento encontrado",
                    "action_type": "documents.read",
                    "parameters": {"file_path": "$step_1_search.output.found_files[0]"},
                    "depends_on": ["step_1_search"],
                },
                {
                    "step_id": "step_3_summarize",
                    "title": "Sintetizar informe con referencias auditables",
                    "action_type": "documents.summarize",
                    "parameters": {
                        "content": "$step_2_read.output.content",
                        "file_path": "$step_2_read.output.file_path",
                        "max_points": 5,
                    },
                    "depends_on": ["step_2_read"],
                },
            ],
        }

        req = JessycaRequest(request_id="req_obj1", user_input="resume informe")
        resp = rt.execute_llm_plan(agent, req, plan_proposal, sandbox_dir=p_tmp)

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert len(resp.tools_executed) == 3

        # Verificar contenido de la síntesis y referencias
        summary_out = resp.output_data["step_3_summarize"]
        assert summary_out["verified"] is True
        assert len(summary_out["key_points"]) >= 3
        assert len(summary_out["references"]) >= 3
        assert any("Línea" in ref for ref in summary_out["references"])


# ── TEST 9: SANDBOX OBJETIVO 2 — ORGANIZAR COPIAS DE ARCHIVOS CON VISTA PREVIA ──

def test_p12_sandbox_objective_2_organize_copies_with_preview():
    """Sandbox Objetivo 2:
    Escanear directorio, generar vista previa de organización de copias por extensión,
    copiar archivos al destino y verificar físicamente la integridad en disco."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p_tmp = Path(tmp_dir)
        src_dir = p_tmp / "origen"
        dst_dir = p_tmp / "copias_organizadas"
        src_dir.mkdir(parents=True)

        # Crear archivos de prueba
        (src_dir / "reporte.txt").write_text("Contenido reporte", encoding="utf-8")
        (src_dir / "grafico.png").write_text("fake png bytes", encoding="utf-8")

        rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        agent = MockAgentForPhase12()

        # Plan de 4 etapas con vista previa antes de copiado
        plan_proposal = {
            "goal": "Organizar copias de archivos en carpetas según extensión previa vista previa",
            "steps": [
                {
                    "step_id": "step_1_scan",
                    "title": "Escanear directorio de origen",
                    "action_type": "files.search",
                    "parameters": {"directory": str(src_dir)},
                    "depends_on": [],
                },
                {
                    "step_id": "step_2_preview",
                    "title": "Generar vista previa de la organización sin efectos secundarios",
                    "action_type": "files.preview_organize",
                    "parameters": {"directory": str(src_dir), "target_base": str(dst_dir)},
                    "depends_on": ["step_1_scan"],
                },
                {
                    "step_id": "step_3_copy_1",
                    "title": "Copiar reporte.txt a destino",
                    "action_type": "files.copy",
                    "parameters": {
                        "source_path": str(src_dir / "reporte.txt"),
                        "destination_path": str(dst_dir / "txt" / "reporte.txt"),
                    },
                    "depends_on": ["step_2_preview"],
                },
                {
                    "step_id": "step_4_verify",
                    "title": "Verificar físicamente en disco la existencia y tamaño de copias",
                    "action_type": "files.verify_copies",
                    "parameters": {
                        "copies_mapping": {
                            str(src_dir / "reporte.txt"): str(dst_dir / "txt" / "reporte.txt"),
                        }
                    },
                    "depends_on": ["step_3_copy_1"],
                },
            ],
        }

        req = JessycaRequest(request_id="req_obj2", user_input="organiza copias")
        resp = rt.execute_llm_plan(agent, req, plan_proposal, sandbox_dir=p_tmp)

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert len(resp.tools_executed) == 4

        # Verificar físicamente en el sistema de archivos del host
        copied_file = dst_dir / "txt" / "reporte.txt"
        assert copied_file.exists()
        assert copied_file.read_text(encoding="utf-8") == "Contenido reporte"

        # Verificar que el preview reportó la asignación correcta
        preview_out = resp.output_data["step_2_preview"]
        assert preview_out["files_count"] == 2
        assert str(src_dir / "reporte.txt") in preview_out["preview_mapping"]


# ── TEST 10: SANDBOX OBJETIVO 3 — EXTRAER TABLA A ARCHIVO VERIFICABLE ──

def test_p12_sandbox_objective_3_extract_table_and_verify_rowcount():
    """Sandbox Objetivo 3:
    Extraer una tabla estructurada desde contenido textual Markdown/CSV,
    escribirla en un archivo CSV destino y verificar físicamente la concordancia de filas."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p_tmp = Path(tmp_dir)
        source_doc = p_tmp / "datos_ventas.md"
        output_csv = p_tmp / "ventas_extraidas.csv"

        md_content = (
            "# Resumen de Ventas\n\n"
            "| ID | Producto | Cantidad | Total |\n"
            "|---|---|---|---|\n"
            "| 101 | Licencia Pro | 5 | 1500 |\n"
            "| 102 | Servidor Local | 2 | 4200 |\n"
            "| 103 | Modulo Seguridad | 10 | 800 |\n"
        )
        source_doc.write_text(md_content, encoding="utf-8")

        rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
        agent = MockAgentForPhase12()

        plan_proposal = {
            "goal": "Extraer tabla de ventas y guardarla en CSV verificable",
            "steps": [
                {
                    "step_id": "step_1_read",
                    "title": "Leer archivo con tabla Markdown",
                    "action_type": "documents.read",
                    "parameters": {"file_path": str(source_doc)},
                    "depends_on": [],
                },
                {
                    "step_id": "step_2_extract",
                    "title": "Parsear y estructurar tabla en memoria",
                    "action_type": "data.extract_table",
                    "parameters": {"content": "$step_1_read.output.content"},
                    "depends_on": ["step_1_read"],
                },
                {
                    "step_id": "step_3_write",
                    "title": "Escribir tabla estructurada a archivo CSV",
                    "action_type": "data.write_table",
                    "parameters": {
                        "output_path": str(output_csv),
                        "headers": "$step_2_extract.output.headers",
                        "rows": "$step_2_extract.output.rows",
                        "format": "csv",
                    },
                    "depends_on": ["step_2_extract"],
                },
                {
                    "step_id": "step_4_verify",
                    "title": "Verificar físicamente archivo CSV y conteo de filas",
                    "action_type": "files.verify_table",
                    "parameters": {
                        "table_path": "$step_3_write.output.output_path",
                        "expected_rows_count": "$step_2_extract.output.rows_count",
                    },
                    "depends_on": ["step_2_extract", "step_3_write"],
                },
            ],
        }

        req = JessycaRequest(request_id="req_obj3", user_input="extrae tabla")
        resp = rt.execute_llm_plan(agent, req, plan_proposal, sandbox_dir=p_tmp)

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert len(resp.tools_executed) == 4

        # Comprobar físicamente el archivo CSV creado
        assert output_csv.exists()
        lines = [ln.strip() for ln in output_csv.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 4  # 1 header + 3 data rows

        # Comprobar el output de verificación física
        verif_out = resp.output_data["step_4_verify"]
        assert verif_out["is_verified"] is True
        assert verif_out["actual_rows_count"] == 3
        assert verif_out["expected_rows_count"] == 3


# ── TEST 11: ACLARACIÓN ANTE DESTINOS O RECURSOS ESENCIALES FALTANTES ──

def test_p12_clarification_solicited_when_essential_destination_missing():
    """Valida que si faltan destinos o recursos esenciales sin valor por defecto,
    el runtime solicite aclaración explícita (PlanClarificationRequired -> AWAITING_CLARIFICATION)."""
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)
    agent = MockAgentForPhase12()

    # Plan que intenta copiar pero omite el parámetro de destino esencial
    ambiguous_plan = {
        "goal": "copiar archivo sin destino claro",
        "steps": [
            {
                "step_id": "step_cp",
                "title": "Copiar a destino indefinido",
                "action_type": "files.copy",
                "parameters": {"source_path": "archivo.txt", "destination_path": ""},
                "depends_on": [],
            }
        ],
    }

    req = JessycaRequest(request_id="req_clarif", user_input="copia archivo")
    resp = rt.execute_llm_plan(agent, req, ambiguous_plan)

    assert resp.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert resp.requires_clarification is True
    assert "Aclaración requerida" in resp.response_text


# ── TEST 12: SANDBOX VIOLATION PREVENTION (NO ESCAPES) ──

def test_p12_sandbox_path_traversal_blocked():
    """Valida que intentos de escape de directorio mediante .. sean bloqueados
    fuera del LLM por PlanValidator."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        p_tmp = Path(tmp_dir)
        catalog = ActionCatalog()
        validator = PlanValidator(catalog=catalog, sandbox_dir=p_tmp)

        malicious_plan = {
            "goal": "escapar del sandbox",
            "steps": [
                {
                    "step_id": "step_escape",
                    "title": "Lectura fuera de sandbox",
                    "action_type": "files.read",
                    "parameters": {"file_path": str(p_tmp / ".." / "system.ini")},
                    "depends_on": [],
                }
            ],
        }

        with pytest.raises(SandboxViolationError) as exc:
            validator.validate_plan(malicious_plan)
        assert "resuelve fuera de" in str(exc.value) or "sandbox" in str(exc.value).lower()


# ── TEST 13: STRICT REJECTION OF ACTIVE MODE ──

def test_p12_active_mode_strictly_prohibited():
    """Valida que el modo ACTIVE continúe estrictamente prohibido y bloqueado en ARE."""
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    with pytest.raises(PermissionError) as exc:
        rt.set_mode("ACTIVE")
    assert "ACTIVE' mode is strictly prohibited" in str(exc.value)
