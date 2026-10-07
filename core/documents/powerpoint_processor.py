"""Procesador y creador estructurado de presentaciones PowerPoint (.pptx) (powerpoint_processor.py).

Garantiza:
1. Creación estructurada de presentaciones de 16:9 con diseño legible, tipografía jerárquica y paleta moderna.
2. Inserción de títulos, subtítulos, bloques de viñetas, tablas estructuradas e imágenes.
3. Inspección detallada de diapositivas, formas y elementos visuales.
4. Verificación y renderizado opcional mediante Microsoft PowerPoint real vía COM.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pptx
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from core.logger import get_logger

logger = get_logger("jessyca.documents.powerpoint")


@dataclass
class SlideContent:
    title: str
    subtitle: str | None = None
    bullets: list[str] = field(default_factory=list)
    table_headers: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    image_path: str | Path | None = None
    category_label: str = "INFORME EJECUTIVO"


class PowerPointPresentationProcessor:
    """Manejador especializado en presentaciones PowerPoint (.pptx)."""

    # Paleta Corporativa Moderna
    COLOR_BG_DARK = RGBColor(15, 23, 42)        # Slate 900
    COLOR_CARD_DARK = RGBColor(30, 41, 59)      # Slate 800
    COLOR_TEXT_LIGHT = RGBColor(248, 250, 252)  # Slate 50
    COLOR_TEXT_MUTED = RGBColor(148, 163, 184)  # Slate 400
    COLOR_ACCENT = RGBColor(56, 189, 248)       # Sky 400
    COLOR_ACCENT_ALT = RGBColor(99, 102, 241)   # Indigo 500

    @classmethod
    def create_presentation(
        cls,
        file_path: str | Path,
        slides_data: list[SlideContent],
        presenter: str = "JESSYCA 3.0",
    ) -> dict[str, Any]:
        """Crea una presentación PowerPoint moderna con relación de aspecto 16:9 y 5 diapositivas."""
        out_path = Path(file_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        normalized_slides: list[SlideContent] = []
        for s in slides_data:
            if isinstance(s, SlideContent):
                normalized_slides.append(s)
            elif isinstance(s, dict):
                normalized_slides.append(
                    SlideContent(
                        title=str(s.get("title", "Diapositiva")),
                        subtitle=s.get("subtitle"),
                        bullets=list(s.get("bullets", [])),
                        table_headers=list(s.get("table_headers", [])),
                        table_rows=list(s.get("table_rows", [])),
                        image_path=s.get("image_path"),
                        category_label=str(s.get("category_label", "INFORME EJECUTIVO")),
                    )
                )

        prs = pptx.Presentation()
        # Formato panorámico 16:9
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        blank_slide_layout = prs.slide_layouts[6]  # Diapositiva en blanco para control total

        for slide_idx, sdata in enumerate(normalized_slides, start=1):
            slide = prs.slides.add_slide(blank_slide_layout)

            # 1. Fondo estilizado completo (Shape de fondo)
            bg_shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), prs.slide_width, prs.slide_height
            )
            bg_shape.fill.solid()
            bg_shape.fill.fore_color.rgb = cls.COLOR_BG_DARK
            bg_shape.line.fill.background()

            # Franja de acento superior
            accent_bar = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), prs.slide_width, Inches(0.12)
            )
            accent_bar.fill.solid()
            accent_bar.fill.fore_color.rgb = cls.COLOR_ACCENT
            accent_bar.line.fill.background()

            # 2. DIAPOSITIVA 1: Portada
            if slide_idx == 1:
                cls._render_cover_slide(slide, sdata, presenter, prs.slide_width, prs.slide_height)
                continue

            # 3. Encabezado de Diapositiva Estándar (Diapositivas 2 a 5)
            # Etiqueta de Categoría
            cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(8), Inches(0.35))
            cat_tf = cat_box.text_frame
            cat_tf.word_wrap = True
            cat_p = cat_tf.paragraphs[0]
            cat_p.text = f"{sdata.category_label.upper()} — SLIDE {slide_idx}/{len(slides_data)}"
            cat_p.font.size = Pt(10)
            cat_p.font.bold = True
            cat_p.font.color.rgb = cls.COLOR_ACCENT

            # Título principal de diapositiva
            title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.75), Inches(11.5), Inches(0.8))
            title_tf = title_box.text_frame
            title_tf.word_wrap = True
            title_p = title_tf.paragraphs[0]
            title_p.text = sdata.title
            title_p.font.size = Pt(24)
            title_p.font.bold = True
            title_p.font.color.rgb = cls.COLOR_TEXT_LIGHT

            # Subtítulo si existe
            if sdata.subtitle:
                sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.45), Inches(11.5), Inches(0.45))
                sub_tf = sub_box.text_frame
                sub_tf.word_wrap = True
                sub_p = sub_tf.paragraphs[0]
                sub_p.text = sdata.subtitle
                sub_p.font.size = Pt(13)
                sub_p.font.italic = True
                sub_p.font.color.rgb = cls.COLOR_TEXT_MUTED

            # 4. Contenido Central según elementos presentes
            content_top = Inches(2.0)

            # Caso A: Diapositiva con Tabla
            if sdata.table_headers and sdata.table_rows:
                cls._render_table(slide, sdata, top=content_top)

            # Caso B: Diapositiva con Imagen + Viñetas (Layout Dividido)
            elif sdata.image_path and os.path.exists(str(sdata.image_path)):
                cls._render_image_and_bullets(slide, sdata, top=content_top)

            # Caso C: Diapositiva con Viñetas o Tarjetas de Texto
            elif sdata.bullets:
                cls._render_bullet_cards(slide, sdata, top=content_top)

        # Guardar presentación
        prs.save(str(out_path))

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"Fallo en creación de presentación PowerPoint: '{out_path}' no existe o está vacía.")

        inspection = cls.inspect_presentation(out_path)
        logger.info(f"[PPTX CREATED] Presentación '{out_path.name}' generada ({inspection['slides_count']} diapositivas, {out_path.stat().st_size} bytes)")
        return {
            "success": True,
            "path": str(out_path),
            "size_bytes": out_path.stat().st_size,
            "inspection": inspection,
        }

    @classmethod
    def _render_cover_slide(
        cls,
        slide: Any,
        data: SlideContent,
        presenter: str,
        width: Inches,
        height: Inches,
    ) -> None:
        """Renderiza una diapositiva de portada impactante y moderna."""
        # Tarjeta central
        card = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.2), Inches(1.2), Inches(10.9), Inches(5.1)
        )
        card.fill.solid()
        card.fill.fore_color.rgb = cls.COLOR_CARD_DARK
        card.line.color.rgb = cls.COLOR_ACCENT
        card.line.width = Pt(1.5)

        # Categoría
        box_cat = slide.shapes.add_textbox(Inches(1.8), Inches(1.8), Inches(9.5), Inches(0.4))
        p_cat = box_cat.text_frame.paragraphs[0]
        p_cat.text = data.category_label.upper()
        p_cat.font.size = Pt(12)
        p_cat.font.bold = True
        p_cat.font.color.rgb = cls.COLOR_ACCENT

        # Título
        box_t = slide.shapes.add_textbox(Inches(1.8), Inches(2.3), Inches(9.5), Inches(1.6))
        box_t.text_frame.word_wrap = True
        p_t = box_t.text_frame.paragraphs[0]
        p_t.text = data.title
        p_t.font.size = Pt(32)
        p_t.font.bold = True
        p_t.font.color.rgb = cls.COLOR_TEXT_LIGHT

        # Subtítulo
        if data.subtitle:
            box_sub = slide.shapes.add_textbox(Inches(1.8), Inches(4.0), Inches(9.5), Inches(0.9))
            box_sub.text_frame.word_wrap = True
            p_sub = box_sub.text_frame.paragraphs[0]
            p_sub.text = data.subtitle
            p_sub.font.size = Pt(16)
            p_sub.font.color.rgb = cls.COLOR_TEXT_MUTED

        # Pie con autor y fecha
        box_footer = slide.shapes.add_textbox(Inches(1.8), Inches(5.3), Inches(9.5), Inches(0.5))
        p_foot = box_footer.text_frame.paragraphs[0]
        p_foot.text = f"Elaborado por: {presenter}  |  Sistema Operativo: Windows 11  |  Confidencial"
        p_foot.font.size = Pt(10.5)
        p_foot.font.italic = True
        p_foot.font.color.rgb = cls.COLOR_TEXT_MUTED

    @classmethod
    def _render_bullet_cards(cls, slide: Any, data: SlideContent, top: Inches) -> None:
        """Renderiza viñetas organizadas en tarjetas legibles."""
        card_w = Inches(11.7)
        card_h = Inches(4.7)

        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), top, card_w, card_h)
        card.fill.solid()
        card.fill.fore_color.rgb = cls.COLOR_CARD_DARK
        card.line.color.rgb = cls.COLOR_CARD_DARK

        tb = slide.shapes.add_textbox(Inches(1.2), top + Inches(0.3), Inches(11.0), card_h - Inches(0.6))
        tf = tb.text_frame
        tf.word_wrap = True

        for i, bullet_text in enumerate(data.bullets):
            p = tf.add_paragraph() if i > 0 else tf.paragraphs[0]
            p.text = f"•  {bullet_text}"
            p.font.size = Pt(15)
            p.font.color.rgb = cls.COLOR_TEXT_LIGHT
            p.space_after = Pt(14)
            p.line_spacing = 1.2

    @classmethod
    def _render_table(cls, slide: Any, data: SlideContent, top: Inches) -> None:
        """Renderiza una tabla estructurada de datos en la diapositiva."""
        rows_cnt = len(data.table_rows) + 1
        cols_cnt = len(data.table_headers)
        tbl_shape = slide.shapes.add_table(rows_cnt, cols_cnt, Inches(0.8), top, Inches(11.7), Inches(4.6))
        tbl = tbl_shape.table

        # Encabezados
        for col_i, header_text in enumerate(data.table_headers):
            cell = tbl.cell(0, col_i)
            cell.text = header_text
            cell.fill.solid()
            cell.fill.fore_color.rgb = cls.COLOR_CARD_DARK
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            p.font.bold = True
            p.font.size = Pt(12)
            p.font.color.rgb = cls.COLOR_ACCENT

        # Filas
        for row_i, r_data in enumerate(data.table_rows, start=1):
            bg = cls.COLOR_CARD_DARK if row_i % 2 == 0 else RGBColor(24, 34, 52)
            for col_i, val in enumerate(r_data):
                if col_i < cols_cnt:
                    cell = tbl.cell(row_i, col_i)
                    cell.text = str(val)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = bg
                    p = cell.text_frame.paragraphs[0]
                    p.font.size = Pt(11)
                    p.font.color.rgb = cls.COLOR_TEXT_LIGHT
                    if col_i >= 2 and any(ch in str(val) for ch in ("$", "%", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")):
                        p.alignment = PP_ALIGN.RIGHT

    @classmethod
    def _render_image_and_bullets(cls, slide: Any, data: SlideContent, top: Inches) -> None:
        """Renderiza layout dividido: gráfico a la izquierda, explicaciones a la derecha."""
        img_path = str(data.image_path)
        img_w = Inches(5.8)
        img_h = Inches(4.7)

        # Imagen
        slide.shapes.add_picture(img_path, Inches(0.8), top, width=img_w, height=img_h)

        # Tarjeta derecha para viñetas explicativas
        box_right = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.9), top, Inches(5.6), img_h)
        box_right.fill.solid()
        box_right.fill.fore_color.rgb = cls.COLOR_CARD_DARK
        box_right.line.color.rgb = cls.COLOR_CARD_DARK

        tb = slide.shapes.add_textbox(Inches(7.1), top + Inches(0.3), Inches(5.2), img_h - Inches(0.6))
        tf = tb.text_frame
        tf.word_wrap = True

        for i, b in enumerate(data.bullets):
            p = tf.add_paragraph() if i > 0 else tf.paragraphs[0]
            p.text = f"•  {b}"
            p.font.size = Pt(13.5)
            p.font.color.rgb = cls.COLOR_TEXT_LIGHT
            p.space_after = Pt(12)

    @staticmethod
    def inspect_presentation(file_path: str | Path) -> dict[str, Any]:
        """Inspecciona y analiza el contenido de una presentación PowerPoint (.pptx)."""
        p = Path(file_path).resolve()
        prs = pptx.Presentation(str(p))

        slides_summary = []
        total_shapes = 0
        total_tables = 0
        total_pictures = 0

        for idx, slide in enumerate(prs.slides, start=1):
            shapes_cnt = len(slide.shapes)
            total_shapes += shapes_cnt
            text_snippets = []

            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            text_snippets.append(para.text.strip())
                if shape.has_table:
                    total_tables += 1
                if getattr(shape, "shape_type", None) == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE:
                    total_pictures += 1

            title_text = text_snippets[0] if text_snippets else f"Slide {idx}"
            slides_summary.append({
                "index": idx,
                "title": title_text,
                "shapes_count": shapes_cnt,
                "text_snippets_count": len(text_snippets),
                "summary": " | ".join(text_snippets[:3]),
            })

        return {
            "file_name": p.name,
            "file_size": p.stat().st_size,
            "slides_count": len(prs.slides),
            "total_shapes": total_shapes,
            "total_tables": total_tables,
            "total_pictures": total_pictures,
            "slides": slides_summary,
        }

    @staticmethod
    def verify_with_powerpoint_app(
        file_path: str | Path,
        export_slides_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Abre la presentación en Microsoft PowerPoint real vía COM y exporta diapositivas si se solicita."""
        p = Path(file_path).resolve()
        ppt = None
        pres = None
        presentations = None
        slides = None
        initialized = False
        try:
            import win32com.client  # type: ignore[import-untyped]
            import pythoncom  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            initialized = True

            ppt = win32com.client.DispatchEx("PowerPoint.Application")
            presentations = ppt.Presentations
            # Abrir en modo de sólo lectura
            # Nota: WithWindow=False o True según disponibilidad
            try:
                pres = presentations.Open(str(p), ReadOnly=True, Untitled=False, WithWindow=False)
            except Exception:
                pres = presentations.Open(str(p), ReadOnly=True, Untitled=False)

            slides = pres.Slides
            slides_count = slides.Count

            exported_slides: list[str] = []
            if export_slides_dir:
                export_dir = Path(export_slides_dir).resolve()
                export_dir.mkdir(parents=True, exist_ok=True)
                for s_i in range(1, slides_count + 1):
                    try:
                        slide = slides.Item(s_i)
                        img_out = export_dir / f"slide_{s_i}.png"
                        slide.Export(str(img_out), "PNG", 1920, 1080)
                        if img_out.exists():
                            exported_slides.append(str(img_out))
                        del slide
                    except Exception as e_slide:
                        logger.warning(f"Error exportando diapositiva {s_i}: {e_slide}")

            return {
                "verified": True,
                "engine": "Microsoft PowerPoint (COM)",
                "slides_count": slides_count,
                "opened_without_error": True,
                "exported_images": exported_slides,
            }
        except Exception as e:
            logger.warning(f"[PPT COM VERIFICATION] No se pudo verificar con PowerPoint.Application: {e}")
            return {
                "verified": False,
                "engine": "None",
                "error": str(e),
                "opened_without_error": False,
                "exported_images": [],
            }
        finally:
            if slides is not None:
                del slides
                slides = None
            if pres is not None:
                try:
                    pres.Close()
                except Exception:
                    pass
                del pres
                pres = None
            if presentations is not None:
                del presentations
                presentations = None
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            if ppt is not None:
                try:
                    ppt.Quit()
                except Exception:
                    pass
                del ppt
                ppt = None
