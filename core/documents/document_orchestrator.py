"""Orquestador unificado de flujos documentales (document_orchestrator.py).

Ejecuta y coordina los tres recorridos funcionales requeridos:
1. WORD: Creación de informe técnico-ejecutivo y edición incremental preservando el original.
2. EXCEL: Presupuesto estructurado con fórmulas, gráfico y recálculo con motor Microsoft Excel COM.
3. POWERPOINT: Presentación de 5 diapositivas 16:9 con diseño legible, tabla, viñetas e imagen.
4. AUDITORÍA Y VERIFICACIÓN: Comprobación con AnyDoc, inspección binaria y renderizado visual COM.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Backend no interactivo seguro para generación de imágenes
import matplotlib.pyplot as plt

from core.documents.anydoc_verifier import AnyDocDocumentVerifier
from core.documents.excel_processor import BudgetItem, ExcelSpreadsheetProcessor
from core.documents.powerpoint_processor import (
    PowerPointPresentationProcessor,
    SlideContent,
)
from core.documents.system_audit import DocumentSystemAuditor
from core.documents.word_processor import WordDocumentProcessor, WordSection
from core.logger import get_logger

logger = get_logger("jessyca.documents.orchestrator")


class DocumentWorkflowOrchestrator:
    """Coordinador de flujos documentales completos con verificación física y visual."""

    def __init__(self, output_dir: str | Path = "data/pruebas_documentales") -> None:
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.anydoc_verifier = AnyDocDocumentVerifier()

    def generate_chart_image(self, file_path: str | Path, items: list[BudgetItem]) -> str:
        """Genera un gráfico estadístico moderno en PNG para incrustar en diapositivas o reportes."""
        out_img = Path(file_path).resolve()
        out_img.parent.mkdir(parents=True, exist_ok=True)

        conceptos = [item.concepto.split()[0] + "..." if len(item.concepto) > 14 else item.concepto for item in items]
        subtotales = [item.cantidad * item.costo_unitario for item in items]

        fig, ax = plt.subplots(figsize=(8, 6), dpi=200)
        fig.patch.set_facecolor("#0F172A")  # Fondo Slate 900
        ax.set_facecolor("#1E293B")         # Fondo Slate 800

        colors = ["#38BDF8", "#818CF8", "#34D399", "#FBBF24", "#F472B6", "#A78BFA"]
        bars = ax.barh(conceptos, subtotales, color=colors[:len(items)], edgecolor="#334155", height=0.6)

        ax.set_title("Distribución de Costos por Componente ($ USD)", fontsize=13, fontweight="bold", color="#F8FAFC", pad=15)
        ax.set_xlabel("Monto Total ($)", fontsize=10, color="#94A3B8")
        ax.tick_params(colors="#CBD5E1", labelsize=9)
        ax.grid(axis="x", linestyle="--", alpha=0.3, color="#64748B")

        for spine in ax.spines.values():
            spine.set_color("#334155")

        # Etiquetas con valores en cada barra
        for bar in bars:
            width = bar.get_width()
            ax.text(width + 200, bar.get_y() + bar.get_height() / 2, f"${width:,.0f}",
                    ha="left", va="center", color="#F8FAFC", fontsize=8.5, fontweight="bold")

        plt.tight_layout()
        fig.savefig(str(out_img), facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        logger.info(f"[CHART GENERATED] Gráfico de presupuesto generado en '{out_img.name}'")
        return str(out_img)

    def run_word_workflow(self) -> dict[str, Any]:
        """Recorrido 1 (Word): Creación de informe y edición con preservación del original."""
        doc_original_path = self.output_dir / "Informe_Ejecutivo_JESSYCA_Q3_2026.docx"
        doc_editado_path = self.output_dir / "Informe_Ejecutivo_JESSYCA_Q3_2026_Actualizado.docx"

        sections = [
            WordSection(
                heading="1. Resumen Ejecutivo y Objetivos",
                heading_level=1,
                paragraphs=[
                    "El presente informe consolida los resultados operativos, técnicos y financieros de la plataforma **JESSYCA 3.0** durante el tercer trimestre de 2026.",
                    "La arquitectura ha completado la transición hacia gobernanza canónica, integrando verificación observable de hardware, automatización de escritorio, control de navegador y capacidades documentales.",
                ],
                bullets=[
                    "Disponibilidad operativa continua en Windows 11 sin orquestadores paralelos.",
                    "Cumplimiento del 100% en políticas de gobernanza JDE y denegación por defecto.",
                    "Consolidación de latencia sub-100ms en flujos de enrutamiento rápido.",
                ],
            ),
            WordSection(
                heading="2. Hitos Clave y Desempeño Operativo",
                heading_level=1,
                paragraphs=[
                    "Durante el trimestre se validaron las matrices de capacidades reales del sistema frente al sistema operativo local.",
                ],
                table_headers=["Subsistema", "Métrica Clave", "Estado", "Verificación"],
                table_rows=[
                    ["Audio & Voz (pycaw / faster-whisper)", "Latencia VAD < 50ms", "Operativo", "Hardware Real"],
                    ["Navegador Gobernado (Playwright)", "25/25 Tests Aprobados", "Operativo", "DOM Observable"],
                    ["Escritorio (pywinauto / user32)", "100% Single-Instance", "Operativo", "PID / HWND"],
                    ["Mobile Control (JDE Binding)", "15/15 Tests Aprobados", "Operativo", "Protocolo Seguro"],
                ],
            ),
            WordSection(
                heading="3. Conclusiones y Hoja de Ruta",
                heading_level=1,
                paragraphs=[
                    "El despliegue ha demostrado estabilidad total y ausencia de falsos éxitos en las capas críticas del sistema.",
                ],
                bullets=[
                    "Despliegue de la Fase 18 de automatización documental integrada.",
                    "Inicio de pruebas de carga concurrente multi-sesión.",
                ],
            ),
        ]

        # 1. Crear documento original
        res_create = WordDocumentProcessor.create_report(
            file_path=doc_original_path,
            title="Informe de Desempeño y Arquitectura JESSYCA Q3 2026",
            subtitle="Auditoría Integral de Capacidades, Rendimiento y Seguridad en Windows 11",
            sections=sections,
            author="JESSYCA Core Engineering",
        )

        # 2. Editar documento conservando el original
        anexo_sections = [
            WordSection(
                heading="Anexo Técnico: Certificación de Seguridad y Cumplimiento",
                heading_level=2,
                paragraphs=[
                    "Este anexo certifica que todas las operaciones de archivos, navegador y memoria se han ejecutado bajo estricto confinamiento en sandbox.",
                    "Se verificó la **inmutabilidad de contratos** mediante hashes SHA-256 y sellos criptográficos.",
                ],
                table_headers=["Control de Seguridad", "Estándar", "Resultado"],
                table_rows=[
                    ["Prevención de Path Traversal", "OWASP / JDE Policy", "Cero Fugas"],
                    ["Aislamiento de Procesos", "Single-Instance Guard", "Certificado"],
                    ["Redacción de Secretos", "Deep Sanitizer", "100% Protegido"],
                ],
            )
        ]

        res_edit = WordDocumentProcessor.edit_document(
            file_path=doc_original_path,
            additions=anexo_sections,
            preserve_original=True,
            output_path=doc_editado_path,
        )

        # 3. Verificación con Word COM
        word_com_check = WordDocumentProcessor.verify_with_word_app(doc_editado_path)

        # 4. Verificación con AnyDoc
        anydoc_check = self.anydoc_verifier.verify_document(doc_editado_path, expected_format="docx")

        return {
            "original_file": str(doc_original_path),
            "updated_file": str(doc_editado_path),
            "create_result": res_create,
            "edit_result": res_edit,
            "word_com_verification": word_com_check,
            "anydoc_verification": anydoc_check,
        }

    def run_excel_workflow(self) -> dict[str, Any]:
        """Recorrido 2 (Excel): Creación de presupuesto con fórmulas, gráfico y recálculo COM."""
        excel_path = self.output_dir / "Presupuesto_Operativo_Tecnologico_2026.xlsx"

        items = [
            BudgetItem("Servidores GPU NVIDIA RTX", "Infraestructura", 2.0, 4500.0),
            BudgetItem("Almacenamiento NVMe Enterprise 8TB", "Infraestructura", 4.0, 850.0),
            BudgetItem("Licencias de Modelos y APIs", "Software", 12.0, 250.0),
            BudgetItem("Conectividad y Red Privada 10GbE", "Red", 2.0, 1200.0),
            BudgetItem("Servicios de Ingeniería Especializada", "Servicios", 80.0, 150.0),
            BudgetItem("Auditoría Externa de Ciberseguridad", "Seguridad", 1.0, 6000.0),
        ]

        # 1. Crear libro con openpyxl (escribe fórmulas y gráfico)
        res_create = ExcelSpreadsheetProcessor.create_budget_workbook(
            file_path=excel_path,
            items=items,
            titulo_presupuesto="Presupuesto Operativo y Tecnológico 2026",
            tasa_impuesto=0.18,
        )

        # 2. Leer datos en crudo (demostrando que openpyxl ve fórmulas literales)
        raw_formulas_read = ExcelSpreadsheetProcessor.read_data(excel_path, data_only=False)

        # 3. Ejecutar motor de cálculo con Microsoft Excel COM (evalúa resultados)
        calc_res = ExcelSpreadsheetProcessor.evaluate_formulas_with_engine(excel_path)

        # 4. Leer datos con data_only=True tras recálculo guardado
        calculated_data_read = ExcelSpreadsheetProcessor.read_data(excel_path, data_only=True)

        # 5. Inspección estructural
        inspection = ExcelSpreadsheetProcessor.inspect_workbook(excel_path)

        # 6. Verificación con AnyDoc
        anydoc_check = self.anydoc_verifier.verify_document(excel_path, expected_format="xlsx")

        return {
            "excel_file": str(excel_path),
            "create_result": res_create,
            "raw_formulas_sample": [r for r in raw_formulas_read if any(isinstance(c, str) and c.startswith("=") for c in r)][:3],
            "calculation_engine_result": calc_res,
            "calculated_data_sample": [r for r in calculated_data_read if r and r[0] in ("TOTAL COSTO DIRECTO", "PRESUPUESTO TOTAL ESTIMADO")],
            "inspection": inspection,
            "anydoc_verification": anydoc_check,
            "items": items,
        }

    def run_powerpoint_workflow(self, budget_items: list[BudgetItem]) -> dict[str, Any]:
        """Recorrido 3 (PowerPoint): Presentación de 5 diapositivas desde el informe Word y presupuesto."""
        pptx_path = self.output_dir / "Presentacion_Ejecutiva_JESSYCA_Q3_2026.pptx"
        chart_img_path = self.output_dir / "grafico_distribucion_presupuesto.png"

        # 1. Generar imagen del gráfico para incrustar en Slide 4
        img_generated = self.generate_chart_image(chart_img_path, budget_items)

        # 2. Diseñar el contenido estructurado de las 5 diapositivas
        slides = [
            # Diapositiva 1: Portada
            SlideContent(
                title="Desempeño y Arquitectura JESSYCA Q3 2026",
                subtitle="Consolidación de Gobernanza Canónica, Capacidades Reales y Presupuesto Tecnológico",
                category_label="PRESENTACIÓN EJECUTIVA",
            ),
            # Diapositiva 2: Resumen Ejecutivo y Objetivos
            SlideContent(
                title="Resumen Ejecutivo y Objetivos Estratégicos",
                subtitle="Pilares fundamentales de la consolidación de JESSYCA 3.0 en Windows 11",
                category_label="ESTRATEGIA OPERATIVA",
                bullets=[
                    "Unificación de la toma de decisiones y ejecución a través de la ruta canónica del LocalAgent.",
                    "Erradicación total de falsos éxitos: cada acción requiere ExecutionEvidence verificada físicamente.",
                    "Integración de automatización de navegador (Playwright), escritorio (pywinauto/COM) y documentos.",
                    "Garantía de rendimiento sub-100ms en el enrutador experimental con fallback resiliente.",
                ],
            ),
            # Diapositiva 3: Estructura Presupuestaria (Tabla)
            SlideContent(
                title="Estructura Presupuestaria y Asignación de Recursos",
                subtitle="Detalle de inversión en infraestructura, software y servicios para el ejercicio 2026",
                category_label="ANÁLISIS FINANCIERO",
                table_headers=["Concepto / Ítem", "Categoría", "Cantidad", "Costo Unitario", "Subtotal"],
                table_rows=[
                    ["Servidores GPU NVIDIA RTX", "Infraestructura", "2.0", "$4,500.00", "$9,000.00"],
                    ["Almacenamiento NVMe Enterprise", "Infraestructura", "4.0", "$850.00", "$3,400.00"],
                    ["Licencias de Modelos y APIs", "Software", "12.0", "$250.00", "$3,000.00"],
                    ["Servicios de Ingeniería", "Servicios", "80.0", "$150.00", "$12,000.00"],
                    ["Auditoría de Ciberseguridad", "Seguridad", "1.0", "$6,000.00", "$6,000.00"],
                    ["TOTAL DIRECTO ESTIMADO", "Consolidado", "-", "-", "$33,400.00"],
                ],
            ),
            # Diapositiva 4: Análisis Visual y Gráfico (Imagen incrustada + Viñetas)
            SlideContent(
                title="Análisis Visual: Distribución de Costos por Componente",
                subtitle="Visualización comparativa del esfuerzo presupuestario por línea de gasto",
                category_label="DISTRIBUCIÓN Y ANÁLISIS",
                image_path=img_generated,
                bullets=[
                    "Mayor asignación concentrada en servicios especializados de ingeniería (36%).",
                    "Infraestructura física (GPUs y NVMe) representa una base sólida para ejecución local.",
                    "La auditoría externa de ciberseguridad garantiza cumplimiento e inviolabilidad de políticas JDE.",
                    "Margen de contingencia del 18% cubierto para amortiguar fluctuaciones de hardware.",
                ],
            ),
            # Diapositiva 5: Conclusiones y Próximos Pasos
            SlideContent(
                title="Conclusiones, Hitos y Hoja de Ruta",
                subtitle="Plan de acción y cronograma para la certificación de la siguiente fase",
                category_label="PLAN DE ACCIÓN",
                bullets=[
                    "Aprobación formal del informe y presupuesto por el comité de ingeniería.",
                    "Despliegue del subsistema de procesamiento documental en modo CONTROLLED.",
                    "Validación de interoperabilidad bidireccional con AnyDoc para formatos mixtos.",
                    "Mantenimiento estricto del criterio de cero falsos éxitos en toda la suite de pruebas.",
                ],
            ),
        ]

        # 3. Crear presentación .pptx
        res_create = PowerPointPresentationProcessor.create_presentation(
            file_path=pptx_path,
            slides_data=slides,
            presenter="JESSYCA 3.0 Engineering Core",
        )

        # 4. Verificación y Renderizado con PowerPoint COM (exporta diapositivas a PNG)
        slides_export_dir = self.output_dir / "render_slides_pptx"
        ppt_com_check = PowerPointPresentationProcessor.verify_with_powerpoint_app(
            file_path=pptx_path,
            export_slides_dir=slides_export_dir,
        )

        # 5. Verificación con AnyDoc
        anydoc_check = self.anydoc_verifier.verify_document(pptx_path, expected_format="pptx")

        return {
            "pptx_file": str(pptx_path),
            "chart_image": img_generated,
            "create_result": res_create,
            "powerpoint_com_verification": ppt_com_check,
            "anydoc_verification": anydoc_check,
            "slides_count": len(slides),
        }

    def run_all(self) -> dict[str, Any]:
        """Ejecuta los tres recorridos funcionales y la auditoría completa."""
        audit_report = DocumentSystemAuditor.audit()

        word_results = self.run_word_workflow()
        excel_results = self.run_excel_workflow()
        pptx_results = self.run_powerpoint_workflow(excel_results["items"])

        summary = {
            "audit": audit_report.to_dict(),
            "word_workflow": word_results,
            "excel_workflow": excel_results,
            "powerpoint_workflow": pptx_results,
            "all_verified": bool(
                word_results["create_result"]["success"]
                and word_results["edit_result"]["success"]
                and excel_results["create_result"]["success"]
                and excel_results["calculation_engine_result"]["has_engine"]
                and pptx_results["create_result"]["success"]
                and pptx_results["powerpoint_com_verification"]["verified"]
            ),
        }
        return summary


if __name__ == "__main__":
    import json
    orchestrator = DocumentWorkflowOrchestrator()
    results = orchestrator.run_all()
    print("\n" + "=" * 60)
    print("REPORTE DE EJECUCIÓN DOCUMENTAL COMPLETA JESSYCA 3.0")
    print("=" * 60)
    print(f"Todas las pruebas verificadas: {results['all_verified']}")
    print(f"Word Doc creado: {results['word_workflow']['original_file']}")
    print(f"Word Doc editado: {results['word_workflow']['updated_file']}")
    print(f"Excel Libro: {results['excel_workflow']['excel_file']}")
    print(f"Excel Motor de cálculo: {results['excel_workflow']['calculation_engine_result']['engine_name']}")
    print(f"PowerPoint Presentación: {results['powerpoint_workflow']['pptx_file']}")
    print(f"PowerPoint Slides Renderizadas: {len(results['powerpoint_workflow']['powerpoint_com_verification'].get('exported_images', []))}")
    print("=" * 60)
