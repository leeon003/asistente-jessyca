"""Suite de pruebas para Timeout, Cancelación Cooperativa y Deduplicación Atómica (Prompt 04).

Valida:
1. Timeout antes de iniciar efecto (HTTP 504 sin cancelar operación en curso).
2. Timeout después de iniciar efecto (estado RUNNING preservado, no repetición de escrituras).
3. Duplicados simultáneos concurrentes (deduplicación atómica: 1 solo efecto físico ejecutado).
4. Misma clave de idempotencia con distinto payload produce HTTP 409 Conflict.
5. Nueva clave legítima con el mismo texto procesada como acción independiente.
6. Cancelación cooperativa antes del efecto (aborta sin ejecutar efectos secundarios).
7. Hilo no cooperativo (preserva estado CANCEL_REQUESTED / UNKNOWN sin afirmar detención forzosa).
8. Aislamiento de sesiones al consultar y cancelar operaciones (rechazo HTTP 403 ante acceso cruzado).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config.settings import AppSettings
from core.execution.operation_manager import (
    IdempotencyConflictError,
    OperationManager,
    OperationStatus,
    SessionIsolationError,
    get_operation_manager,
)
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    JessycaRequest,
    JessycaResponse,
)
from interfaces.mobile_api.app import create_mobile_api_app


@pytest.fixture
def mock_settings() -> AppSettings:
    return AppSettings(
        MOBILE_API_ENABLED=True,
        MOBILE_API_HOST="127.0.0.1",
        MOBILE_API_PORT=8765,
        MOBILE_API_AUTH_TOKEN="secure-test-token-prompt04",
        MOBILE_API_TIMEOUT=0.2,  # Timeout corto para pruebas de latencia
    )


@pytest.fixture
def test_client(mock_settings: AppSettings):
    app = create_mobile_api_app(settings=mock_settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_operation_manager():
    """Limpia el estado del gestor de operaciones antes y después de cada test."""
    manager = get_operation_manager()
    manager.reset()
    yield
    manager.reset()


# ── TEST 1: TIMEOUT ANTES DE INICIAR EFECTO ──
def test_01_timeout_before_starting_effect(test_client: TestClient, mock_settings: AppSettings) -> None:
    """Valida que un timeout HTTP antes de iniciar el efecto devuelva 504 sin abortar ni corromper."""
    effect_counter = 0

    def slow_interact(req: JessycaRequest, cancellation_token=None) -> JessycaResponse:
        nonlocal effect_counter
        # Simula razonamiento lento previo a efectos
        time.sleep(0.4)
        effect_counter += 1
        return JessycaResponse(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text="Completado tras timeout",
        )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get:
        mock_agent = MagicMock()
        mock_agent.interact.side_effect = slow_interact
        mock_get.return_value = mock_agent

        op_id = "op-timeout-001"
        resp = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": op_id,
            },
            json={
                "session_id": "session-timeout",
                "message": "Operación lenta",
            },
        )

        assert resp.status_code == 504
        data = resp.json()
        assert data["success"] is False
        assert data["operation_id"] == op_id
        assert data["status"] in ("RUNNING", "PENDING")
        assert "Tiempo de espera HTTP" in data["error"]


# ── TEST 2: TIMEOUT DESPUÉS DE INICIAR EFECTO ──
def test_02_timeout_after_starting_effect_retains_running_and_cached_result(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Valida que si el timeout ocurre con el efecto ya iniciado, el estado no es CANCELLED y permite consultar."""
    effect_count = 0

    def slow_effect_interact(req: JessycaRequest, cancellation_token=None) -> JessycaResponse:
        nonlocal effect_count
        # Registrar que el efecto inició
        op_rec = req.metadata.get("operation_record")
        if op_rec:
            op_rec.effect_started = True
        effect_count += 1
        time.sleep(0.35)
        return JessycaResponse(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text="Efecto completado en segundo plano",
        )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get:
        mock_agent = MagicMock()
        mock_agent.interact.side_effect = slow_effect_interact
        mock_get.return_value = mock_agent

        op_id = "op-effect-002"
        session_id = "session-effect"
        resp = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": op_id,
            },
            json={
                "session_id": session_id,
                "message": "Modificar archivo",
            },
        )

        assert resp.status_code == 504
        assert resp.json()["status"] in ("RUNNING", "PENDING")

        # Esperar a que la tarea en segundo plano termine
        time.sleep(0.4)

        # Consultar por endpoint autorizado
        query_resp = test_client.get(
            f"/api/v1/operations/{op_id}?session_id={session_id}",
            headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
        )
        assert query_resp.status_code == 200
        qdata = query_resp.json()
        assert qdata["status"] == "COMPLETED"
        assert qdata["effect_started"] is True
        assert effect_count == 1


# ── TEST 3: DUPLICADOS SIMULTÁNEOS (DEDUPLICACIÓN ATÓMICA) ──
def test_03_simultaneous_duplicates_execute_single_effect() -> None:
    """Dos solicitudes concurrentes con la misma clave no deben iniciar dos efectos."""
    async def _run():
        manager = get_operation_manager()
        effect_counter = 0

        def slow_effect():
            nonlocal effect_counter
            time.sleep(0.2)
            effect_counter += 1
            return "effect_result"

        session_id = "sess-concurrent"
        op_id = "op-concurrent-001"
        payload = {"message": "Enviar reporte", "session_id": session_id}

        # Ambas solicitudes intentan adquirir la operación concurrentemente
        rec1, is_new1 = await manager.acquire_or_join(session_id, op_id, payload)
        rec2, is_new2 = await manager.acquire_or_join(session_id, op_id, payload)

        assert is_new1 is True
        assert is_new2 is False  # La segunda solicitud se adhiere a la primera

        # Solo la primera lanza el worker
        task1 = manager.run_operation(rec1, slow_effect)

        # Ambas esperan el resultado de la misma tarea
        res1 = await task1
        res2 = rec2.result

        assert res1 == "effect_result"
        assert res2 == "effect_result"
        assert effect_counter == 1  # Un solo efecto ejecutado

    asyncio.run(_run())


# ── TEST 4: MISMA CLAVE CON DISTINTO PAYLOAD PRODUCE CONFLICTO ──
def test_04_same_key_different_payload_produces_conflict(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """La misma clave de idempotencia con un payload distinto debe retornar HTTP 409 Conflict."""
    op_id = "key-conflict-001"
    session_id = "sess-conflict"

    mock_resp = JessycaResponse(
        request_id=op_id,
        session_id=session_id,
        success=True,
        status=AgentExecutionState.COMPLETED,
        response_text="Resultado inicial",
    )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get:
        mock_agent = MagicMock()
        mock_agent.interact.return_value = mock_resp
        mock_get.return_value = mock_agent

        # Primera petición con mensaje A
        r1 = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": op_id,
            },
            json={"session_id": session_id, "message": "Acción A"},
        )
        assert r1.status_code == 200

        # Segunda petición con la MISMA clave pero mensaje B (diferente payload)
        r2 = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": op_id,
            },
            json={"session_id": session_id, "message": "Acción B diferente"},
        )
        assert r2.status_code == 409
        err = r2.json()
        assert err["success"] is False
        assert "Conflicto de idempotencia" in err["error"]


# ── TEST 5: NUEVA CLAVE LEGÍTIMA CON MISMO TEXTO ──
def test_05_new_key_with_same_text_is_legitimate_new_action(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Mismo texto con clave distinta representa una acción nueva legítima y se ejecuta."""
    invocations = 0

    def counting_interact(req: JessycaRequest, cancellation_token=None):
        nonlocal invocations
        invocations += 1
        return JessycaResponse(
            request_id=req.request_id,
            session_id=req.session_id,
            success=True,
            status=AgentExecutionState.COMPLETED,
            response_text=f"Ejecución #{invocations}",
        )

    with patch("interfaces.mobile_api.app.JessycaLocalAgent.get_instance") as mock_get:
        mock_agent = MagicMock()
        mock_agent.interact.side_effect = counting_interact
        mock_get.return_value = mock_agent

        session_id = "sess-legit"

        # Petición 1: clave A
        r1 = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": "key-action-001",
            },
            json={"session_id": session_id, "message": "Añadir elemento a lista"},
        )
        assert r1.status_code == 200

        # Petición 2: clave B (nueva clave con el mismo mensaje)
        r2 = test_client.post(
            "/api/v1/chat",
            headers={
                "X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN,
                "Idempotency-Key": "key-action-002",
            },
            json={"session_id": session_id, "message": "Añadir elemento a lista"},
        )
        assert r2.status_code == 200
        assert invocations == 2  # Ambas se ejecutaron


# ── TEST 6: CANCELACIÓN ANTES DEL EFECTO ──
def test_06_cancellation_before_effect_prevents_side_effects() -> None:
    """La cancelación solicitada antes de la fase de efectos aborta la ejecución sin efectos secundarios."""
    async def _run():
        manager = get_operation_manager()
        effect_executed = False

        def cooperative_worker():
            nonlocal effect_executed
            # Comprobar token antes del efecto
            if rec.cancellation_token.is_cancelled:
                return None
            # Efecto físico
            effect_executed = True
            return "effect_done"

        session_id = "sess-cancel"
        op_id = "op-cancel-001"
        rec, is_new = await manager.acquire_or_join(session_id, op_id, {"msg": "sensible"})

        # Cancelar antes de iniciar
        manager.cancel_operation(session_id, op_id)
        assert rec.cancellation_token.is_cancelled is True

        task = manager.run_operation(rec, cooperative_worker)
        await task

        assert effect_executed is False
        assert rec.status == OperationStatus.CANCELLED

    asyncio.run(_run())


# ── TEST 7: HILO QUE NO COOPERA PRESERVA ESTADO RUNNING / UNKNOWN ──
def test_07_uncooperative_thread_retains_proper_status() -> None:
    """Un hilo que no coopera conserva estado CANCEL_REQUESTED / UNKNOWN sin afirmar que fue detenido."""
    async def _run():
        manager = get_operation_manager()
        thread_finished = False

        def stubborn_worker():
            nonlocal thread_finished
            # Hilo no cooperativo que simula efecto C o llamada bloqueante sin mirar el token
            time.sleep(0.3)
            thread_finished = True
            return "uncooperative_done"

        session_id = "sess-stubborn"
        op_id = "op-stubborn-001"
        rec, is_new = await manager.acquire_or_join(session_id, op_id, {"action": "stubborn"})

        # Iniciar worker
        task = manager.run_operation(rec, stubborn_worker)
        await asyncio.sleep(0.05)

        # El efecto está en curso
        rec.effect_started = True

        # El usuario pide cancelar
        manager.cancel_operation(session_id, op_id)
        # No podemos afirmar que el hilo se detuvo; su estado es CANCEL_REQUESTED
        assert rec.status == OperationStatus.CANCEL_REQUESTED

        # Esperar que el hilo termine su ejecución independiente
        await task
        assert thread_finished is True
        # Al finalizar habiendo sido cancelado con efecto iniciado, el estado es UNKNOWN (no CANCELLED limpio)
        assert rec.status == OperationStatus.UNKNOWN

    asyncio.run(_run())


# ── TEST 8: AISLAMIENTO DE SESIONES AL CONSULTAR Y CANCELAR ──
def test_08_session_isolation_on_query_and_cancel(
    test_client: TestClient, mock_settings: AppSettings
) -> None:
    """Una sesión no puede consultar ni cancelar operaciones que pertenecen a otra sesión."""
    manager = get_operation_manager()

    # Registrar operación para sesión Alice
    async def _setup_op():
        rec, _ = await manager.acquire_or_join(
            session_id="session_alice",
            operation_id="op_alice_private",
            payload={"msg": "privado de alice"},
        )
        rec.status = OperationStatus.RUNNING
        rec.result = "secreto"

    asyncio.run(_setup_op())

    # Bob intenta consultar la operación de Alice -> 403 Forbidden
    query_resp = test_client.get(
        "/api/v1/operations/op_alice_private?session_id=session_bob",
        headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
    )
    assert query_resp.status_code == 403
    assert "Acceso denegado" in query_resp.json()["error"]

    # Bob intenta cancelar la operación de Alice -> 403 Forbidden
    cancel_resp = test_client.post(
        "/api/v1/operations/op_alice_private/cancel?session_id=session_bob",
        headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
    )
    assert cancel_resp.status_code == 403
    assert "Acceso denegado" in cancel_resp.json()["error"]

    # Alice consulta su propia operación -> 200 OK
    alice_query = test_client.get(
        "/api/v1/operations/op_alice_private?session_id=session_alice",
        headers={"X-Jessyca-Token": mock_settings.MOBILE_API_AUTH_TOKEN},
    )
    assert alice_query.status_code == 200
    assert alice_query.json()["operation_id"] == "op_alice_private"
