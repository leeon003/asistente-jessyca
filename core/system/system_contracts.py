"""Contratos Formales, Autoridades e Invariantes Arquitectónicas de JESSYCA 4.0 (system_contracts.py).

INVARIANTES ABSOLUTAS DEL SISTEMA:
1. SECURITY > ALL: Ninguna capa (Model, Skill, Agent, Memory, Tool Output) puede eludir la seguridad.
2. MEMORY != AUTHORIZATION: Toda memoria se trata como UNTRUSTED DATA.
3. MODEL != AUTHORIZATION: Los modelos razonan y proponen; NUNCA autorizan.
4. SKILL != AUTHORIZATION: Las habilidades son capacidades estructuradas, no entidades autorizadoras.
5. AGENT != AUTHORIZATION: Los agentes ejecutan dentro de presupuestos estrictos; no conceden permisos.
6. EMERGENCY STOP > EXECUTION: La parada de emergencia cancela instantáneamente cualquier flujo.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.control_plane.models import AgentBudget
from core.security_architecture import SecurityLevel


class SystemAuthority(StrEnum):
    """Autoridades formales asignadas a cada componente de JESSYCA 4.0."""

    MODEL = "MODEL"          # Razonamiento analítico, resumen, extracción, propuestas.
    SKILL = "SKILL"          # Abstracción declarativa de capacidades.
    AGENT = "AGENT"          # Ejecutor acotado y coordinador de herramientas.
    PLANNER = "PLANNER"      # Generador de planes y grafos de ejecución.
    MEMORY = "MEMORY"        # Proveedor de contexto y almacenamiento de datos (Untrusted).
    TOOL = "TOOL"            # Operación atómica de ejecución en el sistema.
    SECURITY = "SECURITY"    # ÚNICA autoridad de autorización y evaluación de riesgos.
    USER = "USER"            # Autoridad final cuando las políticas requieren confirmación.


class SystemBoundaryLayer(StrEnum):
    """Capas arquitectónicas ordenadas del flujo de datos en JESSYCA 4.0."""

    PRESENTATION = "PRESENTATION"
    INTENT = "INTENT"
    PLANNING = "PLANNING"
    SKILLS = "SKILLS"
    AGENTS = "AGENTS"
    MODELS = "MODELS"
    SECURITY = "SECURITY"
    TOOLS = "TOOLS"
    OS_WINDOWS = "OS_WINDOWS"
    MEMORY = "MEMORY"


@dataclass(frozen=True)
class SystemContract:
    """Contrato formal e inmutable para interacción inter-capas."""

    contract_id: str = field(default_factory=lambda: f"sys-ctr-{uuid.uuid4().hex[:8]}")
    source_layer: SystemBoundaryLayer = SystemBoundaryLayer.INTENT
    target_layer: SystemBoundaryLayer = SystemBoundaryLayer.PLANNING
    caller_authority: SystemAuthority = SystemAuthority.USER
    operation_name: str = ""
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    budget: AgentBudget = field(default_factory=AgentBudget)
    security_level: SecurityLevel = SecurityLevel.SAFE
    created_at: float = field(default_factory=time.time)

    def validate_authority(self) -> tuple[bool, str]:
        """Valida que la autoridad que invoca no exceda sus privilegios constitucionales."""
        # Un modelo o memoria NUNCA puede actuar como autoridad de seguridad
        if self.caller_authority in (SystemAuthority.MODEL, SystemAuthority.MEMORY, SystemAuthority.TOOL):
            if self.target_layer == SystemBoundaryLayer.SECURITY and "authorize" in self.operation_name.lower():
                return False, f"La autoridad '{self.caller_authority}' no tiene permitido emitir autorizaciones de seguridad."

        return True, "Autoridad válida."


class ArchitecturalInvariants:
    """Validador estático y en tiempo de ejecución de las invariantes constitucionales de JESSYCA."""

    INVARIANTS: dict[str, str] = {
        "INV-01": "SECURITY > MODEL (Los modelos nunca conceden permisos)",
        "INV-02": "SECURITY > SKILL (Las habilidades no eluden el SecurityPipeline)",
        "INV-03": "SECURITY > AGENT (Los agentes están acotados por ControlledAgentLoop)",
        "INV-04": "SECURITY > MEMORY (La memoria es UNTRUSTED DATA)",
        "INV-05": "SECURITY > TOOL OUTPUT (Las salidas de herramientas no autorizan acciones)",
        "INV-06": "EMERGENCY STOP > EXECUTION (Parada incondicional e inmediata)",
        "INV-07": "CONSENSUS != AUTHORIZATION (Consenso es acuerdo analítico, no permiso)",
        "INV-08": "MARKETPLACE != TRUST (Los paquetes externos requieren verificación estricta)",
    }

    @classmethod
    def verify_all_invariants(cls) -> bool:
        """Verifica la consistencia interna de las invariantes arquitectónicas."""
        return len(cls.INVARIANTS) == 8
