"""Módulo de capacidades documentales avanzadas de JESSYCA 3.0.

Incluye procesadores para:
- Word (.docx): WordDocumentProcessor, WordSection
- Excel (.xlsx): ExcelSpreadsheetProcessor, BudgetItem
- PowerPoint (.pptx): PowerPointPresentationProcessor, SlideContent
- Auditoría: DocumentSystemAuditor, DocumentSystemAuditReport
- AnyDoc Verificador: AnyDocDocumentVerifier
"""

from core.documents.anydoc_verifier import AnyDocDocumentVerifier
from core.documents.document_orchestrator import DocumentWorkflowOrchestrator
from core.documents.excel_processor import BudgetItem, ExcelSpreadsheetProcessor
from core.documents.powerpoint_processor import (
    PowerPointPresentationProcessor,
    SlideContent,
)
from core.documents.system_audit import (
    DocumentSystemAuditor,
    DocumentSystemAuditReport,
)
from core.documents.word_processor import WordDocumentProcessor, WordSection

__all__ = [
    "AnyDocDocumentVerifier",
    "BudgetItem",
    "DocumentSystemAuditReport",
    "DocumentSystemAuditor",
    "DocumentWorkflowOrchestrator",
    "ExcelSpreadsheetProcessor",
    "PowerPointPresentationProcessor",
    "SlideContent",
    "WordDocumentProcessor",
    "WordSection",
]
