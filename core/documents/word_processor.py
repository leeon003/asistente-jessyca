"""Procesador y creador estructurado de documentos Word (.docx) (word_processor.py).

Garantiza:
1. Creación estructurada de documentos profesionales con títulos, párrafos con runs, viñetas y tablas estilizadas.
2. Edición segura conservando el original (preserve_original=True).
3. Inspección profunda de integridad (conteo de párrafos, tablas, palabras, estructura XML).
4. Verificación opcional con la aplicación real Microsoft Word vía COM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from core.logger import get_logger

logger = get_logger("jessyca.documents.word")


def _set_cell_background(cell: Any, hex_color: str) -> None:
    """Aplica color de fondo hexadecimal a una celda de tabla en python-docx."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


@dataclass
class WordSection:
    heading: str
    heading_level: int = 1
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    table_headers: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)


class WordDocumentProcessor:
    """Manejador especializado en documentos Word (.docx)."""

    @staticmethod
    def create_report(
        file_path: str | Path,
        title: str,
        subtitle: str | None = None,
        sections: list[WordSection] | None = None,
        author: str = "JESSYCA 3.0",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Crea un documento Word estructurado y profesional."""
        out_path = Path(file_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        doc = docx.Document()

        # Propiedades del documento
        core_props = doc.core_properties
        core_props.title = title
        core_props.author = author
        if subtitle:
            core_props.subject = subtitle

        # 1. Título principal
        title_p = doc.add_paragraph()
        title_p.paragraph_format.space_before = Pt(0)
        title_p.paragraph_format.space_after = Pt(6)
        title_run = title_p.add_run(title)
        title_run.font.size = Pt(24)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(30, 41, 59)  # Slate 800

        # 2. Subtítulo
        if subtitle:
            sub_p = doc.add_paragraph()
            sub_p.paragraph_format.space_before = Pt(0)
            sub_p.paragraph_format.space_after = Pt(18)
            sub_run = sub_p.add_run(subtitle)
            sub_run.font.size = Pt(13)
            sub_run.font.italic = True
            sub_run.font.color.rgb = RGBColor(100, 116, 139)  # Slate 500

        # Separador sutil
        doc.add_paragraph("—" * 40)

        # 3. Secciones
        if sections:
            for sec in sections:
                # Encabezado
                h = doc.add_heading(sec.heading, level=min(sec.heading_level, 3))
                h.paragraph_format.space_before = Pt(12)
                h.paragraph_format.space_after = Pt(6)

                # Párrafos regulares
                for p_text in sec.paragraphs:
                    p = doc.add_paragraph()
                    p.paragraph_format.space_after = Pt(6)
                    p.paragraph_format.line_spacing = 1.15
                    # Permitir marcado simple **negrita** o *cursiva*
                    WordDocumentProcessor._add_formatted_runs(p, p_text)

                # Viñetas
                for b_text in sec.bullets:
                    bp = doc.add_paragraph(style="List Bullet")
                    bp.paragraph_format.space_after = Pt(3)
                    WordDocumentProcessor._add_formatted_runs(bp, b_text)

                # Tablas estructuradas
                if sec.table_headers and sec.table_rows:
                    table = doc.add_table(rows=1, cols=len(sec.table_headers))
                    table.alignment = WD_TABLE_ALIGNMENT.CENTER
                    table.autofit = True

                    # Encabezados de tabla
                    hdr_cells = table.rows[0].cells
                    for idx, heading in enumerate(sec.table_headers):
                        cell = hdr_cells[idx]
                        cell.text = heading
                        _set_cell_background(cell, "1E293B")  # Slate 800
                        for p in cell.paragraphs:
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            for r in p.runs:
                                r.font.bold = True
                                r.font.color.rgb = RGBColor(255, 255, 255)
                                r.font.size = Pt(10)

                    # Filas de datos
                    for row_idx, row_data in enumerate(sec.table_rows):
                        row_cells = table.add_row().cells
                        bg_color = "F8FAFC" if row_idx % 2 == 1 else "FFFFFF"
                        for c_idx, val in enumerate(row_data):
                            if c_idx < len(row_cells):
                                c = row_cells[c_idx]
                                c.text = str(val)
                                _set_cell_background(c, bg_color)
                                for p in c.paragraphs:
                                    p.paragraph_format.space_after = Pt(2)
                                    for r in p.runs:
                                        r.font.size = Pt(9.5)

                    # Espacio después de tabla
                    doc.add_paragraph()

        # Guardar documento
        doc.save(str(out_path))

        # Verificación física
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"Fallo en creación de documento Word: '{out_path}' no existe o está vacío.")

        info = WordDocumentProcessor.inspect_document(out_path)
        logger.info(f"[WORD CREATED] '{out_path.name}' creado con éxito ({info['paragraphs_count']} párrafos, {info['tables_count']} tablas, {out_path.stat().st_size} bytes)")
        return {
            "success": True,
            "path": str(out_path),
            "size_bytes": out_path.stat().st_size,
            "inspection": info,
        }

    @staticmethod
    def edit_document(
        file_path: str | Path,
        additions: list[WordSection],
        preserve_original: bool = True,
        output_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Edita un documento Word conservando el contenido original."""
        src_path = Path(file_path).resolve()
        if not src_path.exists():
            raise FileNotFoundError(f"Documento origen no encontrado: '{src_path}'")

        dest_path = Path(output_path).resolve() if output_path else src_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        doc = docx.Document(str(src_path))
        orig_para_count = len(doc.paragraphs)
        orig_table_count = len(doc.tables)

        if preserve_original:
            # Separador de actualización
            p_sep = doc.add_paragraph()
            p_sep.paragraph_format.space_before = Pt(18)
            p_sep.add_run("—" * 20 + " [SECCIÓN ACTUALIZADA / ANEXO] " + "—" * 20).font.color.rgb = RGBColor(148, 163, 184)

        # Agregar nuevas secciones
        for sec in additions:
            h = doc.add_heading(sec.heading, level=min(sec.heading_level, 3))
            h.paragraph_format.space_before = Pt(12)
            for p_text in sec.paragraphs:
                p = doc.add_paragraph()
                WordDocumentProcessor._add_formatted_runs(p, p_text)
            for b_text in sec.bullets:
                bp = doc.add_paragraph(style="List Bullet")
                WordDocumentProcessor._add_formatted_runs(bp, b_text)
            if sec.table_headers and sec.table_rows:
                table = doc.add_table(rows=1, cols=len(sec.table_headers))
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                hdr = table.rows[0].cells
                for i, head in enumerate(sec.table_headers):
                    hdr[i].text = head
                    _set_cell_background(hdr[i], "334155")
                    for p in hdr[i].paragraphs:
                        for r in p.runs:
                            r.font.bold = True
                            r.font.color.rgb = RGBColor(255, 255, 255)
                for r_data in sec.table_rows:
                    rc = table.add_row().cells
                    for i, v in enumerate(r_data):
                        if i < len(rc):
                            rc[i].text = str(v)
                doc.add_paragraph()

        doc.save(str(dest_path))

        info = WordDocumentProcessor.inspect_document(dest_path)
        return {
            "success": True,
            "path": str(dest_path),
            "original_paragraphs": orig_para_count,
            "original_tables": orig_table_count,
            "new_paragraphs": info["paragraphs_count"],
            "new_tables": info["tables_count"],
            "preserved": preserve_original,
            "size_bytes": dest_path.stat().st_size,
        }

    @staticmethod
    def inspect_document(file_path: str | Path) -> dict[str, Any]:
        """Inspecciona la estructura interna de un archivo Word (.docx)."""
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Documento no encontrado: '{p}'")

        doc = docx.Document(str(p))
        text_lines = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
        full_text = "\n".join(text_lines)
        word_count = len(full_text.split())

        headings = [para.text.strip() for para in doc.paragraphs if para.style.name.startswith("Heading")]
        tables_data = []
        for t in doc.tables:
            tables_data.append({"rows": len(t.rows), "cols": len(t.columns)})

        return {
            "file_name": p.name,
            "file_size": p.stat().st_size,
            "paragraphs_count": len(doc.paragraphs),
            "non_empty_paragraphs": len(text_lines),
            "tables_count": len(doc.tables),
            "tables_info": tables_data,
            "headings_count": len(headings),
            "headings": headings,
            "words_count": word_count,
            "sample_text": full_text[:300] + ("..." if len(full_text) > 300 else ""),
        }

    @staticmethod
    def verify_with_word_app(file_path: str | Path) -> dict[str, Any]:
        """Abre y valida el documento mediante Microsoft Word real vía COM."""
        p = Path(file_path).resolve()
        word = None
        doc = None
        initialized = False
        try:
            import win32com.client  # type: ignore[import-untyped]
            import pythoncom  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            initialized = True

            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0

            doc = word.Documents.Open(str(p), ReadOnly=True)
            para_count = doc.Paragraphs.Count
            table_count = doc.Tables.Count

            return {
                "verified": True,
                "engine": "Microsoft Word (COM)",
                "paragraphs_count": para_count,
                "tables_count": table_count,
                "opened_without_error": True,
            }
        except Exception as e:
            logger.warning(f"[WORD COM VERIFICATION] No se pudo verificar con Word.Application: {e}")
            return {
                "verified": False,
                "engine": "None",
                "error": str(e),
                "opened_without_error": False,
            }
        finally:
            if doc is not None:
                try:
                    doc.Close(False)
                except Exception:
                    pass
                doc = None
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass
                word = None
            import gc
            gc.collect()
            if initialized:
                try:
                    import pythoncom  # type: ignore[import-untyped]
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    @staticmethod
    def _add_formatted_runs(p: Any, text: str) -> None:
        """Parsea texto con **negrita** o *cursiva* y agrega runs formateados."""
        import re
        tokens = re.split(r"(\*\*.*?\*\*|\*.*?\*)", text)
        for token in tokens:
            if not token:
                continue
            if token.startswith("**") and token.endswith("**") and len(token) > 4:
                r = p.add_run(token[2:-2])
                r.bold = True
            elif token.startswith("*") and token.endswith("*") and len(token) > 2:
                r = p.add_run(token[1:-1])
                r.italic = True
            else:
                p.add_run(token)
