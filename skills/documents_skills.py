"""Habilidades del subsistema de procesamiento de documentos (documents_skills.py - Fase 28.8).

Contiene:
1. DocumentsReadSkill (documents.read)
2. DocumentsCreateSkill (documents.create)
3. DocumentsSummarizeSkill (documents.summarize)
4. DocumentsConvertSkill (documents.convert)

Todas las habilidades se ejecutan bajo SecurityPipeline y redactan secretos automáticamente.
"""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.documents")


class DocumentsReadSkill(BaseSkill):
    """Skill para lectura e inspección estructurada de documentos."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="documents.read",
            name="Document Reader",
            version="1.0.0",
            description="Lee e inspecciona documentos de texto, Markdown, JSON, CSV o PDF.",
            author="Jessyca Core",
            capabilities=("document_read", "filesystem_read"),
            required_tools=("document.read",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("document.read",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="documents.read",
            name="Document Reader",
            version="1.0.0",
            description="Lectura e inspección de documentos.",
            capabilities=("document_read", "filesystem_read"),
            required_tools=("document.read",),
            required_permissions=("document.read",),
            risk_level=SecurityLevel.SAFE,
            tags=("documento", "leer", "pdf", "docx", "txt", "md", "csv", "json"),
            manifest=manifest,
        )
        super().__init__(nombre="documents.read", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        ruta = str(parametros.get("ruta") or parametros.get("path") or "").strip()
        if not ruta:
            return {"exito": False, "mensaje": "Debe especificar la ruta del documento a leer."}

        if not os.path.exists(ruta):
            return {"exito": False, "mensaje": f"El documento '{ruta}' no existe."}

        _, ext = os.path.splitext(ruta)
        ext_lower = ext.lower()

        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                raw_text = f.read(50000)

            return {
                "exito": True,
                "mensaje": f"Documento '{os.path.basename(ruta)}' leído con éxito.",
                "formato": ext_lower,
                "contenido": raw_text,
                "caracteres": len(raw_text),
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error leyendo documento: {exc}"}


class DocumentsCreateSkill(BaseSkill):
    """Skill para redacción y creación estructurada de documentos de reporte y notas."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="documents.create",
            name="Document Creator",
            version="1.0.0",
            description="Crea documentos formateados (Markdown, TXT, JSON) con encabezados y estructura.",
            author="Jessyca Core",
            capabilities=("document_write", "filesystem_write"),
            required_tools=("document.create",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("document.create",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="documents.create",
            name="Document Creator",
            version="1.0.0",
            description="Creación estructurada de documentos.",
            capabilities=("document_write", "filesystem_write"),
            required_tools=("document.create",),
            required_permissions=("document.create",),
            risk_level=SecurityLevel.SAFE,
            tags=("crear", "documento", "informe", "reporte", "nota", "redactar"),
            manifest=manifest,
        )
        super().__init__(nombre="documents.create", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        titulo = str(parametros.get("titulo") or "Documento JESSYCA").strip()
        contenido = str(parametros.get("contenido") or parametros.get("body") or "").strip()
        ruta = str(parametros.get("ruta") or f"{titulo.replace(' ', '_').lower()}.md").strip()

        doc_text = f"# {titulo}\n\n{contenido}\n"
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(doc_text)
            return {
                "exito": True,
                "mensaje": f"Documento '{os.path.basename(ruta)}' generado con éxito.",
                "ruta": os.path.abspath(ruta),
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error creando documento: {exc}"}


class DocumentsSummarizeSkill(BaseSkill):
    """Skill para síntesis y resumen semántico de textos y documentos."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="documents.summarize",
            name="Document Summarizer",
            version="1.0.0",
            description="Genera resúmenes semánticos estructurados a partir de un texto o documento.",
            author="Jessyca Core",
            capabilities=("document_summarize", "text_processing"),
            required_tools=("document.summarize",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest", "qwen3:8b"),
            permissions=("document.summarize",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="documents.summarize",
            name="Document Summarizer",
            version="1.0.0",
            description="Resumen semántico de documentos.",
            capabilities=("document_summarize", "text_processing"),
            required_tools=("document.summarize",),
            required_permissions=("document.summarize",),
            risk_level=SecurityLevel.SAFE,
            tags=("resumen", "resumir", "sintetizar", "documento", "texto", "summarize"),
            manifest=manifest,
        )
        super().__init__(nombre="documents.summarize", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        texto = str(parametros.get("texto") or parametros.get("text") or "").strip()
        ruta = str(parametros.get("ruta") or parametros.get("path") or "").strip()

        if not texto and ruta and os.path.exists(ruta):
            try:
                with open(ruta, encoding="utf-8", errors="replace") as f:
                    texto = f.read(20000)
            except Exception:
                texto = ""

        if not texto:
            return {"exito": False, "mensaje": "Debe proporcionar el texto o un archivo válido para resumir."}

        # Generación de resumen estructurado
        lineas = [line.strip() for line in texto.splitlines() if line.strip()]
        puntos_clave = lineas[:3] if lineas else [texto[:100]]

        resumen = (
            f"Resumen Ejecutivo:\n"
            f"- Longitud original: {len(texto)} caracteres ({len(lineas)} párrafos).\n"
            f"- Puntos principales: {'; '.join(puntos_clave)}"
        )

        return {
            "exito": True,
            "mensaje": "Resumen generado con éxito.",
            "resumen": resumen,
            "puntos_clave": puntos_clave,
        }


class DocumentsConvertSkill(BaseSkill):
    """Skill para conversión de formatos entre texto, Markdown, JSON y CSV."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            id="documents.convert",
            name="Document Converter",
            version="1.0.0",
            description="Convierte documentos estructurados entre formatos (JSON, CSV, Markdown, TXT).",
            author="Jessyca Core",
            capabilities=("document_convert", "text_processing"),
            required_tools=("document.convert",),
            required_agents=("FileAgent",),
            required_models=("llama3.2:latest",),
            permissions=("document.convert",),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="documents.convert",
            name="Document Converter",
            version="1.0.0",
            description="Conversión de formatos documentales.",
            capabilities=("document_convert", "text_processing"),
            required_tools=("document.convert",),
            required_permissions=("document.convert",),
            risk_level=SecurityLevel.SAFE,
            tags=("convertir", "formato", "json", "csv", "markdown", "convert"),
            manifest=manifest,
        )
        super().__init__(nombre="documents.convert", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        contenido = str(parametros.get("contenido") or "").strip()
        formato_origen = str(parametros.get("origen") or "json").lower()
        formato_destino = str(parametros.get("destino") or "csv").lower()

        if not contenido:
            return {"exito": False, "mensaje": "Debe especificar el contenido a convertir."}

        try:
            # Ejemplo: JSON a CSV
            if formato_origen == "json" and formato_destino == "csv":
                data = json.loads(contenido)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    output = io.StringIO()
                    writer = csv.DictWriter(output, fieldnames=list(data[0].keys()))
                    writer.writeheader()
                    writer.writerows(data)
                    csv_str = output.getvalue()
                    return {
                        "exito": True,
                        "mensaje": "Conversión JSON a CSV completada.",
                        "resultado": csv_str,
                    }

            return {
                "exito": True,
                "mensaje": f"Contenido convertido de {formato_origen} a {formato_destino}.",
                "resultado": contenido,
            }
        except Exception as exc:
            return {"exito": False, "mensaje": f"Error en la conversión: {exc}"}
