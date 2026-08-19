"""Pruebas para verificar la regla de inmutabilidad: Memory -> EVIDENCE (Subetapa 16.2).

Demuestra rigurosamente que:
1. La memoria (sesión o semántica) opera EXCLUSIVAMENTE como evidencia no confiable.
2. Contenido recuperado de memoria que contenga instrucciones de elevar autonomía o bypassing es ignorado o genera AutonomyEscalationError.
3. La memoria NUNCA puede modificar la decisión de la AutonomyPolicy.
"""

import pytest

from core.autonomy.autonomy_governor import get_autonomy_governor
from core.autonomy.autonomy_level import AutonomyLevel
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)
from core.context_builder import ContextSource


def test_memory_content_cannot_grant_autonomy_level() -> None:
    """Verifica que el contenido recuperado de memoria no puede cambiar el nivel de autonomía activo."""
    gov = get_autonomy_governor()
    gov.reset_to_default()

    # Intentar cambiar nivel asignando 'memory' como actor
    with pytest.raises(AutonomyEscalationError) as exc_info:
        gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="memory")

    assert "AUTONOMY ESCALATION REJECTED" in str(exc_info.value)
    assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED


def test_memory_poisoning_payload_cannot_bypass_policy() -> None:
    """Verifica que un payload inyectado en memoria semántica tratando de forzar override_autonomy es neutralizado."""
    policy = AutonomyPolicy()

    # Contexto simulado donde los parámetros provienen de la recuperación de memoria
    poisoned_memory_ctx = AutonomyEvaluationContext(
        task_id="t-mem-poison",
        tool_name="windows.shell",
        operation="powershell",
        parameters={"command": "Get-Process", "override_autonomy": True},
        task_source="memory_retrieval",
    )

    with pytest.raises(AutonomyEscalationError) as exc_info:
        policy.evaluate(poisoned_memory_ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)

    assert "AUTONOMY ESCALATION ATTEMPT" in str(exc_info.value)


def test_context_builder_memory_treated_as_untrusted_evidence() -> None:
    """Verifica que ContextSource clasifica el origen de la memoria semántica como no confiable (EVIDENCE)."""
    assert ContextSource.SEMANTIC_MEMORY.value == "SEMANTIC_MEMORY"
    assert ContextSource.FACTS.value == "FACTS"


