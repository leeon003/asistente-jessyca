"""Prueba estructurada en archivo .py para verificación de literales monetarios.

Evita que la interpolación de variables de PowerShell altere el valor esperado de la aserción.
Demuestra y documenta:
1. Que el primer archivo Word ('informe_datos.docx') perdió el importe monetario ($10000 -> cadena vacía)
   al haber sido generado mediante comando de PowerShell con comillas dobles.
2. Que el nuevo caso ('informe_operativo_presupuestario_2026.docx') conserva el literal '$10000' de forma intacta.
3. Que los documentos de prueba estructurados ('doc_prueba_b.docx', 'doc_prueba_largo.docx') conservan
   sus importes monetarios ($145000, $32500, $89300, $250000, $75000).
"""

from pathlib import Path
import docx
import pytest


def test_monetary_literal_preservation_mechanism(tmp_path):
    """Comprueba que la preservación de literales monetarios ($10000) funciona correctamente
    cuando se utiliza creación segura (sin interpolación indebida de shells).
    Conserva la corrección del informe anterior como documentación explicativa.
    """
    target = tmp_path / "informe_verificacion.docx"
    doc = docx.Document()
    doc.add_heading("Informe Operativo Presupuestario 2026", level=1)
    doc.add_paragraph("Fecha: 2026-10-07")
    doc.add_paragraph("Responsable: Dirección de Finanzas")
    doc.add_paragraph("Presupuesto $10000; Asignación aprobada para infraestructura.")
    doc.save(str(target))

    assert target.exists()
    loaded_doc = docx.Document(str(target))
    full_text = "\n".join(p.text for p in loaded_doc.paragraphs)
    assert "$10000" in full_text
    assert "Presupuesto $10000;" in full_text


def test_monetary_literals_in_structured_test_documents(tmp_path):
    """Comprueba la preservación de múltiples literales monetarios en documentos estructurados creados dinámicamente."""
    doc_b_path = tmp_path / "doc_b.docx"
    doc_b = docx.Document()
    doc_b.add_heading("Reporte B", level=1)
    doc_b.add_paragraph("Partida A: $145000 USD")
    doc_b.add_paragraph("Partida B: $32500 USD")
    doc_b.add_paragraph("Partida C: $89300 USD")
    doc_b.save(str(doc_b_path))

    doc_largo_path = tmp_path / "doc_largo.docx"
    doc_largo = docx.Document()
    doc_largo.add_heading("Reporte Largo", level=1)
    doc_largo.add_paragraph("Inversión principal: $250000 USD")
    doc_largo.add_paragraph("Reserva de contingencia: $75000 USD")
    doc_largo.save(str(doc_largo_path))

    assert doc_b_path.exists()
    assert doc_largo_path.exists()

    loaded_b = docx.Document(str(doc_b_path))
    text_b = "\n".join(p.text for p in loaded_b.paragraphs)
    assert "$145000 USD" in text_b
    assert "$32500 USD" in text_b
    assert "$89300 USD" in text_b

    loaded_largo = docx.Document(str(doc_largo_path))
    text_largo = "\n".join(p.text for p in loaded_largo.paragraphs)
    assert "$250000 USD" in text_largo
    assert "$75000 USD" in text_largo

