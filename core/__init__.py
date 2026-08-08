"""Módulo core de Jessyca Windows MCP."""

from core.capability import CapabilityManager, ToolCapabilitySpec
from core.constants import APP_NAME, APP_VERSION
from core.context_manager import ContextItem, ContextManager
from core.contracts import ISecurityManager, IService, ITool, IToolRegistry
from core.event_bus import (
    Event,
    EventBus,
    EventPriority,
    Subscription,
    get_event_bus,
)
from core.exceptions import (
    ConfigurationError,
    JessycaError,
    MCPError,
    ToolExecutionError,
    ToolNotFoundError,
    ValidationError,
    WindowsPlatformError,
)
from core.executor import (
    PlanExecutionResult,
    RollbackAction,
    TaskExecutionResult,
    TaskExecutor,
)
from core.logger import get_logger, setup_logger
from core.planner import AIPlanner, ExecutionPlan, SubTask
from core.security import (
    AuditRecord,
    RiskLevel,
    SecurityDecision,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
    check_hierarchical_permission,
)
from core.session_manager import Session, SessionManager, ToolExecutionLog
from core.types import EnvironmentMode, LogLevel, Result, WindowsVersion

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "IService",
    "ITool",
    "IToolRegistry",
    "ISecurityManager",
    "JessycaError",
    "ConfigurationError",
    "WindowsPlatformError",
    "MCPError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ValidationError",
    "get_logger",
    "setup_logger",
    "EnvironmentMode",
    "LogLevel",
    "Result",
    "WindowsVersion",
    "RiskLevel",
    "SecurityStatus",
    "ToolSecurityProfile",
    "SecurityDecision",
    "SecurityPolicy",
    "check_hierarchical_permission",
    "AuditRecord",
    "SecurityManager",
    "ToolCapabilitySpec",
    "CapabilityManager",
    "ContextItem",
    "ContextManager",
    "ToolExecutionLog",
    "Session",
    "SessionManager",
    "Event",
    "EventPriority",
    "Subscription",
    "EventBus",
    "get_event_bus",
    "SubTask",
    "ExecutionPlan",
    "AIPlanner",
    "RollbackAction",
    "TaskExecutionResult",
    "PlanExecutionResult",
    "TaskExecutor",
]
