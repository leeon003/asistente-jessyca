"""Conector opcional para tareas de desarrollo; no reemplaza JESSYCA BRAIN.

SDK real de OpenHands: https://github.com/OpenHands/software-agent-sdk
La ejecución está prohibida sin aprobación explícita y sandbox independiente.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DevelopmentTask:
    instruction: str
    workspace: Path
    approved: bool = False


@dataclass(frozen=True)
class DevelopmentResult:
    success: bool
    message: str
    output: str = ""


class OpenHandsBrainProvider:
    """Proveedor especializado inyectable, desactivado hasta configuración."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        sandbox_root: str | Path | None = None,
        runner: Callable[[str, Path], str] | None = None,
        risk_engine: Any | None = None,
    ):
        self.enabled = enabled
        self.sandbox_root = Path(sandbox_root).resolve() if sandbox_root is not None else None
        self.runner = runner
        self.risk_engine = risk_engine

    def run(self, task: DevelopmentTask) -> DevelopmentResult:
        if not self.enabled:
            return DevelopmentResult(False, "OpenHands desactivado")
        if not task.approved:
            return DevelopmentResult(False, "Requiere aprobación explícita")
        if self.sandbox_root is None or self.runner is None:
            return DevelopmentResult(False, "Sandbox o ejecutor no configurado")
        if not task.instruction.strip():
            return DevelopmentResult(False, "Tarea vacía")
        target = Path(task.workspace).resolve()
        try:
            target.relative_to(self.sandbox_root)
        except ValueError:
            return DevelopmentResult(False, "Directorio fuera del sandbox")
        if target == self.sandbox_root or not target.is_dir():
            return DevelopmentResult(False, "Se requiere subdirectorio aislado existente")
        # RiskEngine is mandatory for execution; fail closed on errors or uncertain levels.
        if self.risk_engine is None:
            return DevelopmentResult(False, "RiskEngine no configurado")
        try:
            assessment = self.risk_engine.evaluate_risk(
                "openhands_write", {"instruction": task.instruction, "workspace": str(target)}
            )
            level = str(getattr(assessment.risk_level, "value", assessment.risk_level)).upper()
            if level not in {"SAFE", "READ_ONLY", "WARNING"}:
                return DevelopmentResult(False, "RiskEngine bloqueó la tarea")
        except Exception:
            return DevelopmentResult(False, "Evaluación de riesgo fallida")
        try:
            result = self.runner(task.instruction, target)
        except Exception as exc:
            return DevelopmentResult(False, f"OpenHands falló: {type(exc).__name__}")
        return DevelopmentResult(True, "Tarea terminada (requiere verificar cambios)", str(result))


def make_openhands_sdk_runner(*, model: str, api_key: str) -> Callable[[str, Path], str]:
    """Crea un ejecutor SDK, destinado EXCLUSIVAMENTE a un sandbox ya aislado.

    El aislamiento de rutas Python NO es una jaula OS. No invocar con acceso
    al Windows anfitrión o con credenciales sensibles dentro del workspace.
    """
    if not model or not api_key:
        raise ValueError("Modelo y credenciales deben configurarse explícitamente")

    def execute(instruction: str, workspace: Path) -> str:
        try:
            from openhands.sdk import Agent, Conversation, LLM, Tool
            from openhands.tools.file_editor import FileEditorTool
            from openhands.tools.task_tracker import TaskTrackerTool
            from openhands.tools.terminal import TerminalTool
        except ImportError as exc:
            raise RuntimeError("OpenHands SDK no instalado") from exc
        llm = LLM(model=model, api_key=api_key)
        agent = Agent(
            llm=llm,
            tools=[
                Tool(name=FileEditorTool.name),
                Tool(name=TaskTrackerTool.name),
                Tool(name=TerminalTool.name),
            ],
        )
        conversation = Conversation(agent=agent, workspace=str(workspace))
        conversation.send_message(instruction)
        conversation.run()
        return "OpenHands SDK terminó; verificar archivos y pruebas"
    return execute
