"""Orquestador central del pipeline de ejecución segura (SecureExecutionPipeline - Subetapa 05.2).

Coordina el flujo determinista de interceptación a través de las 6 capas de seguridad de Jessyca:
Security Architecture -> Risk Engine -> Security Policy -> Permission Manager -> Confirmation Manager -> Audit Logger -> SecureExecutionBoundary.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from core.audit_logger import AuditEvent, AuditEventType, AuditLogger, get_audit_logger
from core.builtin_capabilities import register_builtin_capabilities
from core.capability_resolver import CapabilityResolver
from core.confirmation import ConfirmationManager, IConfirmationProvider
from core.event_bus import EventBus, get_event_bus
from core.logger import get_logger
from core.permission_manager import PermissionManager, PermissionRequest
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityContext, ToolSecurityMetadata
from core.security_policy import SecurityPolicyEvaluator, create_default_security_policy
from server.aggregator import SecurityDecisionAggregator
from server.boundary import ExecutionResult, ExecutionStatus, SecureExecutionBoundary
from server.evidence import create_authorization_evidence
from server.execution_request import ExecutionRequest

logger = get_logger("jessyca.server.pipeline")


class SecureExecutionPipeline:
    """Orquestador del pipeline de ejecución segura."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        policy_evaluator: SecurityPolicyEvaluator | None = None,
        permission_manager: PermissionManager | None = None,
        confirmation_manager: ConfirmationManager | None = None,
        audit_logger: AuditLogger | None = None,
        event_bus: EventBus | None = None,
        execution_boundary: SecureExecutionBoundary | None = None,
        capability_resolver: CapabilityResolver | None = None,
    ) -> None:
        self.risk_engine = risk_engine or RiskEngine()
        self.policy_evaluator = policy_evaluator or SecurityPolicyEvaluator()
        self.policy = create_default_security_policy()
        self.permission_manager = permission_manager or PermissionManager()
        self.confirmation_manager = confirmation_manager or ConfirmationManager()
        self.audit_logger = audit_logger or get_audit_logger()
        self.event_bus = event_bus or get_event_bus()
        self.boundary = execution_boundary or SecureExecutionBoundary()
        self.capability_resolver = capability_resolver or CapabilityResolver()
        self.aggregator = SecurityDecisionAggregator()

        from tools.desktop.executor import WindowsDesktopToolExecutor
        from tools.filesystem.executor import WindowsFilesystemToolExecutor
        from tools.process.executor import WindowsProcessToolExecutor
        from tools.registry.executor import WindowsRegistryToolExecutor
        from tools.services.executor import WindowsServicesToolExecutor

        self.boundary.register_executor("windows.files", WindowsFilesystemToolExecutor())
        self.boundary.register_executor("windows.process", WindowsProcessToolExecutor())
        self.boundary.register_executor("windows.registry", WindowsRegistryToolExecutor())
        self.boundary.register_executor("windows.services", WindowsServicesToolExecutor())
        self.boundary.register_executor("windows.desktop", WindowsDesktopToolExecutor())

        # Registrar automáticamente las capabilities integradas declarativas
        register_builtin_capabilities(self.capability_resolver.registry)

    def execute_request(
        self,
        request: ExecutionRequest,
        confirmation_provider: IConfirmationProvider | None = None,
    ) -> ExecutionResult:
        """Ejecuta una solicitud a través del pipeline determinista de seguridad.

        Ninguna etapa puede ser omitida. Si una capa deniega la operación, el pipeline se detiene inmediatamente.
        """
        start_time = time.perf_counter()
        req_id = request.request_id
        corr_id = request.correlation_id
        sess_id = request.session_id

        # Notificar EventBus
        self.event_bus.publish("execution:requested", {"request_id": req_id, "tool_name": request.tool_name})

        # Paso 1: AUDIT - REQUEST_RECEIVED
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.REQUEST_RECEIVED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                user=request.context.user,
                tool_name=request.tool_name,
                operation=request.operation,
                parameters=request.parameters,
                metadata=request.metadata,
            )
        )

        # Paso 1.1: CAPABILITY SYSTEM - CAPABILITY_RESOLVED
        capability_res = self.capability_resolver.resolve(request.tool_name, request.operation)
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.CAPABILITY_RESOLVED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                user=request.context.user,
                tool_name=request.tool_name,
                operation=request.operation,
                reason=capability_res.reason,
            )
        )
        self.event_bus.publish("capability:resolved", capability_res.to_dict())

        # Crear SecurityContext e inspeccionar metadatos
        ctx = SecurityContext(
            user=request.context.user,
            tool_name=request.tool_name,
            parameters=request.parameters,
        )
        metadata = ToolSecurityMetadata(tool_name=request.tool_name, category="mcp")

        # Paso 2: RISK ENGINE - RISK_EVALUATED
        risk_assessment = self.risk_engine.evaluate_risk(ctx, request.parameters)
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.RISK_EVALUATED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                user=request.context.user,
                tool_name=request.tool_name,
                operation=request.operation,
                security_level=risk_assessment.risk_level,
                risk_factors={f.value for f in risk_assessment.risk_factors},
            )
        )

        # Paso 3: SECURITY POLICY - POLICY_EVALUATED
        policy_result = self.policy_evaluator.evaluate_policy(ctx, metadata, risk_assessment, self.policy)
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                user=request.context.user,
                tool_name=request.tool_name,
                operation=request.operation,
                policy_id=self.policy.policy_id,
                policy_decision=policy_result.decision_type.value,
                reason=policy_result.reason,
            )
        )

        # Paso 4: PERMISSION MANAGER - PERMISSION_EVALUATED
        perm_request = PermissionRequest(
            context=ctx,
            metadata=metadata,
            risk_assessment=risk_assessment,
            tool_name=request.tool_name,
            operation=request.operation,
        )
        permission_result = self.permission_manager.evaluate_permission(perm_request)
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.PERMISSION_EVALUATED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                user=request.context.user,
                tool_name=request.tool_name,
                operation=request.operation,
                permission_decision=permission_result.decision.value,
                reason=permission_result.reason,
            )
        )

        # Paso 5: AGREGADOR DE DECISIONES DE SEGURIDAD
        aggregated = self.aggregator.aggregate(
            risk_assessment=risk_assessment,
            policy_decision=policy_result,
            permission_result=permission_result,
            capability_resolution=capability_res,
        )

        # Si el agregador determina DENY directo antes de confirmación -> Detener pipeline
        if not aggregated.is_allowed and not aggregated.requires_confirmation:
            return self._handle_denial(request, aggregated.reason, start_time)

        # Paso 6: CONFIRMATION MANAGER (Si la operación requiere confirmación)
        confirmation_result = None
        if aggregated.requires_confirmation:
            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.CONFIRMATION_REQUESTED,
                    request_id=req_id,
                    correlation_id=corr_id,
                    session_id=sess_id,
                    tool_name=request.tool_name,
                    operation=request.operation,
                )
            )
            self.event_bus.publish("execution:confirmation_required", {"request_id": req_id, "tool_name": request.tool_name})

            conf_req = self.confirmation_manager.create_request(
                tool_name=request.tool_name,
                operation=request.operation,
                parameters=request.parameters,
                risk_level=risk_assessment.risk_level,
                session_id=sess_id,
            )

            if confirmation_provider:
                confirmation_result = self.confirmation_manager.submit_request(conf_req, provider=confirmation_provider)
            else:
                confirmation_result = self.confirmation_manager.get_result(conf_req.request_id)

            # Re-evaluar decisión agregada con el resultado de confirmación
            aggregated = self.aggregator.aggregate(
                risk_assessment=risk_assessment,
                policy_decision=policy_result,
                permission_result=permission_result,
                confirmation_result=confirmation_result,
                capability_resolution=capability_res,
            )

            conf_status = getattr(confirmation_result, "status", None)
            conf_status_str = getattr(conf_status, "value", str(conf_status)) if conf_status else "REJECTED"

            if aggregated.is_allowed:
                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.CONFIRMATION_APPROVED,
                        request_id=req_id,
                        correlation_id=corr_id,
                        session_id=sess_id,
                        confirmation_status="APPROVED",
                    )
                )
            else:
                self.audit_logger.log_audit_event(
                    AuditEvent(
                        event_type=AuditEventType.CONFIRMATION_REJECTED,
                        request_id=req_id,
                        correlation_id=corr_id,
                        session_id=sess_id,
                        confirmation_status=conf_status_str,
                    )
                )
                return self._handle_denial(request, aggregated.reason, start_time)

        # Verificar si la decisión final fue denegada
        if not aggregated.is_allowed:
            return self._handle_denial(request, aggregated.reason, start_time)

        # Paso 7: GENERACIÓN DE EVIDENCIA DE AUTORIZACIÓN (AuthorizationEvidence)
        evidence = create_authorization_evidence(
            request_id=req_id,
            correlation_id=corr_id,
            tool_name=request.tool_name,
            operation=request.operation,
            parameters=request.parameters,
            risk_assessment=risk_assessment,
            policy_result=policy_result,
            permission_result=permission_result,
            confirmation_result=confirmation_result,
        )

        self.event_bus.publish("execution:authorized", {"request_id": req_id, "evidence_id": evidence.evidence_id})

        # Paso 8: EXECUTION_STARTED
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.EXECUTION_STARTED,
                request_id=req_id,
                correlation_id=corr_id,
                session_id=sess_id,
                tool_name=request.tool_name,
                operation=request.operation,
            )
        )
        self.event_bus.publish("execution:started", {"request_id": req_id, "tool_name": request.tool_name})

        # Paso 9: INVOCACIÓN DE LA FRONTERA DE EJECUCIÓN CON EVIDENCIA
        try:
            exec_result = self.boundary.execute_with_evidence(request, evidence)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Paso 10: AUDITORÍA FINAL DE EJECUCIÓN
            if exec_result.status == ExecutionStatus.SUCCESS:
                final_event_type = AuditEventType.EXECUTION_SUCCEEDED
            elif exec_result.status in (ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED):
                final_event_type = AuditEventType.EXECUTION_DISABLED
            else:
                final_event_type = AuditEventType.EXECUTION_FAILED

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=final_event_type,
                    request_id=req_id,
                    correlation_id=corr_id,
                    session_id=sess_id,
                    tool_name=request.tool_name,
                    operation=request.operation,
                    duration_ms=duration_ms,
                    success=(exec_result.status in (ExecutionStatus.SUCCESS, ExecutionStatus.EXECUTION_DISABLED, ExecutionStatus.STUB_DISABLED)),
                )
            )

            self.event_bus.publish("execution:completed", {"request_id": req_id, "status": exec_result.status.value})
            return exec_result

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Error durante la ejecución en frontera para [{req_id}]: {e}")

            self.audit_logger.log_audit_event(
                AuditEvent(
                    event_type=AuditEventType.ERROR,
                    request_id=req_id,
                    correlation_id=corr_id,
                    session_id=sess_id,
                    tool_name=request.tool_name,
                    operation=request.operation,
                    error_message=str(e),
                    duration_ms=duration_ms,
                    success=False,
                )
            )

            self.event_bus.publish("execution:failed", {"request_id": req_id, "error": str(e)})
            raise

    def _handle_denial(
        self,
        request: ExecutionRequest,
        reason: str,
        start_time: float,
    ) -> ExecutionResult:
        """Procesa y registra el rechazo de la ejecución."""
        duration_ms = (time.perf_counter() - start_time) * 1000
        req_id = request.request_id

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.EXECUTION_DENIED,
                request_id=req_id,
                correlation_id=request.correlation_id,
                session_id=request.session_id,
                tool_name=request.tool_name,
                operation=request.operation,
                reason=reason,
                duration_ms=duration_ms,
                success=False,
            )
        )

        self.event_bus.publish("execution:denied", {"request_id": req_id, "reason": reason})

        return ExecutionResult(
            status=ExecutionStatus.DENIED,
            request_id=req_id,
            tool_name=request.tool_name,
            operation=request.operation,
            message=f"Ejecución Denegada: {reason}",
            duration_ms=duration_ms,
            timestamp=datetime.now(UTC),
        )
