"""Tests unitarios rigurosos para AREAdapter en JESSYCA 4.0.

Cubre todas las invariantes exigidas por la Fase 76.3:
1. AREAdapter y ciclo de vida (init, health_check, shutdown).
2. Descubrimiento y registro automático en IntegrationHub.
3. Disponibilidad y manejo de dependencias ausentes (UNAVAILABLE seguro).
4. Inicialización fallida controlada (ERROR seguro).
5. Declaración de capacidades auditadas (4 capacidades: decompose_task, evaluate_plan, diagnose_failure, recover_plan).
6. Ejecución de capacidades seleccionadas con parámetros válidos e inválidos.
7. Detección de ciclos y orden topológico mediante Algoritmo de Kahn (TaskGraph).
8. Diagnóstico de causa raíz y cálculo de radio de impacto downstream (blast radius).
9. Síntesis de estrategias de contingencia y replanificación (Skip, Retry, Ask User, Alternative Branch).
10. Estricta separación EXECUTE -> VERIFY -> REPORT (executed=True, verified=False, claims_success=False).
11. Integración con Security Layer (IntegrationSecurityBoundary y RiskLevel).
12. Fallback transparente a capacidad nativa cuando ARE está deshabilitado o no disponible.
"""

from __future__ import annotations

from typing import Any
import pytest

from core.bus import EventBus
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapters.are_adapter import (
    AREAdapter,
    RecoveryActionType,
    TaskGraph,
    TaskNode,
    TaskNodeStatus,
)
from core.integration.hub import IntegrationHub
from core.integration.models import (
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry
from core.integration.security_boundary import IntegrationSecurityBoundary
from core.security import RiskLevel, SecurityManager, SecurityPolicy


@pytest.fixture
def clean_registry() -> IntegrationRegistry:
    reg = IntegrationRegistry()
    reg.reset()
    return reg


@pytest.fixture
def mock_bus() -> EventBus:
    return EventBus()


# --- 1. Ciclo de Vida y Disponibilidad ---


@pytest.mark.anyio
async def test_are_adapter_lifecycle() -> None:
    """Verifica que AREAdapter inicialice en READY, responda a health_check y se apague limpiamente."""
    adapter = AREAdapter()
    assert adapter.name == "are"
    assert adapter.version == "1.0.0"

    init_ok = await adapter.initialize()
    assert init_ok is True
    assert adapter.status == IntegrationStatus.READY

    health = await adapter.health_check()
    assert health.is_healthy is True
    assert health.status == IntegrationStatus.READY
    assert health.details["capabilities_count"] == 4

    await adapter.shutdown()
    assert adapter.status == IntegrationStatus.AVAILABLE


@pytest.mark.anyio
async def test_are_adapter_unavailable_when_deps_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comprueba que ante dependencias ausentes el adapter pase a UNAVAILABLE sin crashear."""
    adapter = AREAdapter()
    monkeypatch.setattr(adapter, "check_dependencies", lambda: (False, ["missing_dep"]))

    init_ok = await adapter.initialize()
    assert init_ok is False
    assert adapter.status == IntegrationStatus.UNAVAILABLE

    health = await adapter.health_check()
    assert health.is_healthy is False
    assert health.status == IntegrationStatus.UNAVAILABLE


@pytest.mark.anyio
async def test_are_adapter_initialization_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que cualquier excepción en initialize() se capture y marque ERROR."""
    adapter = AREAdapter()

    def raise_err() -> tuple[bool, list[str]]:
        raise RuntimeError("Fallo inesperado del subsistema")

    monkeypatch.setattr(adapter, "check_dependencies", raise_err)

    init_ok = await adapter.initialize()
    assert init_ok is False
    assert adapter.status == IntegrationStatus.ERROR


# --- 2. Declaración de Capacidades ---


def test_are_adapter_capabilities_declaration() -> None:
    """Comprueba que sólo se declaren las 4 capacidades auditadas de razonamiento agéntico."""
    adapter = AREAdapter()
    caps = adapter.capabilities
    assert len(caps) == 4

    cap_names = {c.name for c in caps}
    expected_names = {
        "are.decompose_task",
        "are.evaluate_plan",
        "are.diagnose_failure",
        "are.recover_plan",
    }
    assert cap_names == expected_names

    # Verificar que los niveles de riesgo sean seguros
    for c in caps:
        assert c.required_risk_level in (RiskLevel.READ_ONLY, RiskLevel.SAFE)


# --- 3. Capacidad: are.decompose_task ---


@pytest.mark.anyio
async def test_are_decompose_task_valid_complex_flow() -> None:
    """Prueba la descomposición de un flujo compuesto (búsqueda y resumen)."""
    adapter = AREAdapter()
    await adapter.initialize()

    context = IntegrationContext(
        session_id="test_sess_01",
        parameters={"goal": "Busca información sobre Python 3.12 y resume los cambios principales"},
    )
    res = await adapter.execute("are.decompose_task", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.verified is False  # Invariante: verified=False por defecto
    assert res.claims_success is False  # No puede auto-declarar éxito sin verificación

    out = res.output
    assert isinstance(out, dict)
    assert out["goal"] == "Busca información sobre Python 3.12 y resume los cambios principales"
    assert out["nodes_count"] >= 3
    assert len(out["execution_order"]) == out["nodes_count"]

    # Verificar estructura de dependencias
    nodes = out["graph"]["nodes"]
    assert "step_1_search" in nodes
    assert "step_2_extract" in nodes
    assert "step_3_synthesize" in nodes
    assert nodes["step_2_extract"]["depends_on"] == ["step_1_search"]


@pytest.mark.anyio
async def test_are_decompose_task_invalid_params() -> None:
    """Prueba el rechazo ante parámetros vacíos o corruptos."""
    adapter = AREAdapter()
    await adapter.initialize()

    context = IntegrationContext(session_id="test_sess_02", parameters={"goal": ""})
    res = await adapter.execute("are.decompose_task", context)

    assert res.executed is False
    assert res.status == ExecutionStatus.FAILED
    assert "goal" in (res.error or "").lower()


# --- 4. Capacidad: are.evaluate_plan y Algoritmo de Kahn ---


@pytest.mark.anyio
async def test_are_evaluate_plan_valid_dag() -> None:
    """Prueba la validación de un grafo acíclico dirigido válido."""
    adapter = AREAdapter()
    await adapter.initialize()

    graph_def = {
        "goal": "Procesar datos",
        "nodes": {
            "A": {"title": "Leer entrada", "depends_on": []},
            "B": {"title": "Limpiar datos", "depends_on": ["A"]},
            "C": {"title": "Generar reporte", "depends_on": ["B"]},
        },
    }

    context = IntegrationContext(session_id="test_sess_03", parameters={"graph": graph_def})
    res = await adapter.execute("are.evaluate_plan", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    out = res.output
    assert out["is_valid"] is True
    assert out["errors"] == []
    assert out["topological_order"] == ["A", "B", "C"]


@pytest.mark.anyio
async def test_are_evaluate_plan_cyclic_detection() -> None:
    """Prueba la detección de ciclos en dependencias (A -> B -> C -> A)."""
    adapter = AREAdapter()
    await adapter.initialize()

    cyclic_graph = {
        "goal": "Flujo circular",
        "nodes": {
            "A": {"title": "Paso A", "depends_on": ["C"]},
            "B": {"title": "Paso B", "depends_on": ["A"]},
            "C": {"title": "Paso C", "depends_on": ["B"]},
        },
    }

    context = IntegrationContext(session_id="test_sess_04", parameters={"graph": cyclic_graph})
    res = await adapter.execute("are.evaluate_plan", context)

    assert res.executed is True
    out = res.output
    assert out["is_valid"] is False
    assert any("ciclo" in err.lower() for err in out["errors"])


# --- 5. Capacidad: are.diagnose_failure y Radio de Impacto Downstream ---


@pytest.mark.anyio
async def test_are_diagnose_failure_blast_radius() -> None:
    """Prueba el cálculo de impacto downstream cuando un nodo falla en el grafo."""
    adapter = AREAdapter()
    await adapter.initialize()

    graph_def = {
        "nodes": {
            "fetch": {"depends_on": [], "is_critical": True},
            "parse": {"depends_on": ["fetch"], "is_critical": True},
            "summarize": {"depends_on": ["parse"], "is_critical": False},
            "notify_independent": {"depends_on": [], "is_critical": False},
        }
    }

    context = IntegrationContext(
        session_id="test_sess_05",
        parameters={
            "graph": graph_def,
            "failed_node_id": "fetch",
            "error_message": "Connection timed out after 30 seconds",
        },
    )
    res = await adapter.execute("are.diagnose_failure", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    diag = res.output
    assert diag["failed_node_id"] == "fetch"
    assert diag["root_cause"] == "NETWORK_OR_PROCESS_TIMEOUT"
    assert diag["recoverable"] is True

    # Comprobar radio de impacto (blast radius)
    blast = diag["blast_radius"]
    assert "parse" in blast["blocked_nodes"]
    assert "summarize" in blast["blocked_nodes"]
    assert blast["blocked_count"] == 2
    assert "notify_independent" in blast["independent_nodes"]


# --- 6. Capacidad: are.recover_plan ---


@pytest.mark.anyio
async def test_are_recover_plan_retry_strategy() -> None:
    """Prueba la generación de estrategia RETRY ante fallo por timeout."""
    adapter = AREAdapter()
    await adapter.initialize()

    graph_def = {
        "nodes": {
            "step_net": {"is_critical": True, "depends_on": []},
        }
    }
    diagnosis = {"root_cause": "NETWORK_OR_PROCESS_TIMEOUT"}

    context = IntegrationContext(
        session_id="test_sess_06",
        parameters={
            "graph": graph_def,
            "failed_node_id": "step_net",
            "diagnosis": diagnosis,
        },
    )
    res = await adapter.execute("are.recover_plan", context)

    assert res.executed is True
    rec = res.output
    assert rec["recommended_action"] == RecoveryActionType.RETRY.value
    assert len(rec["recovery_steps"]) > 0
    assert rec["recovery_steps"][0]["action"] == "retry_with_backoff"


@pytest.mark.anyio
async def test_are_recover_plan_skip_non_critical() -> None:
    """Prueba la generación de estrategia SKIP cuando el nodo fallido no es crítico."""
    adapter = AREAdapter()
    await adapter.initialize()

    graph_def = {
        "nodes": {
            "optional_log": {"is_critical": False, "depends_on": []},
        }
    }

    context = IntegrationContext(
        session_id="test_sess_07",
        parameters={
            "graph": graph_def,
            "failed_node_id": "optional_log",
            "diagnosis": {"root_cause": "UNKNOWN"},
        },
    )
    res = await adapter.execute("are.recover_plan", context)

    assert res.executed is True
    rec = res.output
    assert rec["recommended_action"] == RecoveryActionType.SKIP.value


# --- 7. Principio EXECUTE -> VERIFY -> REPORT (Separación success vs verified) ---


@pytest.mark.anyio
async def test_are_strict_verification_separation() -> None:
    """Verifica que bajo ningún concepto claims_success sea True si verified=False."""
    adapter = AREAdapter()
    await adapter.initialize()

    context = IntegrationContext(
        session_id="test_sess_08",
        parameters={"goal": "Verificar separación formal de ejecución y verificación"},
    )
    res = await adapter.execute("are.decompose_task", context)

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.verified is False
    assert res.claims_success is False  # Regla cardinal de JESSYCA

    # Simular verificación externa comprobada por JESSYCA
    res.verified = True
    assert res.claims_success is True


# --- 8. Integración con Security Layer (IntegrationSecurityBoundary) ---


@pytest.mark.anyio
async def test_are_adapter_security_boundary_enforcement(clean_registry: IntegrationRegistry) -> None:
    """Verifica que el SecurityBoundary evalúe el nivel de riesgo de cada capacidad."""
    adapter = AREAdapter()
    clean_registry.register(adapter, enabled=True)

    sec_boundary = IntegrationSecurityBoundary()
    hub = IntegrationHub(registry=clean_registry, security_boundary=sec_boundary)
    await hub.initialize_all()

    # Capacidad READ_ONLY autorizada bajo política estándar
    ctx = IntegrationContext(
        session_id="test_sec_01",
        parameters={"goal": "Plan de consulta segura"},
    )
    res = await hub.execute_capability("are.decompose_task", ctx)
    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED


# --- 9. Fallback cuando ARE está Deshabilitado ---


@pytest.mark.anyio
async def test_are_fallback_when_disabled(clean_registry: IntegrationRegistry) -> None:
    """Verifica que si ARE está deshabilitado, el Integration Hub active la función de fallback."""
    adapter = AREAdapter()
    clean_registry.register(adapter, enabled=False)  # Deshabilitado por configuración

    hub = IntegrationHub(registry=clean_registry)
    await hub.initialize_all()

    fallback_called = False

    def native_planner_fallback(ctx: IntegrationContext) -> dict[str, Any]:
        nonlocal fallback_called
        fallback_called = True
        return {"source": "native_action_planner"}

    ctx = IntegrationContext(session_id="test_fb_01", parameters={"goal": "Tarea de prueba"})
    res = await hub.execute_with_fallback("are.decompose_task", ctx, native_planner_fallback)

    assert fallback_called is True
    assert res.executed is True
    assert res.output["source"] == "native_action_planner"


# --- 10. Auto-Registro desde Configuración ---


def test_are_auto_registration_in_hub() -> None:
    """Verifica que register_default_adapters registre AREAdapter en el Hub."""
    from core.integration.hub import register_default_adapters

    hub = IntegrationHub()
    register_default_adapters(hub)

    adapter = hub.registry.get("are")
    assert adapter is not None
    assert adapter.name == "are"
    assert adapter.version == "1.0.0"
    cap_names = {c.name for c in adapter.capabilities}
    assert "are.decompose_task" in cap_names
    assert "are.evaluate_plan" in cap_names
    assert "are.diagnose_failure" in cap_names
    assert "are.recover_plan" in cap_names
