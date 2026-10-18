"""Suite de Pruebas Comparativas y Validación Agéntica (tests/intent/test_sai_intent_benchmark.py).

Valida los 10 criterios de la auditoría JESSYCA 4.0:
1. Preguntas generales sin invocar herramientas.
2. Investigación web desacoplada.
3. Reproducción multimedia sin colisiones.
4. Automatización de aplicaciones de Windows.
5. Instrucciones compuestas de varios pasos (Multi-Step Plan).
6. Referencias anafóricas y correferencias ("abre eso").
7. Integración de memoria contextual previa ("lo que investigaste").
8. Reducción de contexto por Progressive Tool Loading (<500 tokens).
9. Compatibilidad hacia atrás con el contrato de JessycaLocalAgent.
10. Protocolo desacoplado de escritorio y seguridad de Failsafe.
"""

from __future__ import annotations

import pytest

from core.desktop.driver_protocol import (
    DesktopActionResult,
    DesktopDriverProtocol,
    NativeWindowsDriver,
)
from core.intent.models import (
    IntentType,
    PlannedActionStep,
    UserGoalInterpretation,
)
from core.intent.progressive_catalog import ProgressiveToolCatalog
from core.intent.sai_intent_engine import SaiIntentEngine


@pytest.fixture
def engine() -> SaiIntentEngine:
    return SaiIntentEngine()


def test_01_pure_conversation(engine: SaiIntentEngine) -> None:
    """Valida que consultas conceptuales no invoquen herramientas innecesarias."""
    res = engine.interpret("¿Cuál es la diferencia entre un proceso y un hilo?")
    assert res.intent_type == IntentType.CONVERSATION
    assert len(res.steps) == 0
    assert not res.is_executable

    legacy_intent, legacy_params, is_ambig = res.to_legacy_tuple()
    assert legacy_intent == "general_query"
    assert not is_ambig


def test_02_web_research_decomposition(engine: SaiIntentEngine) -> None:
    """Valida que una orden de investigación seleccione browser.search de forma limpia."""
    res = engine.interpret("Investiga en internet sobre computación cuántica")
    assert res.is_executable
    assert any(s.skill_name == "browser.search" for s in res.steps)
    step = next(s for s in res.steps if s.skill_name == "browser.search")
    assert "computación cuántica" in step.parameters.get("query", "").lower()


def test_03_multimedia_playback(engine: SaiIntentEngine) -> None:
    """Valida apertura y búsqueda en YouTube coordinadas sin romper la intención."""
    res = engine.interpret("Abre YouTube y pon música de Mozart")
    assert res.is_executable
    assert any(s.skill_name == "browser.youtube" for s in res.steps)
    step = next(s for s in res.steps if s.skill_name == "browser.youtube")
    assert "mozart" in step.parameters.get("query", "").lower()
    assert step.parameters.get("autoplay") is True


def test_04_app_automation(engine: SaiIntentEngine) -> None:
    """Valida apertura de Bloc de notas con parámetros de texto estructurados."""
    res = engine.interpret("Abre el Bloc de notas y escribe reunión a las tres")
    assert res.is_executable
    assert any(s.skill_name == "windows.apps" for s in res.steps)
    step = next(s for s in res.steps if s.skill_name == "windows.apps")
    assert step.parameters.get("app_name") == "notepad"


def test_05_compound_multi_step_order(engine: SaiIntentEngine) -> None:
    """CRÍTICO: Valida descomposición de orden compuesta de 3 pasos que fallaba en regex."""
    user_input = "Baja el volumen al 30%, abre Chrome y busca información sobre computación cuántica"
    res = engine.interpret(user_input)

    assert res.intent_type == IntentType.MULTI_STEP_PLAN
    assert res.is_multistep
    assert len(res.steps) >= 3

    # Paso 1: Audio
    assert res.steps[0].skill_name == "windows.audio"
    assert res.steps[0].parameters.get("nivel") == 30 or res.steps[0].parameters.get("delta") == -10

    # Paso 2: Chrome
    assert res.steps[1].skill_name == "windows.apps"
    assert res.steps[1].parameters.get("app_name") == "chrome"

    # Paso 3: Búsqueda web
    assert res.steps[2].skill_name == "browser.search"
    assert "computación cuántica" in res.steps[2].parameters.get("query", "").lower()

    # Compatibilidad con contrato legado
    legacy_intent, legacy_params, _ = res.to_legacy_tuple()
    assert "__multistep_plan__" in legacy_params
    assert len(legacy_params["__multistep_plan__"]) >= 3


def test_06_conversational_coreference_eso(engine: SaiIntentEngine) -> None:
    """Valida resolución de pronombres demostrativos ("abre eso" -> app previa)."""
    context = {"last_target": "calc"}
    res = engine.interpret("Abre eso", session_context=context)

    assert res.is_executable
    assert any(s.skill_name == "windows.apps" for s in res.steps)
    step = next(s for s in res.steps if s.skill_name == "windows.apps")
    assert step.parameters.get("app_name") == "calc"
    assert res.resolved_entities.get("resolved_target") == "calc"


def test_07_conversational_coreference_investigation_summary(engine: SaiIntentEngine) -> None:
    """Valida inyección del resumen investigado en la acción posterior de escritura."""
    resumen_previo = "Resumen técnico: Los modelos de código optimizan la productividad un 40%."
    context = {"last_investigation_summary": resumen_previo}
    
    res = engine.interpret("Abre el Bloc de notas y escribe lo que investigaste", session_context=context)
    assert res.is_executable
    step = next(s for s in res.steps if s.skill_name == "windows.apps")
    assert step.parameters.get("text_to_write") == resumen_previo


def test_08_progressive_tool_catalog_reduction() -> None:
    """Valida el patrón Progressive Tool Loading de SAI: pre-selección de dominios mínimos."""
    domains = ProgressiveToolCatalog.preselect_domains("Baja el volumen y pon música en YouTube")
    assert "system" in domains  # Por volumen
    assert "browser" in domains  # Por YouTube
    assert "files" not in domains  # No carga 10 herramientas de archivos innecesarias
    assert "documents" not in domains  # No carga Word/Excel/PDF

    tools_desc = ProgressiveToolCatalog.get_tool_descriptions(domains)
    assert "windows.audio" in tools_desc
    assert "browser.youtube" in tools_desc
    assert "files.copy" not in tools_desc
    assert len(tools_desc) < 600  # Menos de 600 caracteres (<150 tokens)


def test_09_legacy_compatibility_contract() -> None:
    """Garantiza que la tupla exportada cumpla con lo que espera JessycaLocalAgent."""
    plan = UserGoalInterpretation(
        intent_type=IntentType.SINGLE_ACTION,
        goal_summary="Subir volumen",
        spoken_feedback="Listo",
        steps=(
            PlannedActionStep(
                skill_name="windows.audio",
                parameters={"accion": "establecer", "delta": 10},
                description="Subir volumen maestro",
            ),
        ),
    )
    intent, params, is_ambig = plan.to_legacy_tuple()
    assert intent == "control_audio"
    assert params["delta"] == 10
    assert is_ambig is False


def test_10_desktop_driver_protocol_safety() -> None:
    """Verifica el protocolo desacoplado y la presencia del Failsafe activo."""
    driver = NativeWindowsDriver()
    assert isinstance(driver, DesktopDriverProtocol)

    import pyautogui
    assert pyautogui.FAILSAFE is True  # Invariante de seguridad confirmada

    # Prueba no invasiva de captura in-memory
    screen_bytes = driver.capture_screen()
    assert len(screen_bytes) > 100
    assert screen_bytes[:4] == b"\x89PNG"
