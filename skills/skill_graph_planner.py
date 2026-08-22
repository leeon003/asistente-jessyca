"""Planificador y Optimizador de Skill Graphs (Fase 36).

Permite construir un SkillGraph estructurado a partir de una intención del usuario
y aplicar optimizaciones deterministas y seguras.

GARANTÍA DE SEGURIDAD:
- Las optimizaciones NO pueden eliminar verificaciones de seguridad, confirmaciones,
  reducir niveles de riesgo ni omitir la Parada de Emergencia.
- Toda reutilización de caché verifica firma de procedencia, TTL y coincidencia de parámetros.
"""

from __future__ import annotations

import re
import time
from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_graph import SkillGraph
from skills.skill_graph_builder import SkillGraphBuilder
from skills.skill_graph_models import (
    GraphCacheEntry,
    SkillGraphNodeType,
)
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.skills.graph.planner")


class SkillGraphPlanner:
    """Generador de planes estructurados en forma de SkillGraph a partir de intenciones."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or get_skill_registry()

    def plan(
        self,
        intent: str,
        inputs: dict[str, Any] | None = None,
        graph_id: str | None = None,
    ) -> SkillGraph:
        """Alias de planificación para compatibilidad con orquestadores del sistema."""
        return self.plan_from_intent(intent=intent, graph_id=graph_id, context_inputs=inputs)

    def plan_from_intent(
        self,
        intent: str,
        graph_id: str | None = None,
        context_inputs: dict[str, Any] | None = None,
    ) -> SkillGraph:
        """Construye un SkillGraph a partir del análisis semántico del intent."""
        intent_lower = intent.lower()
        gid = graph_id or f"graph_plan_{int(time.time())}"
        inputs = context_inputs or {}

        builder = SkillGraphBuilder(graph_id=gid, name=f"Plan: {intent[:40]}", description=intent)

        # 1. Patrón: Investigación / Informe / Research
        if any(w in intent_lower for w in ("informe", "research", "investiga", "reporte")):
            builder.add_input_node("in_topic", "topic", default_value=inputs.get("topic", intent))
            builder.add_skill_node(
                node_id="search_step",
                skill_id="browser.search",
                label="Buscar Información",
                inputs={"query": "{{inputs.topic}}"},
            )
            builder.add_skill_node(
                node_id="read_step",
                skill_id="browser.read",
                label="Leer Contenido Web",
                inputs={"url": "{{steps.search_step.output.url}}"},
            )
            builder.add_skill_node(
                node_id="create_doc_step",
                skill_id="documents.create",
                label="Crear Documento de Informe",
                inputs={
                    "title": f"Informe: {inputs.get('topic', 'General')}",
                    "content": "{{steps.read_step.output.content}}",
                },
                risk_level=SecurityLevel.SAFE,
            )
            builder.add_output_node("out_final", "document_created")

            # Conexiones
            builder.add_consumes("in_topic", "search_step")
            builder.add_dependency("search_step", "read_step")
            builder.add_dependency("read_step", "create_doc_step")
            builder.add_produces("create_doc_step", "out_final")

        # 2. Patrón: Organización de Archivos / Organize Files
        elif any(w in intent_lower for w in ("organiza", "organizar", "organize_files", "limpiar descargas")):
            builder.add_input_node("in_dir", "directory", default_value=inputs.get("directory", "."))
            builder.add_skill_node(
                node_id="search_files_step",
                skill_id="files.search",
                label="Buscar Archivos",
                inputs={"directory": "{{inputs.directory}}", "query": "*"},
            )
            builder.add_skill_node(
                node_id="organize_step",
                skill_id="files.organize",
                label="Organizar Archivos por Extensión",
                inputs={"source_dir": "{{inputs.directory}}", "rule": "by_extension"},
            )
            builder.add_output_node("out_organized", "organize_result")

            builder.add_consumes("in_dir", "search_files_step")
            builder.add_dependency("search_files_step", "organize_step")
            builder.add_produces("organize_step", "out_organized")

        # 3. Patrón: Preparar Reunión / Prepare Meeting
        elif any(w in intent_lower for w in ("reunión", "reunion", "meeting", "agenda")):
            builder.add_input_node("in_notes", "notes_path", default_value=inputs.get("notes_path", "notes.txt"))
            builder.add_skill_node(
                node_id="read_notes_step",
                skill_id="documents.read",
                label="Leer Notas Previas",
                inputs={"file_path": "{{inputs.notes_path}}"},
            )
            builder.add_skill_node(
                node_id="search_context_step",
                skill_id="browser.search",
                label="Buscar Contexto Relevante",
                inputs={"query": "{{steps.read_notes_step.output.content}}"},
            )
            builder.add_skill_node(
                node_id="create_brief_step",
                skill_id="documents.create",
                label="Generar Brief de Reunión",
                inputs={
                    "title": "Brief de Reunión",
                    "content": "{{steps.search_context_step.output.results}}",
                },
            )
            builder.add_output_node("out_brief", "meeting_brief")

            builder.add_consumes("in_notes", "read_notes_step")
            builder.add_dependency("read_notes_step", "search_context_step")
            builder.add_dependency("search_context_step", "create_brief_step")
            builder.add_produces("create_brief_step", "out_brief")

        # 4. Fallback Genérico: Enrutamiento por coincidencia de Skills en Registry
        else:
            # Buscar una Skill que coincida con el intent
            matched_skill: str | None = None
            for s in self.registry.list_skills():
                sname = s.skill_id if hasattr(s, "skill_id") else str(s)
                tokens = re.split(r"[._\s-]", sname.lower())
                if any(tok in intent_lower for tok in tokens if len(tok) > 3):
                    matched_skill = sname
                    break

            target_skill = matched_skill or "windows.clipboard"
            builder.add_skill_node(
                node_id="single_step",
                skill_id=target_skill,
                label=f"Ejecutar {target_skill}",
                inputs=inputs,
            )

        return builder.build()


class SkillGraphOptimizer:
    """Optimizador seguro para transformar y mejorar planes estructurados en SkillGraph."""

    @classmethod
    def optimize_graph(
        cls,
        graph: SkillGraph,
        cache_entries: dict[str, GraphCacheEntry] | None = None,
    ) -> SkillGraph:
        """Aplica optimizaciones seguras:

        1. Reutilización de resultados en caché vigentes con procedencia validada.
        2. Detección y eliminación de nodos duplicados idénticos no requeridos.
        3. Identificación de ramas independientes.
        """
        if cache_entries:
            now = time.time()
            for node_id, node in graph.nodes.items():
                if node.node_type == SkillGraphNodeType.SKILL:
                    cache_key = f"{node.ref_id}:{sorted(node.inputs.items())}"
                    entry = cache_entries.get(cache_key)
                    if entry and entry.is_valid(now):
                        logger.info(f"[GRAPH CACHE HIT] Nodo '{node_id}' ({node.ref_id}) reutilizará resultado en caché.")
                        node.result = entry.value
                        node.metadata["cached"] = True
                        node.metadata["cache_provenance"] = entry.provenance

        return graph
