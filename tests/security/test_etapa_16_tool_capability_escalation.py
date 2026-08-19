"""Etapa 16.0 — Vector 04: Tool Capability Escalation Audit.

Verifica que CapabilityRegistry y el sistema de capabilities resisten:
- Registro de capabilities duplicadas o no autorizadas
- Lock bypass del registry
- H-01: Risk inference por nombre de herramienta
- Escalada de operaciones no declaradas
"""

from __future__ import annotations

import pytest

from core.capability_registry import CapabilityRegistry, get_capability_registry
from core.capabilities import (
    CapabilityOperation,
    CapabilitySource,
    ToolCapability,
)
from core.exceptions import SecurityValidationError
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata


def _make_capability(
    tool_name: str,
    cap_id: str,
    source: CapabilitySource = CapabilitySource.SYSTEM,
    is_immutable: bool = True,
) -> ToolCapability:
    return ToolCapability(
        capability_id=cap_id,
        tool_name=tool_name,
        version="1.0.0",
        source=source,
        is_immutable=is_immutable,
        operations=[
            CapabilityOperation(
                name="execute",
                description="Execute the tool",
                risk_level=SecurityLevel.SAFE,
            )
        ],
    )


class TestCapabilityRegistryLockdown:
    """Tests de bloqueo del CapabilityRegistry."""

    def test_locked_registry_rejects_new_registration(self) -> None:
        """Tras lock_registry(), no se pueden registrar nuevas capabilities."""
        registry = CapabilityRegistry()
        cap = _make_capability("locked_tool", "cap-locked-001")
        registry.register(cap)
        registry.lock_registry()

        new_cap = _make_capability("new_tool_after_lock", "cap-locked-002")
        with pytest.raises(SecurityValidationError, match="sellado"):
            registry.register(new_cap)

    def test_locked_registry_rejects_unregistration(self) -> None:
        """Tras lock_registry(), no se pueden eliminar capabilities."""
        registry = CapabilityRegistry()
        cap = _make_capability("removable_tool", "cap-remove-001", is_immutable=False)
        registry.register(cap)
        registry.lock_registry()

        with pytest.raises(SecurityValidationError, match="sellado"):
            registry.unregister("cap-remove-001")

    def test_immutable_capability_cannot_be_removed(self) -> None:
        """Capability inmutable no puede ser eliminada aunque el registry no esté bloqueado."""
        registry = CapabilityRegistry()
        cap = _make_capability("immutable_tool", "cap-immut-001", is_immutable=True)
        registry.register(cap)

        with pytest.raises(SecurityValidationError, match="[Ii]nmutable|[Ii]nviolabilidad"):
            registry.unregister("cap-immut-001")

    def test_duplicate_tool_registration_rejected(self) -> None:
        """Registrar la misma herramienta dos veces debe ser rechazado."""
        registry = CapabilityRegistry()
        cap1 = _make_capability("dup_tool", "cap-dup-001")
        cap2 = _make_capability("dup_tool", "cap-dup-002")  # mismo tool_name

        registry.register(cap1)
        with pytest.raises(SecurityValidationError):
            registry.register(cap2)

    def test_duplicate_capability_id_rejected(self) -> None:
        """Registrar capabilities con el mismo ID debe ser rechazado."""
        registry = CapabilityRegistry()
        cap1 = _make_capability("tool_a", "cap-same-id")
        cap2 = _make_capability("tool_b", "cap-same-id")  # mismo ID

        registry.register(cap1)
        with pytest.raises(SecurityValidationError):
            registry.register(cap2)


class TestToolNameRiskInferenceH01:
    """AUDIT H-01: Risk inference por nombre de herramienta en RiskEngine."""

    def setup_method(self) -> None:
        self.engine = RiskEngine()

    def test_safe_named_tool_gets_safe_risk(self) -> None:
        """Herramienta con nombre 'safe' debe obtener riesgo SAFE."""
        ctx = SecurityContext(user="user", tool_name="safe_reader_tool", parameters={})
        meta = ToolSecurityMetadata(tool_name="safe_reader_tool", category="test", risk_level=SecurityLevel.SAFE)
        assessment = self.engine.evaluate_risk(ctx, meta)
        risk_val = str(getattr(assessment.risk_level, "value", assessment.risk_level)).upper()
        assert risk_val in ("SAFE", "READ_ONLY", "WARNING"), (
            f"Herramienta 'safe_reader_tool' obtuvo riesgo inesperado: {risk_val}"
        )

    def test_dangerous_keyword_in_name_elevates_risk(self) -> None:
        """H-01 AUDIT: Nombre con 'delete' debe elevar riesgo automáticamente."""
        ctx = SecurityContext(user="user", tool_name="delete_records", parameters={})
        assessment = self.engine.evaluate_risk(ctx)
        risk_val = str(getattr(assessment.risk_level, "value", assessment.risk_level)).upper()
        # Se espera DANGEROUS o CRITICAL por inferencia de nombre
        assert risk_val in ("DANGEROUS", "CRITICAL"), (
            f"[AUDIT-H01] Herramienta 'delete_records' obtuvo riesgo={risk_val}. "
            "La inferencia por nombre debería elevar a DANGEROUS."
        )

    def test_safe_named_dangerous_operation_audit(self) -> None:
        """H-01 CRITICAL AUDIT: Tool con nombre 'safe' pero operación peligrosa.

        Si el nombre es 'read_safe_helper' pero realiza delete_all, el RiskEngine
        sólo puede detectarlo si los parámetros/operación revelan el peligro.
        """
        ctx = SecurityContext(
            user="user",
            tool_name="read_safe_helper",
            parameters={"recursive": True, "action": "delete"},
        )
        assessment = self.engine.evaluate_risk(ctx)
        risk_val = str(getattr(assessment.risk_level, "value", assessment.risk_level)).upper()

        # Si el riesgo es SAFE/READ_ONLY, el nombre engañó al RiskEngine
        if risk_val in ("SAFE", "READ_ONLY"):
            pytest.xfail(
                "[AUDIT-H01-CONFIRMED] Tool named 'read_safe_helper' con parámetros peligrosos "
                f"(recursive=True, action=delete) obtuvo riesgo={risk_val}. "
                "El nombre de la herramienta puede engañar al RiskEngine. "
                "La evaluación de riesgo debe basarse en metadatos declarados, no inferencia de nombre."
            )

    def test_cmd_keyword_elevates_to_critical(self) -> None:
        """'cmd' en nombre de herramienta debe elevar a CRITICAL."""
        ctx = SecurityContext(user="user", tool_name="run_cmd_wrapper", parameters={})
        assessment = self.engine.evaluate_risk(ctx)
        risk_val = str(getattr(assessment.risk_level, "value", assessment.risk_level)).upper()
        assert risk_val in ("CRITICAL", "DANGEROUS"), (
            f"[AUDIT-H01] 'cmd' en nombre no elevó a CRITICAL/DANGEROUS. Obtuvo: {risk_val}"
        )


class TestCapabilityEscalationViaPlugin:
    """Tests de escalada de capability vía operaciones no declaradas."""

    def test_unregistered_tool_has_no_capability(self) -> None:
        """Herramienta no registrada no debe tener capability."""
        registry = CapabilityRegistry()
        result = registry.get_tool("nonexistent_tool_xyz")
        assert result is None

    def test_operation_lookup_for_unregistered_tool(self) -> None:
        """Operación en herramienta no registrada debe retornar None."""
        registry = CapabilityRegistry()
        result = registry.get_operation("nonexistent_tool", "execute")
        assert result is None

    def test_fingerprint_for_unknown_operation_is_none(self) -> None:
        """Fingerprint para operación desconocida debe retornar None (no error)."""
        registry = CapabilityRegistry()
        result = registry.get_fingerprint("unknown_tool", "unknown_op")
        assert result is None

    def test_thread_safe_concurrent_reads(self) -> None:
        """Lecturas concurrentes del registry no deben producir errores."""
        import threading
        registry = CapabilityRegistry()
        cap = _make_capability("concurrent_tool", "cap-concurrent-001")
        registry.register(cap)

        errors: list[Exception] = []

        def read_registry() -> None:
            try:
                registry.get_tool("concurrent_tool")
                registry.list_tools()
                registry.has_tool("concurrent_tool")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_registry) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, (
            f"[AUDIT] Lecturas concurrentes del CapabilityRegistry produjeron errores: {errors}"
        )
