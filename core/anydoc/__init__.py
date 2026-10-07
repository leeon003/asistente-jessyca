"""Inicialización del subsistema AnyDoc para JESSYCA PC."""

from core.anydoc.adapter import AnyDocAdapter
from core.anydoc.docling_backend import DoclingBackend
from core.anydoc.models import (
    AnyDocMode,
    AnyDocProposal,
    AnyDocReceipt,
    AnyDocResult,
    AnyDocTaskContract,
    ConversionStatus,
    DocumentFormat,
)
from core.anydoc.orchestrator import AnyDocGovernedOrchestrator, AnyDocOrchestrator
from core.anydoc.shadow import AnyDocShadowEvaluator, AnyDocShadowRecord

__all__ = [
    "AnyDocAdapter",
    "AnyDocGovernedOrchestrator",
    "AnyDocOrchestrator",
    "AnyDocMode",
    "AnyDocProposal",
    "AnyDocReceipt",
    "AnyDocResult",
    "AnyDocShadowEvaluator",
    "AnyDocShadowRecord",
    "AnyDocTaskContract",
    "ConversionStatus",
    "DoclingBackend",
    "DocumentFormat",
]

