"""Tests for ARE Controlled Mode Behavior."""

import pytest
from core.are.models import ARERuntimeMode
from core.are.runtime import ARERuntime


def test_controlled_mode_is_complex_task():
    rt = ARERuntime(mode=ARERuntimeMode.CONTROLLED)

    # Complex prompts
    assert rt.is_complex_task("investiga el mercado y luego genera un reporte", "research", {}) is True
    assert rt.is_complex_task("convierte el documento a markdown y después analiza el texto", "convert", {}) is True
    assert rt.is_complex_task("ejecuta agentes paralelos para compilar", "agent_orchestration", {}) is True
    assert rt.is_complex_task("haz una búsqueda primero y luego guarda los resultados", "multistep_research", {}) is True

    # Simple prompts
    assert rt.is_complex_task("abre notepad", "open_application", {}) is False
    assert rt.is_complex_task("qué hora es", "general_query", {}) is False
    assert rt.is_complex_task("cuánto es 5 + 5", "math_calculation", {}) is False


def test_controlled_mode_disabled_blocks_execution():
    rt = ARERuntime(mode=ARERuntimeMode.DISABLED)
    resp = rt.execute_complex_task(
        agent=None,
        req=None,
        goal="hacer algo complejo",
    )
    assert resp.success is False
    assert "ARE Runtime is DISABLED" in resp.response_text
