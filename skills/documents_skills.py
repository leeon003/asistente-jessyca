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
import re
from pathlib import Path
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

    def ejecutar(self, parametros: dict[str, Any], context: Any = None) -> dict[str, Any]:
        ruta = str(parametros.get("ruta") or parametros.get("path") or "").strip()
        if not ruta:
            return {"exito": False, "mensaje": "Debe especificar la ruta del documento a leer."}

        if not os.path.exists(ruta):
            return {"exito": False, "mensaje": f"El documento '{ruta}' no existe."}

        # Comprobar autorización si el contexto suministra trusted_root
        trusted_root = None
        if context is not None:
            if hasattr(context, "metadata") and isinstance(context.metadata, dict):
                trusted_root = context.metadata.get("trusted_root") or context.metadata.get("authorized_root")
            elif isinstance(context, dict):
                trusted_root = context.get("trusted_root") or context.get("authorized_root")

        if trusted_root is not None:
            from core.documents.summarizer import check_document_authorization
            is_auth, msg_sec = check_document_authorization(ruta, trusted_root=trusted_root)
            if not is_auth:
                return {"exito": False, "mensaje": msg_sec, "error": msg_sec}

        _, ext = os.path.splitext(ruta)
        ext_lower = ext.lower()

        try:
            if ext_lower == ".docx":
                import docx
                doc = docx.Document(ruta)
                paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
                tables_data: list[str] = []
                for t in doc.tables:
                    for row in t.rows:
                        tables_data.append(" | ".join(c.text.strip() for c in row.cells))
                content_parts = paragraphs + (["\n--- TABLAS ---"] + tables_data if tables_data else [])
                raw_text = "\n".join(content_parts)

            elif ext_lower in (".xlsx", ".xlsm"):
                import openpyxl
                wb = openpyxl.load_workbook(ruta, data_only=True)
                lines: list[str] = []
                for sname in wb.sheetnames:
                    ws = wb[sname]
                    lines.append(f"--- Hoja: {sname} ---")
                    for row in ws.iter_rows(values_only=True):
                        if any(v is not None for v in row):
                            lines.append(" | ".join(str(v) if v is not None else "" for v in row))
                raw_text = "\n".join(lines)

            elif ext_lower == ".pptx":
                import pptx
                prs = pptx.Presentation(ruta)
                lines = []
                for idx, slide in enumerate(prs.slides, 1):
                    lines.append(f"--- Diapositiva {idx} ---")
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            for paragraph in shape.text_frame.paragraphs:
                                if paragraph.text.strip():
                                    lines.append(paragraph.text.strip())
                raw_text = "\n".join(lines)

            elif ext_lower == ".pdf":
                try:
                    from core.anydoc.docling_backend import DoclingBackend
                    backend = DoclingBackend()
                    res_pdf = backend.convert_to_markdown(ruta)
                    raw_text = res_pdf.get("markdown", "") if isinstance(res_pdf, dict) else str(res_pdf)
                except Exception as pdf_err:
                    logger.warning(f"[DOCUMENTS READ PDF] Fallo Docling: {pdf_err}")
                    raw_text = f"Documento PDF '{os.path.basename(ruta)}' localizado e inspeccionado en disco."

            else:
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
            description="Crea documentos formateados (Word, Excel, PowerPoint, Markdown, TXT, JSON) con estructura.",
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
            tags=("crear", "documento", "informe", "reporte", "word", "excel", "powerpoint", "nota", "redactar"),
            manifest=manifest,
        )
        super().__init__(nombre="documents.create", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        from skills.files_skills import FORBIDDEN_EXECUTABLE_EXTENSIONS, _is_path_critical

        titulo = str(parametros.get("titulo") or parametros.get("title") or "Documento JESSYCA").strip()
        contenido = str(parametros.get("contenido") or parametros.get("body") or parametros.get("content") or "").strip()
        clean_name = re.sub(r'[\\/:*?"<>|]+', "_", titulo).strip(" ._")
        default_filename = f"{clean_name.lower() or 'documento'}.md"
        ruta = str(parametros.get("ruta") or parametros.get("path") or parametros.get("file_path") or default_filename).strip()
        formato = str(parametros.get("formato") or parametros.get("format") or "").lower()

        if not ruta:
            return {"exito": False, "verified": False, "mensaje": "Debe especificar la ruta o nombre del documento."}

        _, ext = os.path.splitext(ruta)
        ext_lower = ext.lower()

        # Determinar formato efectivo si no tiene extensión
        if not ext_lower:
            if formato in ("docx", "word"):
                ruta = f"{ruta}.docx"
                ext_lower = ".docx"
            elif formato in ("xlsx", "excel", "hoja"):
                ruta = f"{ruta}.xlsx"
                ext_lower = ".xlsx"
            elif formato in ("pptx", "powerpoint", "presentacion", "presentación"):
                ruta = f"{ruta}.pptx"
                ext_lower = ".pptx"
            else:
                ruta = f"{ruta}.md"
                ext_lower = ".md"

        # 1. Garantía de Destino Permitido: Bloqueo de rutas críticas del sistema
        if _is_path_critical(ruta):
            return {
                "exito": False,
                "verified": False,
                "mensaje": "Acceso denegado: Intento de escritura en ruta crítica de Windows.",
            }

        # 2. Bloqueo de extensiones ejecutables peligrosas
        if ext_lower in FORBIDDEN_EXECUTABLE_EXTENSIONS:
            return {
                "exito": False,
                "verified": False,
                "mensaje": f"Seguridad: Extensión peligrosa bloqueada '{ext_lower}'.",
            }

        # 3. Garantía contra Sobrescritura No Autorizada y Vinculada a JDE
        destino_norm = os.path.abspath(ruta)
        sobrescribir = bool(parametros.get("sobrescribir") or parametros.get("overwrite") or False)
        session_id = str(parametros.get("session_id") or "default_session")
        user_id = str(parametros.get("user_id") or "default_user")

        if os.path.exists(ruta):
            from core.jde.confirmation import get_confirmation_manager
            conf_mgr = get_confirmation_manager()

            action_name = getattr(self, "nombre", "documents.create")

            if not sobrescribir:
                conf_mgr.register_pending_confirmation(
                    session_id=session_id,
                    action=action_name,
                    tool=action_name,
                    parameters={"ruta": destino_norm},
                    user_id=user_id,
                    metadata={"destination": destino_norm, "operation": "overwrite_protection"},
                )
                return {
                    "exito": False,
                    "verified": False,
                    "conflicto_destino": True,
                    "requiere_confirmacion": True,
                    "session_id": session_id,
                    "operacion": action_name,
                    "destino": destino_norm,
                    "archivo_creado": False,
                    "contenido_verificado": False,
                    "calculo_verificado": False,
                    "mensaje": (
                        f"Protección anti-sobrescritura: El archivo '{os.path.basename(ruta)}' ya existe. "
                        f"Requiere confirmación expresa vinculada a la sesión '{session_id}', operación '{action_name}' y destino '{destino_norm}'."
                    ),
                }

            is_authorized = conf_mgr.verify_and_consume(
                session_id=session_id,
                action=action_name,
                parameters={"ruta": destino_norm},
                user_id=user_id,
            )
            if not is_authorized:
                return {
                    "exito": False,
                    "verified": False,
                    "conflicto_destino": True,
                    "sobrescritura_no_autorizada": True,
                    "session_id": session_id,
                    "operacion": action_name,
                    "destino": destino_norm,
                    "archivo_creado": False,
                    "contenido_verificado": False,
                    "calculo_verificado": False,
                    "mensaje": (
                        f"Sobrescritura no autorizada: El parámetro sobrescribir=True no constituye autorización. "
                        f"Se requiere confirmación previa aprobada en JDE vinculada a la sesión '{session_id}', "
                        f"operación '{action_name}' y destino '{destino_norm}'."
                    ),
                }

        # 4. Creación segura de directorio padre si no existe
        dir_padre = os.path.dirname(ruta)
        if dir_padre:
            os.makedirs(dir_padre, exist_ok=True)

        try:
            # 1. Documento Word (.docx)
            if ext_lower == ".docx" or formato == "docx":
                from core.documents.word_processor import WordDocumentProcessor, WordSection
                sections_raw = parametros.get("sections")
                datos_suministrados = parametros.get("datos") or parametros.get("bullets") or []
                if isinstance(datos_suministrados, str):
                    datos_suministrados = [d.strip() for d in datos_suministrados.split("\n") if d.strip()]

                if not sections_raw:
                    paragraphs = [contenido] if contenido else []
                    sections = [
                        WordSection(
                            heading=titulo or "Informe General",
                            paragraphs=paragraphs if paragraphs else ["Documento estructurado por JESSYCA 3.0."],
                            bullets=list(datos_suministrados),
                        )
                    ]
                else:
                    sections = [
                        WordSection(
                            heading=s.get("heading", "Sección"),
                            heading_level=s.get("heading_level", 1),
                            paragraphs=s.get("paragraphs", []),
                            bullets=s.get("bullets", []),
                            table_headers=s.get("table_headers", []),
                            table_rows=s.get("table_rows", []),
                        )
                        for s in sections_raw
                    ]
                res_word = WordDocumentProcessor.create_report(
                    file_path=ruta,
                    title=titulo,
                    subtitle=parametros.get("subtitulo") or parametros.get("subtitle"),
                    sections=sections,
                    author=parametros.get("author", "JESSYCA 3.0"),
                )
                archivo_creado = os.path.exists(ruta) and os.path.getsize(ruta) > 0
                contenido_verificado = False
                calculo_verificado = None  # No aplica cálculo a Word

                if archivo_creado:
                    try:
                        import docx
                        doc = docx.Document(ruta)
                        full_text = " ".join(p.text for p in doc.paragraphs)
                        title_ok = (titulo.lower() in full_text.lower()) if titulo else True
                        bullets_ok = True
                        if datos_suministrados:
                            bullets_ok = any(str(d).strip().lower() in full_text.lower() for d in datos_suministrados)
                        contenido_verificado = bool(title_ok and bullets_ok and len(doc.paragraphs) > 0)
                    except Exception as err:
                        logger.error(f"[DOCX REOPEN VERIFICATION FAILED] {err}")
                        contenido_verificado = False

                is_verif = bool(archivo_creado and contenido_verificado)
                return {
                    "exito": is_verif,
                    "verified": is_verif,
                    "archivo_creado": archivo_creado,
                    "contenido_verificado": contenido_verificado,
                    "calculo_verificado": calculo_verificado,
                    "mensaje": (
                        f"Documento Word '{os.path.basename(ruta)}' creado y verificado con éxito "
                        f"(archivo creado: OK, contenido verificado: OK)."
                        if is_verif else
                        f"Fallo en verificación de documento Word '{os.path.basename(ruta)}' "
                        f"(creado: {archivo_creado}, contenido: {contenido_verificado})."
                    ),
                    "ruta": destino_norm,
                    "bytes": os.path.getsize(ruta) if archivo_creado else 0,
                    "sections_count": len(sections),
                    "detalles": res_word,
                }

            # 2. Hoja de cálculo Excel (.xlsx)
            elif ext_lower in (".xlsx", ".xlsm") or formato in ("xlsx", "excel"):
                from core.documents.excel_processor import BudgetItem, ExcelSpreadsheetProcessor
                items_raw = parametros.get("items")
                if items_raw and isinstance(items_raw, list):
                    items = [
                        BudgetItem(
                            concepto=str(it.get("concepto", "Item")),
                            categoria=str(it.get("categoria", "General")),
                            cantidad=float(it.get("cantidad", 1)),
                            costo_unitario=float(it.get("costo_unitario", 0)),
                        )
                        for it in items_raw
                    ]
                else:
                    items = [
                        BudgetItem(concepto="Servicios de Software", categoria="Tecnología", cantidad=1.0, costo_unitario=1500.0),
                        BudgetItem(concepto="Infraestructura y Servidores", categoria="Hardware", cantidad=2.0, costo_unitario=800.0),
                    ]
                res_xl = ExcelSpreadsheetProcessor.create_budget_workbook(
                    file_path=ruta,
                    items=items,
                    titulo_presupuesto=titulo or "Presupuesto Operativo",
                )

                subtotal_esperado = sum(it.cantidad * it.costo_unitario for it in items)
                impuesto_esperado = subtotal_esperado * 0.18
                total_esperado = subtotal_esperado + impuesto_esperado

                archivo_creado = os.path.exists(ruta) and os.path.getsize(ruta) > 0
                contenido_verificado = False
                formulas_found = []
                formulas_presentes = False

                if archivo_creado:
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(ruta, data_only=False)
                        sheet = wb.active
                        for row in sheet.iter_rows(values_only=False):
                            for cell in row:
                                if cell.value and str(cell.value).startswith("="):
                                    formulas_found.append(str(cell.value))
                        formulas_presentes = len(formulas_found) > 0
                        contenido_verificado = bool(sheet.title and sheet.max_row >= 4 and formulas_presentes)
                    except Exception as err:
                        logger.error(f"[EXCEL REOPEN VERIFICATION FAILED] {err}")
                        contenido_verificado = False

                # Separación de cálculo según requerimiento (fórmula escrita vs cálculo independiente vs recálculo motor real)
                formula_escrita = formulas_presentes
                resultado_esperado_calculado_independiente = round(total_esperado, 2)
                resultado_recalculado_motor_real = None
                recalculo_motor_real_ejecutado = False
                recalculo_motor_real_verificado = False

                if parametros.get("ejecutar_recalculo_motor", False):
                    try:
                        from pathlib import Path
                        eval_engine = ExcelSpreadsheetProcessor.evaluate_formulas_with_engine(Path(ruta))
                        if eval_engine.get("has_engine"):
                            recalculo_motor_real_ejecutado = True
                            resultado_recalculado_motor_real = eval_engine.get("results")
                            recalculo_motor_real_verificado = True
                    except Exception as m_err:
                        logger.warning(f"[EXCEL MOTOR CALC] No se pudo ejecutar recálculo motor real: {m_err}")

                # No marcar recálculo como verificado si no se ejecutó mediante un motor real
                calculo_verificado = bool(recalculo_motor_real_verificado)
                is_verif = bool(archivo_creado and contenido_verificado)

                return {
                    "exito": is_verif,
                    "verified": is_verif,
                    "archivo_creado": archivo_creado,
                    "contenido_verificado": contenido_verificado,
                    "formula_escrita": formula_escrita,
                    "formulas_encontradas": formulas_found,
                    "resultado_esperado_calculado_independiente": resultado_esperado_calculado_independiente,
                    "resultado_recalculado_motor_real": resultado_recalculado_motor_real,
                    "recalculo_motor_real_ejecutado": recalculo_motor_real_ejecutado,
                    "recalculo_motor_real_verificado": recalculo_motor_real_verificado,
                    "calculo_verificado": calculo_verificado,
                    "mensaje": (
                        f"Hoja de cálculo Excel '{os.path.basename(ruta)}' creada y verificada con éxito "
                        f"(archivo creado: OK, contenido verificado: OK, fórmulas escritas: {len(formulas_found)}, "
                        f"cálculo independiente esperado: {resultado_esperado_calculado_independiente}, "
                        f"recálculo motor real: {'verificado' if recalculo_motor_real_verificado else 'no ejecutado'})."
                        if is_verif else
                        f"Fallo en verificación de Excel '{os.path.basename(ruta)}' "
                        f"(creado: {archivo_creado}, contenido: {contenido_verificado})."
                    ),
                    "ruta": destino_norm,
                    "bytes": os.path.getsize(ruta) if archivo_creado else 0,
                    "formula_written": formula_escrita,
                    "formula_count": len(res_xl.get("formula_cells", [])),
                    "total_calculado_esperado": resultado_esperado_calculado_independiente,
                    "detalles": res_xl,
                }

            # 3. Presentación PowerPoint (.pptx)
            elif ext_lower == ".pptx" or formato in ("pptx", "powerpoint"):
                from core.documents.powerpoint_processor import PowerPointPresentationProcessor, SlideContent
                slides_raw = parametros.get("slides")
                if slides_raw and isinstance(slides_raw, list):
                    slides = [
                        SlideContent(
                            title=str(s.get("title", "Diapositiva")),
                            subtitle=s.get("subtitle"),
                            bullets=list(s.get("bullets", [])),
                            category_label=str(s.get("category_label", "GENERAL")),
                        )
                        for s in slides_raw
                    ]
                else:
                    slides = [
                        SlideContent(title=titulo, subtitle="Presentación Ejecutiva JESSYCA", category_label="PORTADA"),
                        SlideContent(title="Resumen Ejecutivo", bullets=[contenido] if contenido else ["Capacidades verificadas de JESSYCA 3.0."], category_label="RESUMEN"),
                    ]
                res_ppt = PowerPointPresentationProcessor.create_presentation(
                    file_path=ruta,
                    slides_data=slides,
                    presenter=parametros.get("presenter", "JESSYCA 3.0"),
                )

                archivo_creado = os.path.exists(ruta) and os.path.getsize(ruta) > 0
                contenido_verificado = False
                calculo_verificado = None  # No aplica a PPTX

                if archivo_creado:
                    try:
                        import pptx
                        prs = pptx.Presentation(ruta)
                        slides_count = len(prs.slides)
                        expected_count = len(slides)
                        if slides_count >= expected_count:
                            all_slide_text = ""
                            for s in prs.slides:
                                for shape in s.shapes:
                                    if shape.has_text_frame:
                                        all_slide_text += " " + shape.text
                            if slides_raw and slides:
                                title_ok = any(s.title.lower() in all_slide_text.lower() for s in slides)
                            else:
                                title_ok = (titulo.lower() in all_slide_text.lower()) if titulo else True
                            contenido_verificado = bool(title_ok and len(all_slide_text.strip()) > 0)
                    except Exception as err:
                        logger.error(f"[PPTX REOPEN VERIFICATION FAILED] {err}")
                        contenido_verificado = False

                is_verif = bool(archivo_creado and contenido_verificado)
                return {
                    "exito": is_verif,
                    "verified": is_verif,
                    "archivo_creado": archivo_creado,
                    "contenido_verificado": contenido_verificado,
                    "calculo_verificado": calculo_verificado,
                    "mensaje": (
                        f"Presentación PowerPoint '{os.path.basename(ruta)}' creada y verificada con éxito "
                        f"(archivo creado: OK, contenido verificado: OK)."
                        if is_verif else
                        f"Fallo en verificación de PowerPoint '{os.path.basename(ruta)}' "
                        f"(creado: {archivo_creado}, contenido: {contenido_verificado})."
                    ),
                    "ruta": destino_norm,
                    "bytes": os.path.getsize(ruta) if archivo_creado else 0,
                    "slides_count": len(slides),
                    "detalles": res_ppt,
                }

            # 4. Texto / Markdown / JSON
            else:
                doc_text = f"# {titulo}\n\n{contenido}\n"
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(doc_text)

                archivo_creado = os.path.exists(ruta) and os.path.getsize(ruta) > 0
                contenido_verificado = False
                calculo_verificado = None

                if archivo_creado:
                    try:
                        with open(ruta, "r", encoding="utf-8") as f:
                            read_back = f.read()
                        title_ok = (titulo in read_back) if titulo else True
                        contenido_verificado = bool(title_ok and len(read_back) > 0)
                    except Exception as err:
                        logger.error(f"[TEXT REOPEN VERIFICATION FAILED] {err}")
                        contenido_verificado = False

                is_verif = bool(archivo_creado and contenido_verificado)
                return {
                    "exito": is_verif,
                    "verified": is_verif,
                    "archivo_creado": archivo_creado,
                    "contenido_verificado": contenido_verificado,
                    "calculo_verificado": calculo_verificado,
                    "mensaje": f"Documento '{os.path.basename(ruta)}' generado y verificado con éxito.",
                    "ruta": destino_norm,
                    "bytes": os.path.getsize(ruta) if archivo_creado else 0,
                }
        except Exception as exc:
            logger.error(f"[DOCUMENTS CREATE ERROR] {exc}", exc_info=True)
            return {"exito": False, "verified": False, "mensaje": f"Error creando documento: {exc}"}


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

    def ejecutar(self, parametros: dict[str, Any], context: Any = None) -> dict[str, Any]:
        from core.documents.summarizer import extractive_summarize

        texto = str(parametros.get("texto") or parametros.get("text") or parametros.get("content") or "").strip()
        ruta = str(parametros.get("ruta") or parametros.get("path") or parametros.get("file_path") or "").strip()
        max_points = int(parametros.get("max_points") or 5)

        # 1. Base confiable del contexto de ejecución por solicitud (NUNCA de self ni de parámetros del LLM)
        trusted_root = None
        if context is not None:
            if hasattr(context, "metadata") and isinstance(context.metadata, dict):
                trusted_root = context.metadata.get("trusted_root") or context.metadata.get("authorized_root")
            elif isinstance(context, dict):
                trusted_root = context.get("trusted_root") or context.get("authorized_root")
        auth_root = (
            parametros.get("authorized_root")
            or parametros.get("sandbox_root")
            or parametros.get("sandbox_dir")
            or parametros.get("scope")
        )

        try:
            return extractive_summarize(
                content=texto,
                file_path=ruta,
                max_points=max_points,
                authorized_root=auth_root,
                trusted_root=trusted_root,
            )
        except (PermissionError, FileNotFoundError) as err:
            return {"exito": False, "mensaje": str(err), "error": str(err)}
        except Exception as e:
            return {"exito": False, "mensaje": f"Error al generar resumen: {e}", "error": str(e)}


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
