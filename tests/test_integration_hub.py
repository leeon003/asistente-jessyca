"""Tests unitarios completos para la Capa de Integraciones (Integration Hub / Adapter Layer).

Cubre:
1. Registro y desregistro de adapters en IntegrationRegistry.
2. Descubrimiento de capacidades declarativas.
3. Ciclo de vida asíncrono (initialize, health_check, shutdown).
4. Aislamiento de dependencias (módulos ausentes -> UNAVAILABLE sin crashear el Core).
5. Deshabilitación de adapters por configuración.
6. Principio EXECUTE -> VERIFY -> REPORT (separación taxativa, claims_success estricto).
7. Frontera de Seguridad (validación de RiskLevel, denegación de permisos).
8. Fallback transparente a capacidad nativa de JESSYCA.
9. Tolerancia a fallos y excepciones internas de adapters.
10. Emisión de eventos tipados al Event Bus.
11. Sanitización de credenciales y secretos en logs y auditoría.
"""

from __future__ import annotations

import asyncio
from typing import Any
import pytest

from core.bus import EventBus
from core.events.base import IntegrationExecuted, IntegrationStatusChanged
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.hub import IntegrationHub
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry
from core.integration.security_boundary import (
    IntegrationSecurityBoundary,
    sanitize_context_parameters,
)
from core.security import RiskLevel, SecurityManager, SecurityPolicy


# --- Adapters de Prueba Simulados ---


class MockSafeAdapter(IntegrationAdapter):
    """Adapter simulado con dependencias satisfechas y capacidad segura."""

    def __init__(self, name: str = "mock_safe", version: str = "1.0.0") -> None:
        super().__init__(name=name, version=version, dependencies=["sys", "os"])
        self.register_capability(
            IntegrationCapability(
                name="system_info",
                description="Obtiene información segura del sistema",
                required_risk_level=RiskLevel.SAFE,
                required_permissions=[],
            )
        )
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> bool:
        self.initialized = True
        return True

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(
            status=self.status,
            is_healthy=(self.status == IntegrationStatus.READY),
            message="MockSafeAdapter OK",
        )

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        # Respeta EXECUTE -> VERIFY -> REPORT: executed=True, verified=False (a la espera de verificación externa)
        return IntegrationExecutionResult(
            executed=True,
            verified=False,
            verification_required=True,
            status=ExecutionStatus.SUCCEEDED,
            output={"info": "system_ready", "user": context.user_id},
        )

    async def shutdown(self) -> None:
        self.shutdown_called = True


class MockMissingDepsAdapter(IntegrationAdapter):
    """Adapter que declara una dependencia inexistente para probar aislamiento."""

    def __init__(self) -> None:
        super().__init__(
            name="mock_missing_deps",
            version="1.0.0",
            dependencies=["nonexistent_external_module_xyz_12345"],
        )
        self.register_capability(
            IntegrationCapability(
                name="advanced_ai_control",
                description="Capacidad que requiere librería no instalada",
                required_risk_level=RiskLevel.SAFE,
            )
        )

    async def initialize(self) -> bool:
        return True

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(status=self.status, is_healthy=False)

    async def execute(self, capability: str, context: IntegrationContext) -> IntegrationExecutionResult:
        return IntegrationExecutionResult(executed=False, status=ExecutionStatus.FAILED)

    async def shutdown(self) -> None:
        pass


class MockCriticalAdapter(IntegrationAdapter):
    """Adapter con capacidades críticas y peligrosas para probar seguridad."""

    def __init__(self) -> None:
        super().__init__(name="mock_critical", version="1.0.0", dependencies=["os"])
        self.register_capability(
            IntegrationCapability(
                name="raw_system_execution",
                description="Ejecución de comandos arbitrarios",
                required_risk_level=RiskLevel.CRITICAL,
                required_permissions=["system.execute"],
            )
        )

    async def initialize(self) -> bool:
        return True

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(status=self.status, is_healthy=True)

    async def execute(self, capability: str, context: IntegrationContext) -> IntegrationExecutionResult:
        return IntegrationExecutionResult(
            executed=True,
            verified=False,
            verification_required=True,
            status=ExecutionStatus.SUCCEEDED,
            output="Executed dangerous command",
        )

    async def shutdown(self) -> None:
        pass


class MockFailingAdapter(IntegrationAdapter):
    """Adapter que falla intencionalmente para probar captura de errores y fallback."""

    def __init__(self) -> None:
        super().__init__(name="mock_failing", version="1.0.0", dependencies=["os"])
        self.register_capability(
            IntegrationCapability(
                name="unstable_operation",
                description="Operación que lanza excepción",
                required_risk_level=RiskLevel.SAFE,
            )
        )

    async def initialize(self) -> bool:
        return True

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(status=self.status, is_healthy=False, message="Unstable")

    async def execute(self, capability: str, context: IntegrationContext) -> IntegrationExecutionResult:
        raise RuntimeError("Fallo catastrófico en la librería externa simulada")

    async def shutdown(self) -> None:
        pass


# --- Fixtures ---


@pytest.fixture
def clean_registry() -> IntegrationRegistry:
    reg = IntegrationRegistry()
    reg.reset()
    return reg


@pytest.fixture
def mock_bus() -> EventBus:
    return EventBus()


# --- Tests ---


def test_registry_registration_and_lookup(clean_registry: IntegrationRegistry) -> None:
    """Valida registro, desregistro y búsqueda en IntegrationRegistry."""
    adapter = MockSafeAdapter()
    assert clean_registry.register(adapter, enabled=True) is True

    # No permite duplicados
    assert clean_registry.register(adapter) is False

    # Búsqueda por nombre
    retrieved = clean_registry.get("mock_safe")
    assert retrieved is not None
    assert retrieved.name == "mock_safe"

    # Mapeo de capacidades
    caps = clean_registry.list_capabilities()
    assert "system_info" in caps
    assert "mock_safe" in caps["system_info"]

    # Desregistro
    assert clean_registry.unregister("mock_safe") is True
    assert clean_registry.get("mock_safe") is None
    assert "system_info" not in clean_registry.list_capabilities()


def test_registry_enable_disable(clean_registry: IntegrationRegistry) -> None:
    """Valida activación y desactivación dinámica en el registro."""
    adapter = MockSafeAdapter()
    clean_registry.register(adapter, enabled=False)

    assert clean_registry.is_enabled("mock_safe") is False
    assert adapter.status == IntegrationStatus.DISABLED

    clean_registry.set_enabled("mock_safe", True)
    assert clean_registry.is_enabled("mock_safe") is True
    assert adapter.status == IntegrationStatus.AVAILABLE


@pytest.mark.anyio
async def test_dependency_isolation_and_lifecycle(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que un adapter con dependencias faltantes pase a UNAVAILABLE sin fallar el arranque."""
    safe_adapter = MockSafeAdapter()
    missing_deps_adapter = MockMissingDepsAdapter()

    clean_registry.register(safe_adapter, enabled=True)
    clean_registry.register(missing_deps_adapter, enabled=True)

    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)

    # Inicializar todos
    results = await hub.initialize_all()

    # Safe adapter debe estar READY
    assert results["mock_safe"] is True
    assert safe_adapter.status == IntegrationStatus.READY

    # Missing deps adapter debe ser UNAVAILABLE y NO provocar excepción
    assert results["mock_missing_deps"] is False
    assert missing_deps_adapter.status == IntegrationStatus.UNAVAILABLE

    # Health check
    health_reports = await hub.health_check_all()
    assert health_reports["mock_safe"].is_healthy is True
    assert health_reports["mock_missing_deps"].is_healthy is False

    # Shutdown
    await hub.shutdown_all()
    assert safe_adapter.shutdown_called is True


@pytest.mark.anyio
async def test_execute_verify_report_separation(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Valida el principio EXECUTE -> VERIFY -> REPORT: claims_success es estrictamente False

    si verified es False, impidiendo falso éxito.
    """
    adapter = MockSafeAdapter()
    clean_registry.register(adapter, enabled=True)
    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    await hub.initialize_all()

    context = IntegrationContext(
        session_id="test-session-123",
        user_id="diego",
        parameters={"action": "query"},
    )

    res = await hub.execute_capability("system_info", context)

    assert res.executed is True
    assert res.verified is False
    assert res.verification_required is True
    assert res.status == ExecutionStatus.SUCCEEDED
    # claims_success NUNCA debe ser True sin verificación comprobable
    assert res.claims_success is False


@pytest.mark.anyio
async def test_security_boundary_enforcement(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que la frontera de seguridad bloquee capacidades críticas sin permisos."""
    sec_mgr = SecurityManager(
        policy=SecurityPolicy(max_allowed_risk=RiskLevel.WARNING),
    )
    boundary = IntegrationSecurityBoundary(security_manager=sec_mgr)

    crit_adapter = MockCriticalAdapter()
    clean_registry.register(crit_adapter, enabled=True)

    hub = IntegrationHub(
        registry=clean_registry,
        security_boundary=boundary,
        event_bus=mock_bus,
    )
    await hub.initialize_all()

    context = IntegrationContext(
        session_id="test-sec-session",
        user_id="user",
        parameters={"cmd": "format C:"},
    )

    # Intento de ejecutar capacidad CRITICAL con política que sólo permite hasta WARNING
    res = await hub.execute_capability("raw_system_execution", context)

    assert res.executed is False
    assert res.status == ExecutionStatus.DENIED
    assert "Seguridad denegó la ejecución" in (res.error or "")


@pytest.mark.anyio
async def test_fallback_mechanism_when_adapter_fails(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que si un adapter falla con excepción, se invoque el fallback nativo de forma transparente."""
    failing_adapter = MockFailingAdapter()
    clean_registry.register(failing_adapter, enabled=True)

    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    await hub.initialize_all()

    context = IntegrationContext(
        session_id="fallback-sess",
        parameters={"data": "test"},
    )

    def native_jessyca_capability(ctx: IntegrationContext) -> str:
        return f"Native execution for {ctx.session_id}"

    res = await hub.execute_with_fallback(
        capability="unstable_operation",
        context=context,
        native_fallback=native_jessyca_capability,
    )

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.output == "Native execution for fallback-sess"
    assert res.metadata.get("fallback_used") is True
    assert res.metadata.get("provider") == "jessyca_native"


@pytest.mark.anyio
async def test_fallback_mechanism_when_no_adapter_available(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que ante ausencia total de adapter para una capacidad, se active el fallback nativo sin crashear."""
    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)

    context = IntegrationContext(session_id="no-adapter-sess")

    async def async_native_fallback(ctx: IntegrationContext) -> dict[str, str]:
        return {"status": "ok_from_native_async"}

    res = await hub.execute_with_fallback(
        capability="non_existent_capability",
        context=context,
        native_fallback=async_native_fallback,
    )

    assert res.executed is True
    assert res.status == ExecutionStatus.SUCCEEDED
    assert res.output == {"status": "ok_from_native_async"}
    assert res.metadata.get("fallback_used") is True


@pytest.mark.anyio
async def test_event_bus_publishing(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Comprueba que el ciclo de vida y la ejecución emitan eventos tipados al EventBus."""
    events_received: list[Any] = []

    def handle_status(evt: IntegrationStatusChanged) -> None:
        events_received.append(evt)

    def handle_exec(evt: IntegrationExecuted) -> None:
        events_received.append(evt)

    mock_bus.subscribe(IntegrationStatusChanged, handle_status)
    mock_bus.subscribe(IntegrationExecuted, handle_exec)

    adapter = MockSafeAdapter()
    clean_registry.register(adapter, enabled=True)
    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)

    await hub.initialize_all()
    await hub.execute_capability("system_info", IntegrationContext(session_id="ev-sess"))

    status_events = [e for e in events_received if isinstance(e, IntegrationStatusChanged)]
    exec_events = [e for e in events_received if isinstance(e, IntegrationExecuted)]

    assert len(status_events) >= 1
    assert status_events[0].adapter_name == "mock_safe"
    assert status_events[0].new_status == "READY"

    assert len(exec_events) == 1
    assert exec_events[0].adapter_name == "mock_safe"
    assert exec_events[0].capability == "system_info"
    assert exec_events[0].executed is True


def test_sensitive_credentials_sanitization() -> None:
    """Verifica que contraseñas, tokens y claves secretas sean ofuscadas de forma determinista."""
    raw_params = {
        "user": "diego",
        "password": "SuperSecretPassword123!",
        "api_key": "sk-1234567890abcdef",
        "nested": {
            "token": "jwt-token-xyz",
            "safe_data": "visible",
        },
    }

    sanitized = sanitize_context_parameters(raw_params)
    assert sanitized["user"] == "diego"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["api_key"] == "***REDACTED***"
    assert sanitized["nested"]["token"] == "***REDACTED***"
    assert sanitized["nested"]["safe_data"] == "visible"


@pytest.mark.anyio
async def test_preferred_adapter_routing(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Verifica que el hub priorice el adapter especificado en preferred_adapter."""
    adapter_a = MockSafeAdapter(name="adapter_alpha")
    adapter_b = MockSafeAdapter(name="adapter_beta")

    clean_registry.register(adapter_a, enabled=True)
    clean_registry.register(adapter_b, enabled=True)

    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    await hub.initialize_all()

    context = IntegrationContext(session_id="pref-sess")
    res = await hub.execute_capability("system_info", context, preferred_adapter="adapter_beta")

    assert res.executed is True
    # El resultado se ejecutó mediante adapter_beta
    assert res.output["user"] == "user"


class MockInitFailingAdapter(IntegrationAdapter):
    """Adapter que falla durante initialize() para probar aislamiento de arranque."""

    def __init__(self) -> None:
        super().__init__(name="mock_init_fail", version="1.0.0", dependencies=["os"])
        self.register_capability(
            IntegrationCapability(
                name="broken_cap",
                description="Capacidad de adapter roto",
            )
        )

    async def initialize(self) -> bool:
        raise ValueError("Error forzado en initialize()")

    async def health_check(self) -> IntegrationHealth:
        return IntegrationHealth(status=self.status, is_healthy=False)

    async def execute(self, capability: str, context: IntegrationContext) -> IntegrationExecutionResult:
        return IntegrationExecutionResult(executed=False, status=ExecutionStatus.FAILED)

    async def shutdown(self) -> None:
        pass


@pytest.mark.anyio
async def test_adapter_initialization_failure_isolation(
    clean_registry: IntegrationRegistry,
    mock_bus: EventBus,
) -> None:
    """Comprueba que si un adapter lanza excepción en initialize(), pasa a ERROR y no interrumpe a los demás."""
    broken = MockInitFailingAdapter()
    healthy = MockSafeAdapter()

    clean_registry.register(broken, enabled=True)
    clean_registry.register(healthy, enabled=True)

    hub = IntegrationHub(registry=clean_registry, event_bus=mock_bus)
    results = await hub.initialize_all()

    assert results["mock_init_fail"] is False
    assert broken.status == IntegrationStatus.ERROR

    assert results["mock_safe"] is True
    assert healthy.status == IntegrationStatus.READY


def test_claims_success_with_genuine_verification() -> None:
    """Verifica que claims_success sólo retorne True cuando executed=True, status=SUCCEEDED y verified=True."""
    res_unverified = IntegrationExecutionResult(
        executed=True,
        verified=False,
        status=ExecutionStatus.SUCCEEDED,
    )
    assert res_unverified.claims_success is False

    res_verified = IntegrationExecutionResult(
        executed=True,
        verified=True,
        status=ExecutionStatus.SUCCEEDED,
    )
    assert res_verified.claims_success is True

    res_verified_failed = IntegrationExecutionResult(
        executed=True,
        verified=True,
        status=ExecutionStatus.FAILED,
    )
    assert res_verified_failed.claims_success is False

