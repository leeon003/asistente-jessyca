"""Tests para el control de duplicación de apertura de aplicaciones (Corrección 75.1-B).

Cubre los 7 tests requeridos:
- TEST 1: Una orden -> launch_app() == 1 llamada
- TEST 2: Dos órdenes diferentes -> launch_app() == 2 llamadas
- TEST 3: Evento duplicado -> launch_app() == 1 llamada real
- TEST 4: Mismo action_id -> 1 ejecución real
- TEST 5: Nuevo action_id -> 2 ejecuciones
- TEST 6: Cierre de aplicación ("cierra el bloc de notas")
- TEST 7: Múltiples aplicaciones (Chrome, CMD, WhatsApp, Bloc de notas)
"""

from __future__ import annotations

import asyncio

from core.application_session_manager import ApplicationSessionManager, FakeApplicationAdapter
from core.bus import EventBus
from core.events.base import ActionProposed
from core.execution.verification_event_adapter import ActionVerificationAdapter
from core.state.machine import StateMachine
from skills.apps_skill import WindowsAppsSkill


class TrackingFakeAdapter(FakeApplicationAdapter):
    """Adapter simulado con contador de llamadas a launch."""

    def __init__(self) -> None:
        super().__init__()
        self.launch_call_count = 0

    def launch(self, path: str, args: tuple[str, ...] = ()) -> int:
        self.launch_call_count += 1
        return super().launch(path, args)


def test_1_una_orden() -> None:
    """TEST 1 — UNA ORDEN: Input: 'abre el bloc de notas' -> launch_app() == 1 llamada."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    skill = WindowsAppsSkill(session_manager=mgr)

    res = skill.ejecutar({"accion": "abrir", "nombre": "bloc de notas", "action_id": "ord-001"})

    assert res.get("exito") is True
    assert mgr.get_call_count("notepad") == 1
    assert mgr.get_execution_count("notepad") == 1
    assert adapter.launch_call_count == 1


def test_2_dos_ordenes_diferentes() -> None:
    """TEST 2 — DOS ÓRDENES DIFERENTES: Dos órdenes explícitas -> launch_app() == 2 llamadas."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    skill = WindowsAppsSkill(session_manager=mgr)

    # Primera orden del usuario
    res1 = skill.ejecutar({"accion": "abrir", "nombre": "bloc de notas", "action_id": "ord-user-001"})
    # Segunda orden explícita del usuario
    res2 = skill.ejecutar({"accion": "abrir", "nombre": "bloc de notas", "action_id": "ord-user-002"})

    assert res1.get("exito") is True
    assert res2.get("exito") is True
    assert mgr.get_call_count("notepad") == 2
    assert mgr.get_execution_count("notepad") == 2
    assert adapter.launch_call_count == 2
    assert len(adapter.launch_history) == 2


def test_3_evento_duplicado() -> None:
    """TEST 3 — EVENTO DUPLICADO: Enviar dos veces accidentalmente el mismo evento/action_id."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    skill = WindowsAppsSkill(session_manager=mgr)

    event1 = ActionProposed(
        action_name="windows.apps",
        parameters={"accion": "abrir", "nombre": "bloc de notas", "action_id": "evt-dup-100"},
        action_id="evt-dup-100",
    )
    event2 = ActionProposed(
        action_name="windows.apps",
        parameters={"accion": "abrir", "nombre": "bloc de notas", "action_id": "evt-dup-100"},
        action_id="evt-dup-100",
    )

    res1 = skill.ejecutar(event1.parameters)
    res2 = skill.ejecutar(event2.parameters)

    assert res1.get("exito") is True
    assert res2.get("exito") is True
    # Idempotencia activada: solo 1 ejecución real en el SO
    assert mgr.get_execution_count("notepad") == 1
    assert adapter.launch_call_count == 1
    assert len(adapter.launch_history) == 1


def test_3_b_action_verification_adapter_deduplication() -> None:
    """Verifica que ActionVerificationAdapter descarte eventos ActionProposed con action_id duplicado."""
    async def _run() -> None:
        bus = EventBus()
        sm = StateMachine()
        exec_count = 0

        def mock_exec(name: str, params: dict) -> dict:
            nonlocal exec_count
            exec_count += 1
            return {"exito": True}

        async with ActionVerificationAdapter(
            event_bus=bus,
            state_machine=sm,
            executor_fn=mock_exec,
        ):
            evt1 = ActionProposed(
                action_name="windows.apps",
                parameters={"accion": "abrir", "nombre": "bloc de notas"},
                action_id="dup-act-999",
            )
            evt2 = ActionProposed(
                action_name="windows.apps",
                parameters={"accion": "abrir", "nombre": "bloc de notas"},
                action_id="dup-act-999",
            )
            await bus.publish(evt1)
            await bus.publish(evt2)

        assert exec_count == 1

    asyncio.run(_run())


def test_4_mismo_action_id() -> None:
    """TEST 4 — MISMO ACTION_ID: Procesar dos veces la misma acción con action_id = ABC -> 1 ejecución real."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)

    sess1 = mgr.launch_app("bloc de notas", action_id="ABC")
    sess2 = mgr.launch_app("bloc de notas", action_id="ABC")

    assert sess1.session_id == sess2.session_id
    assert mgr.get_call_count("notepad") == 2
    assert mgr.get_execution_count("notepad") == 1
    assert adapter.launch_call_count == 1
    assert len(adapter.launch_history) == 1


def test_5_nuevo_action_id() -> None:
    """TEST 5 — NUEVO ACTION_ID: Procesar action_id = ABC y después action_id = XYZ -> 2 ejecuciones."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)

    sess1 = mgr.launch_app("bloc de notas", action_id="ABC")
    sess2 = mgr.launch_app("bloc de notas", action_id="XYZ")

    assert sess1.session_id != sess2.session_id
    assert mgr.get_execution_count("notepad") == 2
    assert adapter.launch_call_count == 2
    assert len(adapter.launch_history) == 2


def test_6_cierre() -> None:
    """TEST 6 — CIERRE: Verificar que 'cierra el bloc de notas' continúa funcionando."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    skill = WindowsAppsSkill(session_manager=mgr)

    # 1. Abrir Notepad
    res_open = skill.ejecutar({"accion": "abrir", "nombre": "bloc de notas", "action_id": "open-01"})
    assert res_open.get("exito") is True
    assert mgr.find_existing_session("notepad") is not None

    # 2. Cerrar Notepad
    res_close = skill.ejecutar({"accion": "cerrar", "nombre": "bloc de notas"})
    assert res_close.get("exito") is True
    assert "cerr" in res_close.get("mensaje", "").lower()
    assert mgr.find_existing_session("notepad") is None


def test_7_otras_aplicaciones() -> None:
    """TEST 7 — OTRAS APLICACIONES: Probar Chrome/Edge, CMD, WhatsApp, Bloc de notas."""
    adapter = TrackingFakeAdapter()
    mgr = ApplicationSessionManager(adapter=adapter)
    skill = WindowsAppsSkill(session_manager=mgr)

    apps_to_test = [
        ("chrome", "chrome"),
        ("cmd", "cmd"),
        ("whatsapp", "whatsapp"),
        ("bloc de notas", "notepad"),
    ]

    for user_name, expected_app_id in apps_to_test:
        # Cada orden individual produce exactamente 1 ejecución
        res = skill.ejecutar({
            "accion": "abrir",
            "nombre": user_name,
            "action_id": f"act-{expected_app_id}-001",
        })
        assert res.get("exito") is True, f"Fallo al abrir {user_name}: {res}"
        assert mgr.get_execution_count(expected_app_id) == 1

        # Reintento accidental con mismo action_id -> 0 ejecuciones extra
        res_dup = skill.ejecutar({
            "accion": "abrir",
            "nombre": user_name,
            "action_id": f"act-{expected_app_id}-001",
        })
        assert res_dup.get("exito") is True
        assert mgr.get_execution_count(expected_app_id) == 1

        # Nueva orden explícita con nuevo action_id -> exactamente 1 ejecución más
        res_new = skill.ejecutar({
            "accion": "abrir",
            "nombre": user_name,
            "action_id": f"act-{expected_app_id}-002",
        })
        assert res_new.get("exito") is True
        assert mgr.get_execution_count(expected_app_id) == 2
