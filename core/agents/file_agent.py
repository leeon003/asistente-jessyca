"""Agente especializado en operaciones de archivos acotado al sandbox (file_agent.py - Fase 7 & 9).

Restringido exclusivamente al directorio sandbox/.
INVARIANTE CRÍTICA:
Cualquier intento de acceso, lectura o escritura fuera de sandbox/ es bloqueado inmediatamente.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.agents.agent_budget import create_file_agent_budget
from core.agents.base_agent import AgentIdentity, BaseSpecializedAgent
from core.control_plane.models import AgentBudget
from core.emergency_stop import EmergencyStopManager
from core.tool_planner import ControlledToolPlanner

FILE_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "filesystem.read",
    "filesystem.write",
    "filesystem.list",
    "filesystem.search",
    "file.read",
    "file.write",
    "file.list",
    "file.search",
    "document.read",
    "document.write",
    "document.create",
    "buscar_archivo",
    "leer_archivo",
    "escribir_archivo",
})


class FileAgent(BaseSpecializedAgent):
    """Agente especializado en operaciones de archivos confinado estrictamente a sandbox/."""

    def __init__(
        self,
        sandbox_dir: str = "sandbox",
        budget: AgentBudget | None = None,
        planner: ControlledToolPlanner | None = None,
        emergency_stop: EmergencyStopManager | None = None,
        action_executor: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        action_verifier: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        identity = AgentIdentity(
            agent_id="agent_file",
            name="FileAgent",
            description="Agente especializado en operaciones de archivos acotado al directorio sandbox/.",
            role="file_operations",
        )
        capabilities = (
            "file_read",
            "file_write",
            "file_list",
            "sandbox_only",
        )
        effective_budget = budget or create_file_agent_budget()
        self.sandbox_dir = sandbox_dir

        super().__init__(
            identity=identity,
            capabilities=capabilities,
            allowed_tools=FILE_ALLOWED_TOOLS,
            risk_ceiling=effective_budget.max_risk,
            budget=effective_budget,
            planner=planner,
            emergency_stop=emergency_stop,
            action_executor=action_executor,
            action_verifier=action_verifier,
        )

    def _additional_tool_validation(
        self,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str]:
        """Garantiza que toda ruta operada por FileAgent resida estrictamente dentro de sandbox/."""
        path_keys = ("path", "ruta", "file_path", "filename", "nombre_archivo", "directorio")

        for key in path_keys:
            raw_path = params.get(key)
            if raw_path and isinstance(raw_path, str):
                clean_path = raw_path.strip()

                # 1. Detección directa de path traversal
                if ".." in clean_path:
                    return (
                        False,
                        f"Violación de Sandbox por 'FileAgent': Intento de Path Traversal detectado en '{clean_path}'.",
                    )

                # 2. Comprobar contención en sandbox
                normalized = clean_path.replace("\\", "/").lstrip("/")
                if not normalized.startswith("sandbox/") and normalized != "sandbox":
                    # Si es una ruta absoluta, comprobar si reside dentro del sandbox absoluto
                    try:
                        abs_target = Path(clean_path).resolve()
                        abs_sandbox = Path(self.sandbox_dir).resolve()
                        if not str(abs_target).startswith(str(abs_sandbox)):
                            return (
                                False,
                                f"Violación de Sandbox por 'FileAgent': La ruta '{clean_path}' "
                                f"está fuera del directorio permitido '{self.sandbox_dir}/'.",
                            )
                    except Exception:
                        return (
                            False,
                            f"Violación de Sandbox por 'FileAgent': Ruta inválida o no permitida '{clean_path}'.",
                        )

        return True, "FileAgent sandbox check OK"
