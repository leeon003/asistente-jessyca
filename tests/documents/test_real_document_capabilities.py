"""Suite de pruebas de certificación de capacidades documentales reales (test_real_document_capabilities.py).

Cubre los tres recorridos funcionales requeridos:
1. WORD: Creación de informe desde datos y edición conservando el original.
2. EXCEL: Creación de presupuesto con fórmulas, gráfico y comprobación de resultados calculados (motor COM).
3. POWERPOINT: Creación de presentación de 5 diapositivas con estructura, tabla, viñetas e imagen.
4. AUDITORÍA Y VERIFICACIÓN: Distinción de capacidades, comprobación con AnyDoc e inspección de no-vacuidad.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from core.documents.anydoc_verifier import AnyDocDocumentVerifier
from core.documents.document_orchestrator import DocumentWorkflowOrchestrator
from core.documents.excel_processor import BudgetItem, ExcelSpreadsheetProcessor
from core.documents.powerpoint_processor import (
    PowerPointPresentationProcessor,
    SlideContent,
)
from core.documents.system_audit import DocumentSystemAuditor
from core.documents.word_processor import WordDocumentProcessor, WordSection


@pytest.fixture
def test_output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "pruebas_doc"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ── TEST 1: Auditoría Técnica del Sistema Documental ──
def test_document_system_audit() -> None:
    """Verifica que la auditoría detecta software instalado, bibliotecas y declara limitaciones honestamente."""
    report = DocumentSystemAuditor.audit()

    assert report.os_name != ""
    assert report.python_version != ""

    # Bibliotecas clave instaladas
    assert report.libraries["docx"].installed is True
    assert report.libraries["openpyxl"].installed is True
    assert report.libraries["pptx"].installed is True
    assert report.libraries["win32com.client"].installed is True

    # Aplicaciones Microsoft Office vía COM
    word_app = report.office_apps.get("Word.Application")
    excel_app = report.office_apps.get("Excel.Application")
    ppt_app = report.office_apps.get("PowerPoint.Application")

    assert word_app is not None and word_app.installed is True
    assert excel_app is not None and excel_app.installed is True
    assert ppt_app is not None and ppt_app.installed is True

    # Motor de cálculo y AnyDoc
    assert report.has_excel_calc_engine is True
    assert report.has_anydoc_engine is True

    # Declaración explícita de limitaciones
    assert len(report.limitations) >= 3
    assert any("openpyxl" in lim.lower() for lim in report.limitations)
    assert any("macros" in lim.lower() for lim in report.limitations)


# ── TEST 2: Recorrido Funcional WORD (Creación, Estilo y Edición con Preservación) ──
def test_word_report_creation_and_preservation_edit(test_output_dir: Path) -> None:
    """Crea un informe Word desde datos y lo edita conservando el contenido original."""
    doc_path = test_output_dir / "Informe_Prueba.docx"
    doc_edit_path = test_output_dir / "Informe_Prueba_Editado.docx"

    sections = [
        WordSection(
            heading="1. Introducción y Contexto",
            heading_level=1,
            paragraphs=[
                "Documento de prueba funcional para **JESSYCA 3.0**.",
                "Este informe evalúa la capacidad de estructuración en Microsoft Word (.docx).",
            ],
            bullets=["Objetivo 1: Estructura clara", "Objetivo 2: Tablas legibles"],
        ),
        WordSection(
            heading="2. Datos Operativos",
            heading_level=1,
            paragraphs=["Tabla de datos iniciales suministrados:"],
            table_headers=["Métrica", "Valor Inicial", "Estado"],
            table_rows=[
                ["Latencia STT", "45 ms", "Aprobado"],
                ["Precisión de Intención", "98.5%", "Aprobado"],
                ["Confinamiento Sandbox", "100%", "Verificado"],
            ],
        ),
    ]

    # 1. Creación inicial
    res_create = WordDocumentProcessor.create_report(
        file_path=doc_path,
        title="Informe Operativo de Calidad",
        subtitle="Evaluación de Automatización Documental",
        sections=sections,
    )
    assert res_create["success"] is True
    assert doc_path.exists()
    assert doc_path.stat().st_size > 0

    insp_init = WordDocumentProcessor.inspect_document(doc_path)
    assert insp_init["paragraphs_count"] >= 5
    assert insp_init["tables_count"] == 1
    assert "Informe Operativo de Calidad" in insp_init["sample_text"]

    # 2. Edición conservando original
    anexo = [
        WordSection(
            heading="3. Anexo de Auditoría Adicional",
            heading_level=1,
            paragraphs=["Párrafo adicional agregado en la etapa de edición."],
            table_headers=["Control", "Resultado"],
            table_rows=[["Anti-falsos éxitos", "Cumplido"]],
        )
    ]
    res_edit = WordDocumentProcessor.edit_document(
        file_path=doc_path,
        additions=anexo,
        preserve_original=True,
        output_path=doc_edit_path,
    )
    assert res_edit["success"] is True
    assert doc_edit_path.exists()
    assert doc_edit_path.stat().st_size > 0

    insp_edit = WordDocumentProcessor.inspect_document(doc_edit_path)
    assert insp_edit["paragraphs_count"] > insp_init["paragraphs_count"]
    assert insp_edit["tables_count"] == 2
    assert "Informe Operativo de Calidad" in insp_edit["sample_text"]  # Original intacto

    # 3. Verificación con Word COM
    word_check = WordDocumentProcessor.verify_with_word_app(doc_edit_path)
    assert word_check["verified"] is True
    assert word_check["opened_without_error"] is True
    assert word_check["tables_count"] == 2

    # 4. Verificación con AnyDoc
    anydoc_verifier = AnyDocDocumentVerifier()
    anydoc_res = anydoc_verifier.verify_document(doc_edit_path, expected_format="docx")
    assert anydoc_res["verified"] is True
    assert anydoc_res["char_count"] > 100


# ── TEST 3: Recorrido Funcional EXCEL (Fórmulas, Gráficos y Motor de Cálculo) ──
def test_excel_budget_creation_formulas_and_calculation_engine(test_output_dir: Path) -> None:
    """Crea un presupuesto en Excel con fórmulas, gráfico y valida el motor de cálculo COM."""
    excel_path = test_output_dir / "Presupuesto_Prueba.xlsx"

    items = [
        BudgetItem("Servidor GPU RTX", "Hardware", 2.0, 4000.0),      # Subtotal = 8000
        BudgetItem("Unidades SSD NVMe", "Hardware", 4.0, 500.0),       # Subtotal = 2000
        BudgetItem("Licencias de Modelos", "Software", 5.0, 200.0),    # Subtotal = 1000
    ]
    # Total directo esperado = 11,000.00
    # Impuesto esperado (18%) = 1,980.00
    # Presupuesto total esperado = 12,980.00

    res_create = ExcelSpreadsheetProcessor.create_budget_workbook(
        file_path=excel_path,
        items=items,
        titulo_presupuesto="Presupuesto de Prueba Funcional",
        tasa_impuesto=0.18,
    )
    assert res_create["success"] is True
    assert excel_path.exists()
    assert excel_path.stat().st_size > 0

    # 1. Distinción: openpyxl lee fórmulas como cadenas literales
    raw_data = ExcelSpreadsheetProcessor.read_data(excel_path, data_only=False)
    subtotal_formulas = [row[4] for row in raw_data if len(row) >= 5 and str(row[4]).startswith("=")]
    assert len(subtotal_formulas) >= 3
    assert "=C5*D5" in subtotal_formulas
    assert any("SUM" in str(f) for f in subtotal_formulas)

    # 2. Motor de cálculo: evaluar fórmulas con Microsoft Excel COM
    calc_res = ExcelSpreadsheetProcessor.evaluate_formulas_with_engine(excel_path)
    assert calc_res["has_engine"] is True
    assert calc_res["evaluated_formulas_count"] >= 5

    results = calc_res["results"]
    assert "E5" in results and results["E5"]["calculated_value"] == 8000.0
    assert "E6" in results and results["E6"]["calculated_value"] == 2000.0
    assert "E7" in results and results["E7"]["calculated_value"] == 1000.0
    assert "E8" in results and results["E8"]["calculated_value"] == 11000.0  # SUM
    assert "E9" in results and results["E9"]["calculated_value"] == 1980.0   # 18% Tax
    assert "E10" in results and results["E10"]["calculated_value"] == 12980.0 # Total Gral

    # 3. Leer valores calculados persistidos
    cached_data = ExcelSpreadsheetProcessor.read_data(excel_path, data_only=True)
    row_total_directo = next(r for r in cached_data if r and r[0] == "TOTAL COSTO DIRECTO")
    assert row_total_directo[4] == 11000.0

    # 4. Inspección estructural (gráfico presente)
    insp = ExcelSpreadsheetProcessor.inspect_workbook(excel_path)
    assert insp["total_charts"] >= 1
    assert insp["total_formulas"] >= 5

    # 5. Verificación con AnyDoc
    anydoc_verifier = AnyDocDocumentVerifier()
    anydoc_res = anydoc_verifier.verify_document(excel_path, expected_format="xlsx")
    assert anydoc_res["verified"] is True
    assert anydoc_res["char_count"] > 50


# ── TEST 4: Recorrido Funcional POWERPOINT (Presentación de 5 Diapositivas) ──
def test_powerpoint_five_slides_deck_from_word_report(test_output_dir: Path) -> None:
    """Crea una presentación de exactamente 5 diapositivas con tablas, viñetas e imagen."""
    pptx_path = test_output_dir / "Presentacion_Prueba.pptx"
    chart_img = test_output_dir / "grafico_prueba.png"

    # Generar imagen de gráfico
    orch = DocumentWorkflowOrchestrator(output_dir=test_output_dir)
    items = [
        BudgetItem("Servidor GPU", "Hardware", 2.0, 4000.0),
        BudgetItem("Almacenamiento", "Hardware", 4.0, 500.0),
        BudgetItem("Licencias", "Software", 5.0, 200.0),
    ]
    img_path = orch.generate_chart_image(chart_img, items)
    assert os.path.exists(img_path)

    slides = [
        SlideContent(
            title="Presentación de Resultados JESSYCA",
            subtitle="Informe y Presupuesto Q3 2026",
            category_label="PORTADA EJECUTIVA",
        ),
        SlideContent(
            title="Resumen Ejecutivo y Objetivos",
            subtitle="Hitos principales consolidados",
            category_label="ESTRATEGIA",
            bullets=[
                "Hito 1: Gobernanza canónica implementada con éxito.",
                "Hito 2: Verificación física observable en todas las acciones.",
                "Hito 3: Automatización de documentos Office nativa.",
            ],
        ),
        SlideContent(
            title="Resumen Presupuestario Consolidado",
            subtitle="Detalle de asignación por categoría",
            category_label="PRESUPUESTO",
            table_headers=["Concepto", "Categoría", "Costo ($)"],
            table_rows=[
                ["Servidor GPU", "Hardware", "$8,000.00"],
                ["Almacenamiento", "Hardware", "$2,000.00"],
                ["Licencias", "Software", "$1,000.00"],
                ["TOTAL ESTIMADO", "Consolidado", "$11,000.00"],
            ],
        ),
        SlideContent(
            title="Análisis Gráfico de Distribución",
            subtitle="Visualización del esfuerzo de inversión",
            category_label="ANÁLISIS VISUAL",
            image_path=img_path,
            bullets=[
                "Concentración principal en cómputo local.",
                "Almacenamiento de alta velocidad NVMe.",
            ],
        ),
        SlideContent(
            title="Conclusiones y Hoja de Ruta",
            subtitle="Próximos pasos para el despliegue final",
            category_label="PLAN DE ACCIÓN",
            bullets=[
                "Aprobación de la arquitectura documental.",
                "Integración con asistentes locales subordinados.",
                "Cero tolerancia a falsos éxitos mantenida.",
            ],
        ),
    ]

    res_create = PowerPointPresentationProcessor.create_presentation(
        file_path=pptx_path,
        slides_data=slides,
        presenter="JESSYCA QA Tester",
    )
    assert res_create["success"] is True
    assert pptx_path.exists()
    assert pptx_path.stat().st_size > 0

    # 1. Inspección estructural (exactamente 5 diapositivas)
    insp = PowerPointPresentationProcessor.inspect_presentation(pptx_path)
    assert insp["slides_count"] == 5
    assert insp["total_tables"] >= 1
    assert insp["total_pictures"] >= 1

    # 2. Verificación y renderizado visual con PowerPoint COM
    render_dir = test_output_dir / "render_slides"
    ppt_check = PowerPointPresentationProcessor.verify_with_powerpoint_app(
        file_path=pptx_path,
        export_slides_dir=render_dir,
    )
    assert ppt_check["verified"] is True
    assert ppt_check["opened_without_error"] is True
    assert ppt_check["slides_count"] == 5
    assert len(ppt_check["exported_images"]) == 5
    for img_exported in ppt_check["exported_images"]:
        assert os.path.exists(img_exported)
        assert os.path.getsize(img_exported) > 0

    # 3. Verificación con AnyDoc
    anydoc_verifier = AnyDocDocumentVerifier()
    anydoc_res = anydoc_verifier.verify_document(pptx_path, expected_format="pptx")
    assert anydoc_res["verified"] is True
    assert anydoc_res["char_count"] > 100


# ── TEST 5: Orquestador Completo de Flujos en Carpeta Real de Pruebas ──
def test_end_to_end_document_orchestrator() -> None:
    """Ejecuta los tres recorridos completos y consolida los archivos reales en data/pruebas_documentales/."""
    target_dir = Path("data/pruebas_documentales").resolve()
    orch = DocumentWorkflowOrchestrator(output_dir=target_dir)

    results = orch.run_all()
    assert results["all_verified"] is True

    # 1. Comprobar archivos reales de Word
    word_file = Path(results["word_workflow"]["updated_file"])
    assert word_file.exists() and word_file.stat().st_size > 10000

    # 2. Comprobar archivo real de Excel y cálculo
    excel_file = Path(results["excel_workflow"]["excel_file"])
    assert excel_file.exists() and excel_file.stat().st_size > 5000
    assert results["excel_workflow"]["calculation_engine_result"]["has_engine"] is True

    # 3. Comprobar archivo real de PowerPoint y renderizado
    pptx_file = Path(results["powerpoint_workflow"]["pptx_file"])
    assert pptx_file.exists() and pptx_file.stat().st_size > 20000
    assert results["powerpoint_workflow"]["slides_count"] == 5
    assert len(results["powerpoint_workflow"]["powerpoint_com_verification"]["exported_images"]) == 5
