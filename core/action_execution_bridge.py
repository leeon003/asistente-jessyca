"""Re-exportación de ActionExecutionBridge en core/ para compatibilidad directa."""

from core.execution.action_execution_bridge import (
    attach_execution_to_contract,
    build_execution_report,
    build_post_action_feedback,
    verify_and_build_execution_report,
)

__all__ = [
    "attach_execution_to_contract",
    "build_execution_report",
    "build_post_action_feedback",
    "verify_and_build_execution_report",
]
