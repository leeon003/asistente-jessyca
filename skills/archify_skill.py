"""Habilidad de Visualización y Diagramación Técnica con Archify (skills/archify_skill.py).

Fase 1: Laboratorio y Aislamiento.
Expone la capacidad de generar y validar diagramas interactivos (arquitectura, workflow, secuencia)
gobernada por JDE y el adapter seguro.
"""

from __future__ import annotations

import os
from typing import Any

from core.archify.adapter import (
    ArchifyDiagramType,
    ArchifyMode,
    JessycaArchifyAdapter,
    get_archify_adapter,
)
from core.execution.execution_verifier import get_execution_verifier
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillContext,
    SkillDefinition,
    SkillManifest,
    SkillResult,
    SkillStatus,
)

logger = get_logger("jessyca.skills.archify")


def generate_mermaid_fallback(spec: dict[str, Any], diagram_type: str) -> str:
    """Genera representación alternativa en Mermaid para fallback controlado."""
    title = str(spec.get("title", f"Diagrama de {diagram_type}"))
    nodes = spec.get("nodes", spec.get("components", spec.get("participants", spec.get("states", []))))
    edges = spec.get("edges", spec.get("connections", spec.get("messages", spec.get("transitions", []))))

    clean_type = diagram_type.strip().lower()
    if clean_type == "sequence":
        lines = ["sequenceDiagram", "    autonumber", f"    %% {title}"]
        if isinstance(nodes, list):
            for n in nodes:
                nid = str(n.get("id", "")) if isinstance(n, dict) else str(n)
                nlabel = str(n.get("name", n.get("label", nid))) if isinstance(n, dict) else str(n)
                if nid:
                    lines.append(f"    participant {nid} as {nlabel}")
        if isinstance(edges, list):
            for e in edges:
                if isinstance(e, dict):
                    src = str(e.get("from", e.get("source", "")))
                    dst = str(e.get("to", e.get("target", "")))
                    msg = str(e.get("label", e.get("message", "interacción")))
                    if src and dst:
                        lines.append(f"    {src}->>{dst}: {msg}")
        return "\n".join(lines)
    else:
        lines = ["graph TD", f"    %% {title}"]
        if isinstance(nodes, list):
            for n in nodes:
                nid = str(n.get("id", "")) if isinstance(n, dict) else str(n)
                nlabel = str(n.get("name", n.get("label", nid))) if isinstance(n, dict) else str(n)
                if nid:
                    clean_lbl = nlabel.replace('"', "'")
                    lines.append(f'    {nid}["{clean_lbl}"]')
        if isinstance(edges, list):
            for e in edges:
                if isinstance(e, dict):
                    src = str(e.get("from", e.get("source", "")))
                    dst = str(e.get("to", e.get("target", "")))
                    lbl = str(e.get("label", ""))
                    if src and dst:
                        if lbl:
                            clean_elbl = lbl.replace('"', "'")
                            lines.append(f'    {src} -->|"{clean_elbl}"| {dst}')
                        else:
                            lines.append(f"    {src} --> {dst}")
        return "\n".join(lines)


class ArchifySkill(BaseSkill):
    """Skill para crear diagramas interactivos de arquitectura y flujos de software (Fase 2)."""

    def __init__(self, adapter: JessycaArchifyAdapter | None = None) -> None:
        manifest = SkillManifest(
            id="tools.archify",
            name="Archify Technical Diagrammer",
            version="2.0.0",
            description="Genera y valida diagramas técnicos interactivos (arquitectura, secuencias, workflows, dataflows, lifecycles) en HTML/SVG interactivo.",
            author="tt-a1i / Jessyca Integration",
            capabilities=("architecture", "workflow", "sequence", "dataflow", "lifecycle", "diagram_generation"),
            required_tools=("archify",),
            permissions=("tools.archify",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="tools.archify",
            name="Archify Technical Diagrammer",
            version="2.0.0",
            description="Visualización y diagramación técnica interactiva certificada.",
            capabilities=("architecture", "workflow", "sequence", "dataflow", "lifecycle", "diagram_generation"),
            required_tools=("archify",),
            required_permissions=("tools.archify",),
            risk_level=SecurityLevel.SAFE,
            tags=("diagrama", "arquitectura", "workflow", "secuencia", "dataflow", "lifecycle", "archify"),
        )
        super().__init__(nombre="tools.archify", nivel_riesgo=1, definition=def_obj)
        self.adapter = adapter or get_archify_adapter()

    def descripcion(self) -> str:
        return "Crea diagramas técnicos interactivos verificables a partir de especificaciones de componentes o flujos."

    def execute(self, context: SkillContext) -> SkillResult:
        """Ejecuta la acción solicitada respetando el modo del adapter (Shadow, Controlled, Active)."""
        params = context.parameters or {}
        action = str(params.get("action", "render")).lower()
        diagram_type = str(params.get("diagram_type", "architecture")).lower()
        spec = params.get("spec", {})
        allow_fallback = bool(params.get("allow_fallback", False))
        decision_id = str(params.get("decision_id", ""))
        operation_id = str(params.get("operation_id", ""))

        if not isinstance(spec, dict):
            return SkillResult(
                status=SkillStatus.ERROR,
                error="El parámetro 'spec' debe ser un objeto JSON/dict.",
            )

        if action in ("mermaid", "generate_mermaid"):
            mermaid_code = generate_mermaid_fallback(spec, diagram_type)
            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                status=SkillStatus.COMPLETED,
                output={
                    "provider": "mermaid",
                    "diagram_type": diagram_type,
                    "code": mermaid_code,
                    "message": f"Diagrama Mermaid generado para {diagram_type}.",
                },
            )

        if action == "validate":
            val = self.adapter.validate_spec(spec, diagram_type)
            return SkillResult(
                skill_id=self.skill_id,
                success=val.is_valid,
                status=SkillStatus.COMPLETED if val.is_valid else SkillStatus.FAILED,
                output={
                    "is_valid": val.is_valid,
                    "errors": val.errors,
                    "warnings": val.warnings,
                    "node_count": val.node_count,
                    "edge_count": val.edge_count,
                },
            )

        # Si el adapter está en OFF
        if self.adapter.current_mode == ArchifyMode.OFF:
            if allow_fallback:
                mermaid_code = generate_mermaid_fallback(spec, diagram_type)
                self.adapter.metrics.fallbacks += 1
                return SkillResult(
                    skill_id=self.skill_id,
                    success=True,
                    status=SkillStatus.COMPLETED,
                    output={
                        "primary_provider": "archify",
                        "fallback_provider": "mermaid",
                        "fallback_reason": "Archify en modo OFF",
                        "diagram_type": diagram_type,
                        "code": mermaid_code,
                        "message": "Fallback a Mermaid ejecutado (Archify desactivado).",
                    },
                )
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error="Archify está desactivado (mode=OFF).",
            )

        # Si el adapter está en SHADOW, registra la observación sin tocar el disco de producción
        if self.adapter.current_mode == ArchifyMode.SHADOW:
            obs = self.adapter.observe_shadow(
                intent=context.session_id or "diagram_request",
                proposed_spec=spec,
                diagram_type=diagram_type,
            )
            return SkillResult(
                skill_id=self.skill_id,
                success=True,
                status=SkillStatus.COMPLETED,
                output={
                    "mode": "SHADOW",
                    "observation_id": obs.observation_id,
                    "validation_status": obs.validation_status,
                    "verdict": obs.comparison_verdict,
                    "message": "Diagrama evaluado en Shadow Mode sin escribir en producción.",
                },
            )

        # Modo CONTROLLED o ACTIVE: comprobar CapabilityRegistry
        from core.jde.capabilities import get_capability_registry
        registry = get_capability_registry()
        cap = registry.get(f"diagram_generation.{diagram_type}")
        if cap is None or not cap.enabled:
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=f"DENIED: Capacidad 'diagram_generation.{diagram_type}' no está autorizada o está deshabilitada en CapabilityRegistry.",
            )

        render_res = self.adapter.render_diagram(
            spec=spec,
            diagram_type=diagram_type,
            filename=params.get("filename"),
            decision_id=decision_id,
            operation_id=operation_id,
        )
        success, msg, path = render_res

        if not success:
            if allow_fallback:
                mermaid_code = generate_mermaid_fallback(spec, diagram_type)
                self.adapter.metrics.fallbacks += 1
                return SkillResult(
                    skill_id=self.skill_id,
                    success=True,
                    status=SkillStatus.COMPLETED,
                    output={
                        "primary_provider": "archify",
                        "fallback_provider": "mermaid",
                        "fallback_reason": msg,
                        "diagram_type": diagram_type,
                        "code": mermaid_code,
                        "message": f"Fallback a Mermaid activado debido a fallo en renderizado: {msg}",
                    },
                )
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=msg,
            )

        # Verificación determinista mediante ExecutionVerifier con integridad de checksum e identidad
        meta = render_res.metadata
        verification_params = {
            "path": path,
            "artifact_path": path,
            "expected_checksum": meta.checksum if meta else "",
            "expected_artifact_id": meta.diagram_id if meta else "",
            "operation_id": operation_id,
            "decision_id": decision_id,
        }
        verifier = get_execution_verifier()
        evidence = verifier.verify_execution(action="render_diagram", target=path, parameters=verification_params)
        if not evidence.is_verified:
            self.adapter.metrics.verification_failed += 1
            ver_err = evidence.details.get("error", "Fallo de verificación de integridad de artefacto HTML")
            if allow_fallback:
                mermaid_code = generate_mermaid_fallback(spec, diagram_type)
                self.adapter.metrics.fallbacks += 1
                return SkillResult(
                    skill_id=self.skill_id,
                    success=True,
                    status=SkillStatus.COMPLETED,
                    output={
                        "primary_provider": "archify",
                        "fallback_provider": "mermaid",
                        "fallback_reason": ver_err,
                        "diagram_type": diagram_type,
                        "code": mermaid_code,
                        "message": f"Fallback a Mermaid activado debido a fallo en verificación: {ver_err}",
                    },
                )
            return SkillResult(
                skill_id=self.skill_id,
                success=False,
                status=SkillStatus.FAILED,
                error=f"Verificación de artefacto fallida: {ver_err}",
                output={"verification": evidence.to_dict()},
            )

        self.adapter.metrics.verified += 1
        meta = render_res.metadata
        title = spec.get("title", f"Diagrama {diagram_type}")

        return SkillResult(
            skill_id=self.skill_id,
            success=True,
            status=SkillStatus.COMPLETED,
            output={
                "message": f"He generado el diagrama interactivo de {diagram_type}: '{title}'.",
                "artifact_path": path,
                "diagram_type": diagram_type,
                "diagram_id": meta.diagram_id if meta else "",
                "checksum": meta.checksum if meta else "",
                "size_bytes": meta.size_bytes if meta else (os.path.getsize(path) if os.path.exists(path) else 0),
                "cache_status": meta.cache_status if meta else "NEW_ARTIFACT",
                "verification_status": "VERIFIED",
            },
        )

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        """Interfaz retrocompatible."""
        ctx = SkillContext(
            skill_id=self.skill_id,
            intent=str(parametros.get("action", "render")),
            parameters=parametros,
        )
        res = self.execute(ctx)
        return {
            "exito": res.status == SkillStatus.COMPLETED,
            "resultado": res.output,
            "error": res.error,
        }
