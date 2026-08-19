"""Etapa 16.2 — Tests Completos del Autonomy Level Model.

Verifica:
1. CapabilityAutonomyProfile — modelo inmutable, serialización, invariantes de diseño
2. CapabilityAutonomyRegistry — catálogo, sólo lectura, lookups, estadísticas
3. AutonomyPolicy integrada con registry — flujo de profiles declarados vs fallback
4. Invariante de nivel mínimo — current_level < min_level → DENY
5. AutonomyGovernor — UNAUTHORIZED_ACTORS, get_profile_for_action, get_status extendido
6. 12 tests de escalation (LLM, plugin, scheduler, memory, workflow, parámetros maliciosos, etc.)
"""

from __future__ import annotations

import threading

import pytest

from core.autonomy.autonomy_governor import AutonomyGovernor
from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.autonomy_policy import (
    AutonomyEscalationError,
    AutonomyEvaluationContext,
    AutonomyPolicy,
)
from core.autonomy.capability_autonomy_profile import (
    AuditRequirement,
    CapabilityAutonomyProfile,
    ConfirmationRequirement,
    ReversibilityClass,
)
from core.autonomy.capability_autonomy_registry import (
    CapabilityAutonomyRegistry,
    CapabilityProfileNotFoundError,
    CapabilityRegistryLockedError,
    get_capability_autonomy_registry,
)
from core.autonomy.autonomy_decision import AutonomyDecisionValue


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_profile(
    key: str = "test.capability",
    min_level: AutonomyLevel = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
    risk: TaskActionRisk = TaskActionRisk.LOW_RISK,
    confirmation: ConfirmationRequirement = ConfirmationRequirement.NEVER,
    reversibility: ReversibilityClass = ReversibilityClass.REVERSIBLE,
    audit: AuditRequirement = AuditRequirement.BASIC,
) -> CapabilityAutonomyProfile:
    return CapabilityAutonomyProfile(
        capability_key=key,
        minimum_autonomy_level=min_level,
        risk_level=risk,
        requires_confirmation=confirmation,
        reversibility=reversibility,
        audit_requirement=audit,
        description="Test capability",
    )


def _ctx(
    tool: str,
    op: str,
    source: str = "user_request",
    is_scheduled: bool = False,
    is_plugin: bool = False,
    params: dict | None = None,
) -> AutonomyEvaluationContext:
    return AutonomyEvaluationContext(
        task_id="test-task",
        tool_name=tool,
        operation=op,
        parameters=params or {},
        task_source=source,
        is_scheduled=is_scheduled,
        is_plugin=is_plugin,
    )


def _fresh_registry() -> CapabilityAutonomyRegistry:
    """Crea un registry fresco sin el catálogo por defecto, para tests aislados."""
    return CapabilityAutonomyRegistry(preload_defaults=False)


def _fresh_policy(registry: CapabilityAutonomyRegistry) -> AutonomyPolicy:
    return AutonomyPolicy(capability_registry=registry)


# ─────────────────────────────────────────────────────────────────────────────
# Sección 1 — CapabilityAutonomyProfile
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityAutonomyProfile:
    """Tests del modelo CapabilityAutonomyProfile."""

    def test_profile_is_frozen(self) -> None:
        """El perfil debe ser inmutable (frozen dataclass)."""
        profile = _make_profile()
        with pytest.raises((AttributeError, TypeError)):
            profile.capability_key = "modified"  # type: ignore[misc]

    def test_to_dict_contains_all_fields(self) -> None:
        """to_dict() debe incluir todos los campos relevantes."""
        profile = _make_profile()
        d = profile.to_dict()
        required_keys = {
            "capability_key", "minimum_autonomy_level", "minimum_autonomy_level_value",
            "risk_level", "requires_confirmation", "reversibility",
            "audit_requirement", "emergency_stop_applicable", "description", "category",
        }
        assert required_keys.issubset(d.keys())

    def test_critical_profile_requires_confirmation_always(self) -> None:
        """Un perfil CRITICAL con C_ALWAYS debe requerir confirmación en cualquier nivel."""
        profile = _make_profile(
            risk=TaskActionRisk.CRITICAL,
            confirmation=ConfirmationRequirement.ALWAYS,
        )
        for level in AutonomyLevel:
            assert profile.is_confirmation_required_for_level(level) is True, (
                f"CRITICAL+ALWAYS debe requerir confirmación en {level.label}"
            )

    def test_read_only_profile_never_requires_confirmation(self) -> None:
        """Un perfil READ_ONLY con C_NEVER no debe requerir confirmación."""
        profile = _make_profile(
            risk=TaskActionRisk.READ_ONLY,
            confirmation=ConfirmationRequirement.NEVER,
        )
        for level in AutonomyLevel:
            assert profile.is_confirmation_required_for_level(level) is False

    def test_level_sufficient_logic(self) -> None:
        """is_level_sufficient() debe funcionar para cada nivel."""
        profile = _make_profile(min_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED)
        # Niveles suficientes
        assert profile.is_level_sufficient(AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED)
        assert profile.is_level_sufficient(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
        # Niveles insuficientes
        assert not profile.is_level_sufficient(AutonomyLevel.LEVEL_0_OBSERVE)
        assert not profile.is_level_sufficient(AutonomyLevel.LEVEL_1_SUGGEST)
        assert not profile.is_level_sufficient(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)

    def test_tamper_evident_audit_flag(self) -> None:
        """requires_tamper_evident_audit() debe retornar True sólo para TAMPER_EVIDENT."""
        te = _make_profile(audit=AuditRequirement.TAMPER_EVIDENT)
        basic = _make_profile(audit=AuditRequirement.BASIC)
        assert te.requires_tamper_evident_audit() is True
        assert basic.requires_tamper_evident_audit() is False

    def test_when_threshold_confirmation_logic(self) -> None:
        """WHEN_ABOVE_THRESHOLD debe requerir confirmación si nivel actual < nivel mínimo."""
        profile = _make_profile(
            min_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
            confirmation=ConfirmationRequirement.WHEN_ABOVE_THRESHOLD,
        )
        # Nivel insuficiente → confirmación requerida
        assert profile.is_confirmation_required_for_level(AutonomyLevel.LEVEL_0_OBSERVE) is True
        assert profile.is_confirmation_required_for_level(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION) is True
        # Nivel suficiente → no requiere confirmación
        assert profile.is_confirmation_required_for_level(AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED) is False
        assert profile.is_confirmation_required_for_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY) is False


# ─────────────────────────────────────────────────────────────────────────────
# Sección 2 — CapabilityAutonomyRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestCapabilityAutonomyRegistry:
    """Tests del CapabilityAutonomyRegistry."""

    def test_default_catalog_loaded(self) -> None:
        """El catálogo por defecto debe tener al menos 40 perfiles."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        caps = registry.list_capabilities()
        assert len(caps) >= 40, f"Catálogo tiene sólo {len(caps)} perfiles."

    def test_catalog_contains_key_capabilities(self) -> None:
        """Capabilities críticas del sistema deben estar en el catálogo."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        required_capabilities = [
            "filesystem.read",
            "document.create",
            "message.send",
            "windows.shell.cmd",
            "windows.shell.powershell",
            "system.registry_write",
            "system.software_install",
            "memory.read",
            "scheduler.create",
            "browser.navigate",
            "desktop.click",
            "autonomy.query_level",
        ]
        for cap in required_capabilities:
            assert registry.get_profile(cap) is not None, (
                f"Capability '{cap}' no está en el catálogo oficial."
            )

    def test_filesystem_read_is_level_0(self) -> None:
        """filesystem.read debe requerir LEVEL_0 mínimo."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        profile = registry.get_profile("filesystem.read")
        assert profile is not None
        assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_0_OBSERVE
        assert profile.risk_level == TaskActionRisk.READ_ONLY

    def test_document_create_is_level_2(self) -> None:
        """document.create debe requerir LEVEL_2 mínimo."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        profile = registry.get_profile("document.create")
        assert profile is not None
        assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION
        assert profile.risk_level == TaskActionRisk.LOW_RISK

    def test_message_send_is_level_3(self) -> None:
        """message.send debe requerir LEVEL_3 mínimo con confirmación ALWAYS."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        profile = registry.get_profile("message.send")
        assert profile is not None
        assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        assert profile.requires_confirmation == ConfirmationRequirement.ALWAYS
        assert profile.reversibility == ReversibilityClass.IRREVERSIBLE

    def test_windows_shell_is_level_4_critical(self) -> None:
        """windows.shell.cmd debe requerir LEVEL_4 con riesgo CRITICAL."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        for cap in ["windows.shell.cmd", "windows.shell.powershell"]:
            profile = registry.get_profile(cap)
            assert profile is not None
            assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY
            assert profile.risk_level == TaskActionRisk.CRITICAL
            assert profile.requires_confirmation == ConfirmationRequirement.ALWAYS
            assert profile.requires_tamper_evident_audit() is True

    def test_registry_write_is_level_3_critical(self) -> None:
        """system.registry_write: LEVEL_3, CRITICAL, ALWAYS confirmation."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        profile = registry.get_profile("system.registry_write")
        assert profile is not None
        assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
        assert profile.risk_level == TaskActionRisk.CRITICAL
        assert profile.requires_confirmation == ConfirmationRequirement.ALWAYS

    def test_software_install_is_level_4(self) -> None:
        """system.software_install: LEVEL_4, CRITICAL, IRREVERSIBLE."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        profile = registry.get_profile("system.software_install")
        assert profile is not None
        assert profile.minimum_autonomy_level == AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY
        assert profile.reversibility == ReversibilityClass.IRREVERSIBLE

    def test_get_profile_returns_none_for_unknown(self) -> None:
        """get_profile() retorna None para capability no registrada."""
        registry = _fresh_registry()
        assert registry.get_profile("unknown.capability") is None

    def test_get_profile_strict_raises_if_not_found(self) -> None:
        """get_profile_strict() lanza CapabilityProfileNotFoundError si no existe."""
        registry = _fresh_registry()
        with pytest.raises(CapabilityProfileNotFoundError, match="no tiene perfil"):
            registry.get_profile_strict("nonexistent.capability")

    def test_registry_locked_rejects_new_profiles(self) -> None:
        """Tras lock_registry(), no se pueden registrar nuevos perfiles."""
        registry = _fresh_registry()
        registry.lock_registry()
        profile = _make_profile("new.after.lock")
        with pytest.raises(CapabilityRegistryLockedError, match="sellado"):
            registry.register_profile(profile)

    def test_registry_unlocked_accepts_new_profiles(self) -> None:
        """Antes de lock_registry(), se pueden registrar perfiles."""
        registry = _fresh_registry()
        profile = _make_profile("custom.cap")
        registry.register_profile(profile)
        assert registry.get_profile("custom.cap") is not None

    def test_registry_key_lookup_is_case_insensitive(self) -> None:
        """Las claves deben ser insensibles a mayúsculas."""
        registry = _fresh_registry()
        registry.register_profile(_make_profile("filesystem.read"))
        assert registry.get_profile("FILESYSTEM.READ") is not None
        assert registry.get_profile("Filesystem.Read") is not None

    def test_get_capabilities_for_level_0(self) -> None:
        """LEVEL_0 sólo puede ejecutar capabilities con minimum_level == L0."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        caps_l0 = registry.get_capabilities_for_level(AutonomyLevel.LEVEL_0_OBSERVE)
        for key in caps_l0:
            profile = registry.get_profile(key)
            assert profile is not None
            assert profile.minimum_autonomy_level <= AutonomyLevel.LEVEL_0_OBSERVE

    def test_get_capabilities_for_level_4_includes_all(self) -> None:
        """LEVEL_4 debe poder ejecutar más capabilities que LEVEL_0."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        caps_l0 = set(registry.get_capabilities_for_level(AutonomyLevel.LEVEL_0_OBSERVE))
        caps_l4 = set(registry.get_capabilities_for_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY))
        assert caps_l4.issuperset(caps_l0), (
            "LEVEL_4 debe incluir todas las capabilities de LEVEL_0 y más."
        )
        assert len(caps_l4) > len(caps_l0)

    def test_no_level_5_in_catalog(self) -> None:
        """Ningún perfil debe requerir un nivel > 4 (LEVEL_5 no existe)."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        valid_levels = set(AutonomyLevel)
        for profile in registry.list_profiles():
            assert profile.minimum_autonomy_level in valid_levels, (
                f"Perfil '{profile.capability_key}' tiene nivel inválido."
            )
            assert profile.minimum_autonomy_level.value <= 4, (
                f"Perfil '{profile.capability_key}' usa nivel {profile.minimum_autonomy_level.value} > 4. "
                "No existe LEVEL_5."
            )

    def test_thread_safe_concurrent_reads(self) -> None:
        """Lecturas concurrentes del registry no deben producir errores."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        errors: list[Exception] = []
        lock = threading.Lock()

        def read() -> None:
            try:
                registry.get_profile("filesystem.read")
                registry.list_capabilities()
                registry.get_capabilities_for_level(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=read) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Race condition en lecturas concurrentes: {errors}"

    def test_get_stats_returns_expected_structure(self) -> None:
        """get_stats() debe incluir total_profiles, by_risk, by_min_level, by_category."""
        registry = CapabilityAutonomyRegistry(preload_defaults=True)
        stats = registry.get_stats()
        assert stats["total_profiles"] >= 40
        assert "READ_ONLY" in stats["by_risk"]
        assert "LEVEL_0_OBSERVE" in stats["by_min_level"]
        assert "filesystem" in stats["by_category"]


# ─────────────────────────────────────────────────────────────────────────────
# Sección 3 — AutonomyPolicy integrada con registry
# ─────────────────────────────────────────────────────────────────────────────

class TestAutonomyPolicyWithDeclaredProfiles:
    """Tests de la política con perfiles declarados."""

    def _policy_with_registry(self, profiles: list[CapabilityAutonomyProfile]) -> AutonomyPolicy:
        """Crea política con registry personalizado."""
        registry = _fresh_registry()
        for p in profiles:
            registry.register_profile(p)
        return _fresh_policy(registry)

    def test_level_0_allows_readonly_with_profile(self) -> None:
        """LEVEL_0 + capability READ_ONLY con min=L0 → ALLOW."""
        policy = self._policy_with_registry([
            _make_profile("fs.read", min_level=AutonomyLevel.LEVEL_0_OBSERVE,
                          risk=TaskActionRisk.READ_ONLY,
                          confirmation=ConfirmationRequirement.NEVER)
        ])
        ctx = _ctx("fs", "read")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)
        assert decision.allowed is True
        assert decision.decision == AutonomyDecisionValue.ALLOW

    def test_level_0_denies_capability_requiring_level_2(self) -> None:
        """LEVEL_0 + capability con min=L2 → DENY (nivel insuficiente)."""
        policy = self._policy_with_registry([
            _make_profile("doc.create", min_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
                          risk=TaskActionRisk.LOW_RISK)
        ])
        ctx = _ctx("doc", "create")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)
        assert decision.allowed is False
        assert decision.decision == AutonomyDecisionValue.DENY
        assert "LEVEL INSUFFICIENT" in decision.reason
        assert decision.metadata.get("profile_used") is True

    def test_level_2_denies_capability_requiring_level_3(self) -> None:
        """LEVEL_2 + capability con min=L3 → DENY (nivel insuficiente)."""
        policy = self._policy_with_registry([
            _make_profile("msg.send", min_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
                          risk=TaskActionRisk.MEDIUM_RISK,
                          confirmation=ConfirmationRequirement.ALWAYS)
        ])
        ctx = _ctx("msg", "send")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
        assert decision.allowed is False
        assert "LEVEL INSUFFICIENT" in decision.reason

    def test_level_3_message_send_requires_confirmation(self) -> None:
        """LEVEL_3 + message.send (ALWAYS confirm) → REQUIRE_CONFIRMATION."""
        policy = self._policy_with_registry([
            _make_profile("msg.send", min_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
                          risk=TaskActionRisk.MEDIUM_RISK,
                          confirmation=ConfirmationRequirement.ALWAYS,
                          reversibility=ReversibilityClass.IRREVERSIBLE)
        ])
        ctx = _ctx("msg", "send")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED)
        assert decision.allowed is False
        assert decision.requires_confirmation is True
        assert decision.decision == AutonomyDecisionValue.REQUIRE_CONFIRMATION

    def test_level_4_shell_always_requires_confirmation(self) -> None:
        """LEVEL_4 + windows.shell.cmd (CRITICAL, ALWAYS) → REQUIRE_CONFIRMATION."""
        policy = self._policy_with_registry([
            _make_profile("windows.shell", min_level=AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY,
                          risk=TaskActionRisk.CRITICAL,
                          confirmation=ConfirmationRequirement.ALWAYS,
                          reversibility=ReversibilityClass.IRREVERSIBLE,
                          audit=AuditRequirement.TAMPER_EVIDENT)
        ])
        ctx = _ctx("windows.shell", "cmd")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
        assert decision.allowed is False
        assert decision.requires_confirmation is True

    def test_no_profile_fallback_to_classifier(self) -> None:
        """Sin perfil declarado, cae al TaskRiskClassifier."""
        policy = _fresh_policy(_fresh_registry())  # Registry vacío
        # 'filesystem.read' no está → fallback → clasifica como READ_ONLY por nombre
        ctx = _ctx("filesystem", "read")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)
        assert decision.metadata.get("profile_used") is False
        # 'read' en nombre → READ_ONLY → ALLOW en LEVEL_0
        assert decision.allowed is True

    def test_declared_risk_takes_precedence_over_name_inference(self) -> None:
        """El riesgo declarado del perfil prevalece sobre la inferencia por nombre."""
        # Herramienta con 'delete' en nombre → debería ser DANGEROUS por inferencia
        # pero declaramos LOW_RISK en el perfil
        policy = self._policy_with_registry([
            _make_profile("temp.delete", min_level=AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION,
                          risk=TaskActionRisk.LOW_RISK,
                          confirmation=ConfirmationRequirement.NEVER)
        ])
        ctx = _ctx("temp", "delete")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
        # El perfil dice LOW_RISK → debe ser permitido en LEVEL_2
        assert decision.risk_level == TaskActionRisk.LOW_RISK
        assert decision.allowed is True
        assert decision.metadata.get("profile_used") is True

    def test_critical_always_requires_confirmation_regardless_of_level(self) -> None:
        """CRITICAL risk siempre requiere confirmación, en cualquier nivel."""
        policy = self._policy_with_registry([
            _make_profile("sys.registry", min_level=AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
                          risk=TaskActionRisk.CRITICAL,
                          confirmation=ConfirmationRequirement.ALWAYS)
        ])
        for level in [AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED,
                      AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY]:
            ctx = _ctx("sys", "registry")
            decision = policy.evaluate(ctx, level)
            assert decision.requires_confirmation is True, (
                f"CRITICAL debe requerir confirmación en {level.label}"
            )

    def test_default_registry_filesystem_read_level_0(self) -> None:
        """Con catálogo real: filesystem.read en LEVEL_0 → ALLOW."""
        policy = AutonomyPolicy()  # Usa catálogo real
        ctx = _ctx("filesystem", "read")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)
        assert decision.allowed is True
        assert decision.metadata.get("profile_used") is True

    def test_default_registry_shell_requires_level_4(self) -> None:
        """Con catálogo real: windows.shell.cmd en LEVEL_2 → DENY (nivel insuficiente)."""
        policy = AutonomyPolicy()
        ctx = _ctx("windows.shell", "cmd")
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION)
        assert decision.allowed is False
        assert decision.metadata.get("profile_used") is True


# ─────────────────────────────────────────────────────────────────────────────
# Sección 4 — AutonomyGovernor
# ─────────────────────────────────────────────────────────────────────────────

class TestAutonomyGovernorExtended:
    """Tests del AutonomyGovernor extendido con UNAUTHORIZED_ACTORS."""

    def _fresh_governor(self) -> AutonomyGovernor:
        """Crea un governor fresco (no singleton) para tests aislados."""
        return AutonomyGovernor()

    def test_unauthorized_actors_set_is_defined(self) -> None:
        """UNAUTHORIZED_ACTORS debe estar definido y contener actores clave."""
        required = {"llm", "plugin", "scheduler", "memory", "workflow", "assistant"}
        assert required.issubset(AutonomyGovernor.UNAUTHORIZED_ACTORS)

    def test_authorized_actors_and_unauthorized_are_disjoint(self) -> None:
        """AUTHORIZED y UNAUTHORIZED no deben tener intersección."""
        intersection = AutonomyGovernor.AUTHORIZED_ACTORS & AutonomyGovernor.UNAUTHORIZED_ACTORS
        assert len(intersection) == 0, (
            f"Actores aparecen en ambas listas: {intersection}"
        )

    def test_get_status_includes_actor_lists(self) -> None:
        """get_status() debe incluir authorized_actors y unauthorized_actors."""
        governor = self._fresh_governor()
        status = governor.get_status()
        assert "authorized_actors" in status
        assert "unauthorized_actors" in status
        assert "user" in status["authorized_actors"]
        assert "llm" in status["unauthorized_actors"]

    def test_get_profile_for_action_returns_profile(self) -> None:
        """get_profile_for_action() debe retornar perfil para capability conocida."""
        governor = self._fresh_governor()
        profile = governor.get_profile_for_action("filesystem", "read")
        assert profile is not None
        assert profile.capability_key == "filesystem.read"

    def test_get_profile_for_action_returns_none_for_unknown(self) -> None:
        """get_profile_for_action() retorna None para capability no registrada."""
        governor = self._fresh_governor()
        profile = governor.get_profile_for_action("unknown", "capability")
        assert profile is None

    def test_get_profile_for_action_is_readonly(self) -> None:
        """get_profile_for_action() retorna perfil inmutable."""
        governor = self._fresh_governor()
        profile = governor.get_profile_for_action("filesystem", "read")
        if profile:
            with pytest.raises((AttributeError, TypeError)):
                profile.minimum_autonomy_level = AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Sección 5 — Tests de Escalation (12 escenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestAutonomyEscalation:
    """12 escenarios de intento de escalada de autonomía."""

    def _fresh_governor(self) -> AutonomyGovernor:
        return AutonomyGovernor()

    # ── 5.1 Actor LLM intenta set_autonomy_level ─────────────────────────────

    def test_llm_cannot_set_autonomy_level(self) -> None:
        """LLM no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError, match="AUTONOMY ESCALATION REJECTED"):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="llm")

    # ── 5.2 Plugin intenta set_autonomy_level ────────────────────────────────

    def test_plugin_cannot_set_autonomy_level(self) -> None:
        """Plugin no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="plugin")

    # ── 5.3 Scheduler intenta set_autonomy_level ─────────────────────────────

    def test_scheduler_cannot_set_autonomy_level(self) -> None:
        """Scheduler no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="scheduler")

    # ── 5.4 Memory intenta set_autonomy_level ────────────────────────────────

    def test_memory_cannot_set_autonomy_level(self) -> None:
        """Memoria semántica no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="memory")

    # ── 5.5 Workflow intenta set_autonomy_level ───────────────────────────────

    def test_workflow_cannot_set_autonomy_level(self) -> None:
        """Workflow no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="workflow")

    # ── 5.6 Assistant intenta set_autonomy_level ──────────────────────────────

    def test_assistant_cannot_set_autonomy_level(self) -> None:
        """'assistant' como actor no puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="assistant")

    # ── 5.7 Parámetro override_autonomy detectado ────────────────────────────

    def test_override_autonomy_param_rejected(self) -> None:
        """Parámetro 'override_autonomy' en request → AutonomyEscalationError."""
        policy = AutonomyPolicy()
        ctx = AutonomyEvaluationContext(
            task_id="esc-test-07",
            tool_name="filesystem.read",
            operation="read",
            parameters={"override_autonomy": True, "level": "LEVEL_4"},
        )
        with pytest.raises(AutonomyEscalationError, match="AUTONOMY ESCALATION ATTEMPT"):
            policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)

    # ── 5.8 Parámetro bypass_confirmation detectado ──────────────────────────

    def test_bypass_confirmation_param_rejected(self) -> None:
        """Parámetro 'bypass_confirmation' en request → AutonomyEscalationError."""
        policy = AutonomyPolicy()
        ctx = AutonomyEvaluationContext(
            task_id="esc-test-08",
            tool_name="filesystem.delete",
            operation="delete",
            parameters={"bypass_confirmation": True},
        )
        with pytest.raises(AutonomyEscalationError):
            policy.evaluate(ctx, AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED)

    # ── 5.9 Parámetro grant_full_autonomy detectado ──────────────────────────

    def test_grant_full_autonomy_param_rejected(self) -> None:
        """Parámetro 'grant_full_autonomy' → AutonomyEscalationError."""
        policy = AutonomyPolicy()
        ctx = AutonomyEvaluationContext(
            task_id="esc-test-09",
            tool_name="filesystem.read",
            operation="read",
            metadata={"grant_full_autonomy": True},
        )
        with pytest.raises(AutonomyEscalationError):
            policy.evaluate(ctx, AutonomyLevel.LEVEL_0_OBSERVE)

    # ── 5.10 LEVEL_5 no existe ───────────────────────────────────────────────

    def test_level_5_does_not_exist(self) -> None:
        """No debe existir LEVEL_5 en el enum AutonomyLevel."""
        level_values = {level.value for level in AutonomyLevel}
        assert 5 not in level_values, (
            "LEVEL_5 fue encontrado en AutonomyLevel. No debe existir nivel de autonomía irrestricta."
        )
        assert max(level_values) == 4, (
            f"El nivel máximo debe ser 4 (LEVEL_4_CONTROLLED_AUTONOMY). Encontrado: {max(level_values)}"
        )

    # ── 5.11 Scheduled task != user_authorization ────────────────────────────

    def test_scheduled_task_dangerous_is_denied(self) -> None:
        """Tarea programada con acción DANGEROUS → DENY (invariante scheduled≠auth)."""
        policy = AutonomyPolicy()
        ctx = AutonomyEvaluationContext(
            task_id="esc-test-11",
            tool_name="filesystem.delete",
            operation="delete",
            is_scheduled=True,
            task_source="scheduled_task",
        )
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
        assert decision.allowed is False
        assert decision.decision == AutonomyDecisionValue.DENY
        assert "SCHEDULED TASK DENIED" in decision.reason

    # ── 5.12 Plugin no puede auto-elevar a través de acción DANGEROUS ────────

    def test_plugin_dangerous_action_denied(self) -> None:
        """Acción DANGEROUS desde plugin → DENY (Plugin → CAPABILITY, sin auto-elevación)."""
        policy = AutonomyPolicy()
        ctx = AutonomyEvaluationContext(
            task_id="esc-test-12",
            tool_name="process.kill",
            operation="kill",
            is_plugin=True,
            task_source="plugin_action",
        )
        decision = policy.evaluate(ctx, AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY)
        assert decision.allowed is False
        assert "PLUGIN ACTION DENIED" in decision.reason or decision.decision in (
            AutonomyDecisionValue.DENY, AutonomyDecisionValue.REQUIRE_CONFIRMATION
        )

    # ── Bonus: Usuario autorizado SÍ puede cambiar el nivel ──────────────────

    def test_user_can_set_autonomy_level(self) -> None:
        """Usuario autorizado puede cambiar el nivel de autonomía."""
        gov = self._fresh_governor()
        gov.set_autonomy_level(AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION, actor="user")
        assert gov.current_level == AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION

    def test_system_admin_can_reset(self) -> None:
        """system_admin puede resetear el nivel al default."""
        gov = self._fresh_governor()
        gov.set_autonomy_level(AutonomyLevel.LEVEL_0_OBSERVE, actor="user")
        gov.reset_to_default()  # Usa system_admin internamente
        assert gov.current_level == AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED

    def test_level_unchanged_after_unauthorized_attempt(self) -> None:
        """El nivel no debe cambiar tras un intento fallido de escalation."""
        gov = self._fresh_governor()
        original = gov.current_level
        with pytest.raises(AutonomyEscalationError):
            gov.set_autonomy_level(AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY, actor="llm")
        assert gov.current_level == original, (
            "El nivel de autonomía cambió a pesar del intento rechazado."
        )
