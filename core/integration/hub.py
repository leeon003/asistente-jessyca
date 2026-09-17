"""Integration Hub central de JESSYCA 4.0.

Punto único de coordinación para el descubrimiento, ciclo de vida, seguridad,
despacho con fallback y observabilidad de tecnologías externas integradas.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

from core.bus import EventBus, get_event_bus
from core.events.base import Event
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationInfo,
    IntegrationStatus,
)
from core.integration.registry import IntegrationRegistry, get_integration_registry
from core.integration.security_boundary import (
    IntegrationSecurityBoundary,
    sanitize_context_parameters,
)
from core.logger import get_logger

logger = get_logger("jessyca.integration.hub")


class IntegrationHub:
    """Hub central de integraciones para JESSYCA 4.0."""

    def __init__(
        self,
        registry: IntegrationRegistry | None = None,
        security_boundary: IntegrationSecurityBoundary | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = registry or get_integration_registry()
        self._security = security_boundary or IntegrationSecurityBoundary()
        self._event_bus = event_bus

    @property
    def registry(self) -> IntegrationRegistry:
        return self._registry

    @property
    def security_boundary(self) -> IntegrationSecurityBoundary:
        return self._security

    def _get_event_bus(self) -> EventBus | None:
        if self._event_bus is not None:
            return self._event_bus
        try:
            return get_event_bus()
        except Exception:
            return None

    def _publish_event(self, event: Event) -> None:
        bus = self._get_event_bus()
        if bus:
            try:
                bus.publish(event)
            except Exception as exc:
                logger.debug(f"No se pudo publicar evento en EventBus: {exc}")

    async def initialize_all(self) -> dict[str, bool]:
        """Inicializa todos los adapters registrados respetando configuración y dependencias.

        Garantiza aislamiento de dependencias: Si un adapter requiere dependencias no
        instaladas, se marca como UNAVAILABLE sin detener ni provocar excepciones en el Core.

        Returns:
            Diccionario {nombre_adapter: éxito_inicialización}.
        """
        results: dict[str, bool] = {}
        for info in self._registry.list_integrations():
            name = info.name
            adapter = self._registry.get(name)
            if not adapter:
                continue

            if not self._registry.is_enabled(name):
                adapter.status = IntegrationStatus.DISABLED
                results[name] = False
                logger.info(f"Adapter '{name}' está DESHABILITADO por configuración.")
                continue

            # 1. Comprobación segura de dependencias (Aislamiento)
            has_deps, missing = adapter.check_dependencies()
            if not has_deps:
                adapter.status = IntegrationStatus.UNAVAILABLE
                results[name] = False
                logger.warning(
                    f"Adapter '{name}' no disponible. Dependencias faltantes: {missing}. "
                    "JESSYCA continúa operando de forma aislada."
                )
                self._emit_status_changed(name, info.status, IntegrationStatus.UNAVAILABLE, f"Faltan dependencias: {missing}")
                continue

            # 2. Inicialización del Adapter
            old_status = adapter.status
            adapter.status = IntegrationStatus.INITIALIZING
            try:
                success = await adapter.initialize()
                if success:
                    adapter.status = IntegrationStatus.READY
                    results[name] = True
                    logger.info(f"Adapter '{name}' v{adapter.version} inicializado y READY.")
                    self._emit_status_changed(name, old_status, IntegrationStatus.READY)
                else:
                    adapter.status = IntegrationStatus.ERROR
                    results[name] = False
                    logger.error(f"Adapter '{name}' falló durante initialize(). Estado: ERROR.")
                    self._emit_status_changed(name, old_status, IntegrationStatus.ERROR, "initialize() retornó False")
            except Exception as exc:
                adapter.status = IntegrationStatus.ERROR
                results[name] = False
                logger.error(f"Excepción al inicializar adapter '{name}': {exc}", exc_info=True)
                self._emit_status_changed(name, old_status, IntegrationStatus.ERROR, str(exc))

        return results

    async def health_check_all(self) -> dict[str, IntegrationHealth]:
        """Ejecuta diagnósticos de salud para todos los adapters registrados."""
        reports: dict[str, IntegrationHealth] = {}
        for info in self._registry.list_integrations():
            adapter = self._registry.get(info.name)
            if not adapter:
                continue
            try:
                health = await adapter.health_check()
                reports[info.name] = health
            except Exception as exc:
                reports[info.name] = IntegrationHealth(
                    status=IntegrationStatus.ERROR,
                    is_healthy=False,
                    message=f"Error en health_check: {exc}",
                )
        return reports

    async def shutdown_all(self) -> None:
        """Apaga de forma ordenada todos los adapters registrados."""
        for info in self._registry.list_integrations():
            adapter = self._registry.get(info.name)
            if adapter and adapter.status in (IntegrationStatus.READY, IntegrationStatus.DEGRADED):
                try:
                    await adapter.shutdown()
                    adapter.status = IntegrationStatus.AVAILABLE
                except Exception as exc:
                    logger.error(f"Error apagando adapter '{info.name}': {exc}")

    async def execute_capability(
        self,
        capability: str,
        context: IntegrationContext,
        preferred_adapter: str | None = None,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad a través del adapter correspondiente respetando Seguridad y Verificación.

        Args:
            capability: Nombre de la capacidad a ejecutar.
            context: Parámetros y contexto de ejecución.
            preferred_adapter: Nombre del adapter preferido si hay múltiples proveedores.

        Returns:
            IntegrationExecutionResult formal.
        """
        start_time = time.perf_counter()
        cap_name = capability.strip()

        # 1. Selección de Adapter READY
        candidates = self._registry.get_for_capability(cap_name, only_ready=True)
        adapter: IntegrationAdapter | None = None

        if preferred_adapter:
            for cand in candidates:
                if cand.name == preferred_adapter:
                    adapter = cand
                    break

        if adapter is None and candidates:
            adapter = candidates[0]

        if adapter is None:
            dur = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"No existe ningún adapter READY para la capacidad '{cap_name}'.")
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.FAILED,
                error=f"No hay ningún adaptador disponible y listo para la capacidad '{cap_name}'.",
                duration_ms=dur,
            )

        # 2. Obtener la capacidad declarada
        cap_obj = adapter.get_capability(cap_name)
        if not cap_obj:
            dur = (time.perf_counter() - start_time) * 1000.0
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.FAILED,
                error=f"El adapter '{adapter.name}' no declara la capacidad '{cap_name}'.",
                duration_ms=dur,
            )

        # 3. Validación en Frontera de Seguridad
        allowed, decision = self._security.evaluate_execution(adapter, cap_obj, context)
        if not allowed:
            dur = (time.perf_counter() - start_time) * 1000.0
            if decision is not None:
                return self._security.create_denied_result(cap_name, decision, duration_ms=dur)
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.DENIED,
                error="Seguridad denegó la ejecución.",
                duration_ms=dur,
            )

        # 4. Invocación Segura y Aislada del Adapter
        try:
            res = await adapter.execute(cap_name, context)
            dur = (time.perf_counter() - start_time) * 1000.0
            res.duration_ms = dur

            # Observabilidad y registro sin datos sensibles
            safe_params = sanitize_context_parameters(context.parameters)
            logger.info(
                f"[INTEGRATION_HUB] Ejecución '{cap_name}' en '{adapter.name}' completada. "
                f"Status: {res.status}. Executed: {res.executed}. Verified: {res.verified}. Dur: {dur:.2f}ms."
            )

            # Notificación a Event Bus
            self._emit_executed_event(
                adapter_name=adapter.name,
                capability=cap_name,
                status=res.status.value if hasattr(res.status, "value") else str(res.status),
                duration_ms=dur,
                executed=res.executed,
                verified=res.verified,
            )
            return res

        except Exception as exc:
            dur = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"[INTEGRATION_HUB] Fallo crítico al ejecutar '{cap_name}' en '{adapter.name}': {exc}", exc_info=True)
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.FAILED,
                error=f"Excepción en adapter '{adapter.name}': {exc}",
                duration_ms=dur,
            )

    async def execute_with_fallback(
        self,
        capability: str,
        context: IntegrationContext,
        native_fallback: Callable[[IntegrationContext], Awaitable[Any] | Any],
        preferred_adapter: str | None = None,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad mediante un adapter, pero recurre transparentemente a una

        capacidad nativa de JESSYCA si el adapter no está disponible, falla o está deshabilitado.

        Garantiza que JESSYCA nunca crashee si la integración externa no responde.

        Args:
            capability: Nombre de la capacidad solicitada.
            context: Contexto de ejecución.
            native_fallback: Función o corrutina nativa a ejecutar como fallback.
            preferred_adapter: Adapter preferido opcional.

        Returns:
            IntegrationExecutionResult formal.
        """
        start_time = time.perf_counter()
        cap_name = capability.strip()

        # Intentar ejecución con adapter externo
        candidates = self._registry.get_for_capability(cap_name, only_ready=True)
        if candidates:
            res = await self.execute_capability(cap_name, context, preferred_adapter)
            # Si se ejecutó con éxito o falló por denegación de seguridad legítima, retornar
            if res.executed or res.status == ExecutionStatus.DENIED:
                return res

            logger.warning(
                f"[INTEGRATION_HUB] Adapter '{candidates[0].name}' no pudo completar '{cap_name}' "
                f"(Status: {res.status}, Error: {res.error}). Activando Fallback Nativo..."
            )
        else:
            logger.debug(f"[INTEGRATION_HUB] Sin adapter READY para '{cap_name}'. Activando Fallback Nativo...")

        # Ejecutar Fallback Nativo de JESSYCA
        try:
            if inspect.iscoroutinefunction(native_fallback):
                fallback_out = await native_fallback(context)
            else:
                fallback_out = native_fallback(context)

            dur = (time.perf_counter() - start_time) * 1000.0
            logger.info(f"[INTEGRATION_HUB] Fallback Nativo para '{cap_name}' completado exitosamente en {dur:.2f}ms.")
            return IntegrationExecutionResult(
                executed=True,
                verified=False,  # El fallback nativo tampoco auto-certifica sin verificación externa
                verification_required=True,
                status=ExecutionStatus.SUCCEEDED,
                output=fallback_out,
                duration_ms=dur,
                metadata={"fallback_used": True, "provider": "jessyca_native"},
            )
        except Exception as exc:
            dur = (time.perf_counter() - start_time) * 1000.0
            logger.error(f"[INTEGRATION_HUB] Error en Fallback Nativo para '{cap_name}': {exc}", exc_info=True)
            return IntegrationExecutionResult(
                executed=False,
                verified=False,
                verification_required=False,
                status=ExecutionStatus.FAILED,
                error=f"Error en fallback nativo: {exc}",
                duration_ms=dur,
                metadata={"fallback_used": True, "fallback_failed": True},
            )

    def _emit_status_changed(
        self,
        adapter_name: str,
        old_status: IntegrationStatus,
        new_status: IntegrationStatus,
        message: str = "",
    ) -> None:
        try:
            from core.events.base import IntegrationStatusChanged
            evt = IntegrationStatusChanged(
                adapter_name=adapter_name,
                old_status=old_status.value if hasattr(old_status, "value") else str(old_status),
                new_status=new_status.value if hasattr(new_status, "value") else str(new_status),
                message=message,
            )
            self._publish_event(evt)
        except (ImportError, AttributeError):
            pass

    def _emit_executed_event(
        self,
        adapter_name: str,
        capability: str,
        status: str,
        duration_ms: float,
        executed: bool,
        verified: bool,
    ) -> None:
        try:
            from core.events.base import IntegrationExecuted
            evt = IntegrationExecuted(
                adapter_name=adapter_name,
                capability=capability,
                status=status,
                duration_ms=duration_ms,
                executed=executed,
                verified=verified,
            )
            self._publish_event(evt)
        except (ImportError, AttributeError):
            pass


_global_hub: IntegrationHub | None = None


def get_integration_hub() -> IntegrationHub:
    """Devuelve la instancia global del IntegrationHub."""
    global _global_hub
    if _global_hub is None:
        _global_hub = IntegrationHub()
    return _global_hub
