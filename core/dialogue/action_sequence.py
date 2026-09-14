"""Manejador de Secuencias de Acciones (action_sequence.py - Fase 64.3.3).

Define los modelos estructurados para representar, planificar y orquestar
solicitudes compuestas y secuencias de acciones relacionadas (ActionSequence)
manteniendo estrictamente los controles de seguridad de JESSYCA:

PRINCIPIO FUNDAMENTAL (Fase 64.3.3):
Multi-step NO significa "ejecutar todo de golpe".
Significa "gestionar una secuencia de acciones manteniendo el contexto y los controles de seguridad".
Cada paso pasa individualmente por:
  Planner -> ExecutionGate -> Confirmation -> Dispatcher -> Verification -> Feedback

INVARIANTES:
1. ORDEN ESTRICTO: Las acciones se ejecutan en orden secuencial.
2. POLÍTICA STOP_ON_FAILURE: Si un paso falla, los pasos posteriores dependientes NO se ejecutan.
3. PAUSA POR CONFIRMACIÓN: Si un paso requiere confirmación humana, la secuencia se PAUSA
   en estado WAITING_CONFIRMATION y no despacha ningún paso posterior.
4. IDENTIFICADORES ÚNICOS E IDEMPOTENCIA: Cada paso tiene su propio step_id y action_id único.
   El reprocesamiento detecta pasos ya completados y no duplica ejecuciones.
5. SIN BYPASS: Ningún paso salta el ActionPipeline ni llama directamente al Dispatcher.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core.logger import get_logger

if TYPE_CHECKING:
    from core.action_intent_contract import ActionIntentContract
    from core.dialogue.conversational_intent_continuity import ActionContext
    from core.execution.action_pipeline import ActionPipelineResult

logger = get_logger("jessyca.dialogue.action_sequence")


class ActionSequenceStatus(StrEnum):
    """Estados del ciclo de vida de una secuencia de acciones (Fase 64.3.3)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STEP_REJECTED = "STEP_REJECTED"


class ActionStepStatus(StrEnum):
    """Estados individuales de cada paso dentro de la secuencia."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class SequenceFailurePolicy(StrEnum):
    """Políticas de actuación ante fallo en un paso de la secuencia."""

    STOP_ON_FAILURE = "STOP_ON_FAILURE"
    CONTINUE_ON_FAILURE = "CONTINUE_ON_FAILURE"


@dataclass
class ActionStep:
    """Paso individual estructurado dentro de una secuencia de acciones."""

    step_id: str = field(default_factory=lambda: f"step-{uuid.uuid4().hex[:8]}")
    step_number: int = 1
    action_id: str = field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    intent: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    target: str = ""
    risk_level: str | None = None
    description: str = ""
    status: ActionStepStatus = ActionStepStatus.PENDING
    contract: ActionIntentContract | None = None
    pipeline_result: ActionPipelineResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa el paso a un diccionario."""
        return {
            "step_id": self.step_id,
            "step_number": self.step_number,
            "action_id": self.action_id,
            "intent": self.intent,
            "parameters": self.parameters,
            "target": self.target,
            "risk_level": self.risk_level,
            "description": self.description,
            "status": str(self.status),
            "error": self.error,
        }


@dataclass
class ActionSequence:
    """Representación formal de una secuencia multi-paso de acciones relacionadas."""

    sequence_id: str = field(default_factory=lambda: f"seq-{uuid.uuid4().hex[:8]}")
    session_id: str = ""
    raw_input: str = ""
    steps: list[ActionStep] = field(default_factory=list)
    current_step_index: int = 0
    overall_status: ActionSequenceStatus = ActionSequenceStatus.PENDING
    policy: SequenceFailurePolicy = SequenceFailurePolicy.STOP_ON_FAILURE
    created_at: float = field(default_factory=time.time)
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def current_step(self) -> int:
        """Número del paso actual (1-based)."""
        return self.current_step_index + 1

    @property
    def completed_steps(self) -> list[ActionStep]:
        """Lista de pasos que han culminado con éxito verificado."""
        return [s for s in self.steps if s.status == ActionStepStatus.COMPLETED]

    @property
    def failed_steps(self) -> list[ActionStep]:
        """Lista de pasos que han fallado."""
        return [s for s in self.steps if s.status == ActionStepStatus.FAILED]

    @property
    def pending_step(self) -> ActionStep | None:
        """Paso actualmente en espera de confirmación o ejecución."""
        for s in self.steps:
            if s.status in (ActionStepStatus.WAITING_CONFIRMATION, ActionStepStatus.RUNNING):
                return s
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def is_terminal(self) -> bool:
        """Indica si la secuencia ha terminado (éxito, fallo o cancelación)."""
        return self.overall_status in (
            ActionSequenceStatus.COMPLETED,
            ActionSequenceStatus.FAILED,
            ActionSequenceStatus.CANCELLED,
            ActionSequenceStatus.STEP_REJECTED,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa la secuencia a un diccionario."""
        return {
            "sequence_id": self.sequence_id,
            "session_id": self.session_id,
            "raw_input": self.raw_input,
            "steps": [s.to_dict() for s in self.steps],
            "current_step": self.current_step,
            "completed_steps": [s.to_dict() for s in self.completed_steps],
            "failed_steps": [s.to_dict() for s in self.failed_steps],
            "pending_step": self.pending_step.to_dict() if self.pending_step else None,
            "overall_status": str(self.overall_status),
            "policy": str(self.policy),
        }


# ── PLANIFICADOR DETERMINISTA DE PASOS (STEP PLANNER) ─────────────────────────


# Mapeo canónico de nombres de aplicación
_CANONICAL_APPS: dict[str, str] = {
    "notepad": "notepad",
    "bloc de notas": "notepad",
    "el bloc de notas": "notepad",
    "bloc notas": "notepad",
    "bloc": "notepad",
    "notas": "notepad",
    "calculadora": "calc",
    "la calculadora": "calc",
    "calc": "calc",
    "chrome": "chrome",
    "google chrome": "chrome",
    "el navegador": "chrome",
    "navegador": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "paint": "paint",
    "cmd": "cmd",
    "spotify": "spotify",
    "youtube": "youtube",
}


def _normalize_app(raw: str) -> str:
    """Normaliza un nombre de aplicación a su identificador canónico."""
    clean = raw.strip().lower()
    return _CANONICAL_APPS.get(clean, clean)


class StepPlanner:
    """Planificador determinista que convierte entradas compuestas en ActionSequences.

    Soporta:
    1. Conectores secuenciales: "y luego", "y después", "luego", "después", ", luego"
    2. Coordinación de dos acciones: "Abre Chrome y Bloc de notas" -> 2 aperturas
    3. Acciones combinadas dependientes: "Abre Bloc de notas y luego ciérralo"
    4. Acciones opuestas: "Abre Chrome y luego cierra Bloc de notas"
    5. Secuencias derivadas de referentes plurales ("ciérralos" -> cerrar app1, cerrar app2)
    """

    def __init__(self) -> None:
        self._mutex = threading.Lock()

    def is_compound_or_sequence(self, user_input: str) -> bool:
        """Determina si una orden contiene indicadores explícitos de secuencia compuesta."""
        cleaned = user_input.strip().lower()
        if not cleaned:
            return False

        # Conectores temporales inequívocos
        temporal_patterns = [
            r"\s+y\s+luego\s+",
            r"\s+y\s+despu[eé]s\s+",
            r"\s*,\s*luego\s+",
            r"\s*,\s*despu[eé]s\s+",
            r"\s+luego\s+",
            r"\s+despu[eé]s\s+",
            r"\s+y\s+a\s+continuaci[oó]n\s+",
        ]
        for p in temporal_patterns:
            if re.search(p, cleaned):
                return True

        # Patrones de doble aplicación en una sola orden ("Abre Chrome y Bloc de notas")
        if re.match(r"^(?:jessyca,?\s*)?(?:abre|inicia|ejecuta)\s+[a-záéíóú\s]+\s+y\s+[a-záéíóú\s]+$", cleaned):
            return True

        # Patrones de doble cierre ("Cierra Chrome y Bloc de notas")
        if re.match(r"^(?:jessyca,?\s*)?(?:cierra|apaga|termina)\s+[a-záéíóú\s]+\s+y\s+[a-záéíóú\s]+$", cleaned):
            return True

        # Patrones de acción mixta ("Abre Chrome y cierra Bloc de notas")
        if re.match(
            r"^(?:jessyca,?\s*)?(?:abre|inicia)\s+[a-záéíóú\s]+\s+y\s+(?:cierra|apaga|termina)\s+[a-záéíóú\s]+$",
            cleaned,
        ):
            return True

        return False

    def plan_sequence(
        self,
        user_input: str,
        session_id: str,
        context: ActionContext | None = None,
    ) -> ActionSequence | None:
        """Construye un ActionSequence si la entrada es compuesta, o None si es simple.

        Aplica resolución de pronombres anafóricos dependientes entre pasos:
        Ejemplo: "Abre Bloc de notas y luego ciérralo"
        Paso 1: open_application(notepad)
        Paso 2: close_application(notepad)  [resolviendo 'lo' -> 'notepad' del paso 1]
        """
        cleaned = user_input.strip()
        lower = cleaned.lower()

        if not self.is_compound_or_sequence(cleaned):
            return None

        # ── CASO 1: Separadores temporales explícitos (soporte para N >= 2 pasos) ───
        connector_pattern = r"(?:\s*,\s*(?:luego|despu[eé]s)\s*|\s+(?:y\s+luego|y\s+despu[eé]s|luego|despu[eé]s|y\s+a\s+continuaci[oó]n)\s+)"
        raw_parts = [p.strip() for p in re.split(connector_pattern, cleaned, flags=re.IGNORECASE) if p.strip()]
        if len(raw_parts) >= 2:
            parsed_steps: list[ActionStep] = []
            prev_target: str | None = None
            for idx, part in enumerate(raw_parts, start=1):
                step = self._parse_single_clause(
                    part,
                    step_number=idx,
                    inherited_target=prev_target,
                    context=context,
                )
                if not step:
                    parsed_steps = []
                    break
                prev_target = step.target
                parsed_steps.append(step)

            if len(parsed_steps) >= 2:
                return ActionSequence(
                    session_id=session_id,
                    raw_input=cleaned,
                    steps=parsed_steps,
                    policy=SequenceFailurePolicy.STOP_ON_FAILURE,
                )

        # ── CASO 2: "Abre X y cierra Y" ──────────────────────────────────────
        mixed_match = re.match(
            r"^(?:jessyca,?\s*)?(?:abre|inicia)\s+(.+?)\s+y\s+(?:cierra|apaga|termina)\s+(.+)$",
            lower,
        )
        if mixed_match:
            app1 = _normalize_app(mixed_match.group(1))
            app2 = _normalize_app(mixed_match.group(2))
            s1 = ActionStep(
                step_number=1,
                intent="open_application",
                target=app1,
                parameters={"app_name": app1, "nombre_app": app1},
                risk_level="SAFE",
                description=f"Abrir {app1}",
            )
            s2 = ActionStep(
                step_number=2,
                intent="close_application",
                target=app2,
                parameters={"app_name": app2, "nombre_app": app2},
                risk_level="HIGH",
                description=f"Cerrar {app2}",
            )
            return ActionSequence(
                session_id=session_id,
                raw_input=cleaned,
                steps=[s1, s2],
                policy=SequenceFailurePolicy.STOP_ON_FAILURE,
            )

        # ── CASO 3: "Abre X y Y" ─────────────────────────────────────────────
        open_two_match = re.match(
            r"^(?:jessyca,?\s*)?(?:abre|inicia|ejecuta)\s+(.+?)\s+y\s+(.+)$",
            lower,
        )
        if open_two_match:
            app1 = _normalize_app(open_two_match.group(1))
            app2 = _normalize_app(open_two_match.group(2))
            s1 = ActionStep(
                step_number=1,
                intent="open_application",
                target=app1,
                parameters={"app_name": app1, "nombre_app": app1},
                risk_level="SAFE",
                description=f"Abrir {app1}",
            )
            s2 = ActionStep(
                step_number=2,
                intent="open_application",
                target=app2,
                parameters={"app_name": app2, "nombre_app": app2},
                risk_level="SAFE",
                description=f"Abrir {app2}",
            )
            return ActionSequence(
                session_id=session_id,
                raw_input=cleaned,
                steps=[s1, s2],
                policy=SequenceFailurePolicy.STOP_ON_FAILURE,
            )

        # ── CASO 4: "Cierra X y Y" ───────────────────────────────────────────
        close_two_match = re.match(
            r"^(?:jessyca,?\s*)?(?:cierra|apaga|termina)\s+(.+?)\s+y\s+(.+)$",
            lower,
        )
        if close_two_match:
            app1 = _normalize_app(close_two_match.group(1))
            app2 = _normalize_app(close_two_match.group(2))
            s1 = ActionStep(
                step_number=1,
                intent="close_application",
                target=app1,
                parameters={"app_name": app1, "nombre_app": app1},
                risk_level="HIGH",
                description=f"Cerrar {app1}",
            )
            s2 = ActionStep(
                step_number=2,
                intent="close_application",
                target=app2,
                parameters={"app_name": app2, "nombre_app": app2},
                risk_level="HIGH",
                description=f"Cerrar {app2}",
            )
            return ActionSequence(
                session_id=session_id,
                raw_input=cleaned,
                steps=[s1, s2],
                policy=SequenceFailurePolicy.STOP_ON_FAILURE,
            )

        return None

    def plan_plural_sequence(
        self,
        intent: str,
        targets: list[str],
        session_id: str,
        raw_input: str = "",
    ) -> ActionSequence:
        """Construye un ActionSequence a partir de una orden plural resuelta (ej. 'ciérralos')."""
        steps: list[ActionStep] = []
        is_high_risk = any(w in intent for w in ("close", "delete", "kill", "terminate"))

        for idx, t in enumerate(targets, start=1):
            norm_t = _normalize_app(t)
            steps.append(
                ActionStep(
                    step_number=idx,
                    intent=intent,
                    target=norm_t,
                    parameters={"app_name": norm_t, "nombre_app": norm_t},
                    risk_level="HIGH" if is_high_risk else "SAFE",
                    description=f"{'Cerrar' if is_high_risk else 'Abrir'} {norm_t}",
                )
            )

        return ActionSequence(
            session_id=session_id,
            raw_input=raw_input,
            steps=steps,
            policy=SequenceFailurePolicy.STOP_ON_FAILURE,
        )

    def _parse_single_clause(
        self,
        clause: str,
        step_number: int,
        inherited_target: str | None = None,
        context: ActionContext | None = None,
    ) -> ActionStep | None:
        """Interpreta una cláusula individual y construye su ActionStep correspondiente."""
        cl = clause.strip().lower()

        # Quitar prefijo de saludo o nombre del bot si existe
        cl = re.sub(r"^(?:jessyca,?\s*|jessica,?\s*)", "", cl).strip()

        # 1. Pronombre enclítico dependiente ("ciérralo", "ciérrala", "ciérralos", etc.)
        if re.match(r"^(?:ci[eé]rralo|ci[eé]rrala|ci[eé]rralos|ci[eé]rralas)$", cl):
            target = inherited_target or (context.target if context else "app")
            return ActionStep(
                step_number=step_number,
                intent="close_application",
                target=target,
                parameters={"app_name": target, "nombre_app": target},
                risk_level="HIGH",
                description=f"Cerrar {target}",
            )

        if re.match(r"^(?:[aá]brelo|[aá]brela|[aá]brelos|[aá]brelas)$", cl):
            target = inherited_target or (context.target if context else "app")
            return ActionStep(
                step_number=step_number,
                intent="open_application",
                target=target,
                parameters={"app_name": target, "nombre_app": target},
                risk_level="SAFE",
                description=f"Abrir {target}",
            )

        # 2. Cierre explícito ("cierra Bloc de notas")
        close_m = re.match(r"^(?:cierra|apaga|termina|kill)\s+(.+)$", cl)
        if close_m:
            target_str = _normalize_app(close_m.group(1))
            return ActionStep(
                step_number=step_number,
                intent="close_application",
                target=target_str,
                parameters={"app_name": target_str, "nombre_app": target_str},
                risk_level="HIGH",
                description=f"Cerrar {target_str}",
            )

        # 3. Apertura explícita ("abre Chrome")
        open_m = re.match(r"^(?:abre|inicia|ejecuta|lanza)\s+(.+)$", cl)
        if open_m:
            raw_target = open_m.group(1).strip()
            # Si el target es youtube o una web
            if "youtube" in raw_target:
                return ActionStep(
                    step_number=step_number,
                    intent="browser_open",
                    target="youtube",
                    parameters={"url": "https://www.youtube.com"},
                    risk_level="SAFE",
                    description="Abrir YouTube en el navegador",
                )
            target_str = _normalize_app(raw_target)
            return ActionStep(
                step_number=step_number,
                intent="open_application",
                target=target_str,
                parameters={"app_name": target_str, "nombre_app": target_str},
                risk_level="SAFE",
                description=f"Abrir {target_str}",
            )

        # 4. Multimedia: reproducir, pausar
        if re.match(r"^(?:pausa|det[eé]n)\s+(?:la\s+m[uú]sica|el\s+video|eso)$", cl) or cl in ("páusala", "pausala"):
            return ActionStep(
                step_number=step_number,
                intent="pause_media",
                target="media",
                parameters={"accion": "pause"},
                risk_level="SAFE",
                description="Pausar reproducción multimedia",
            )

        # 5. Nombre de app simple en cláusula subsecuente hereda acción de apertura
        # Ej: "abre Chrome, luego Bloc de notas y después Spotify"
        if step_number > 1 or inherited_target is not None:
            norm_bare = _normalize_app(cl)
            if norm_bare in _CANONICAL_APPS.values() or cl in _CANONICAL_APPS:
                return ActionStep(
                    step_number=step_number,
                    intent="open_application",
                    target=norm_bare,
                    parameters={"app_name": norm_bare, "nombre_app": norm_bare},
                    risk_level="SAFE",
                    description=f"Abrir {norm_bare}",
                )

        return None
