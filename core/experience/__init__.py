"""Paquete de Registro y Análisis de Experiencias (core/experience - Fases 57 & 58).

Exporta las interfaces, modelos, registradores y analizadores para el
JESSYCA EXPERIENCE & LEARNING ENGINE.
"""

from __future__ import annotations

from core.experience.analysis_models import (
    AnalysisWindow,
    CorrectionPattern,
    ExperienceAnalysis,
    ExperienceMetrics,
    FailurePattern,
    IntentPattern,
    LatencyPattern,
    Pattern,
    PatternSeverity,
    PatternType,
    STTPattern,
    SuccessPattern,
)
from core.experience.analyzer import ExperienceAnalyzer
from core.experience.experience_logger import ExperienceLogger, get_experience_logger
from core.experience.experience_store import (
    IExperienceStore,
    InMemoryExperienceStore,
    SQLiteExperienceStore,
)
from core.experience.metrics import calculate_metrics
from core.experience.models import (
    CorrectionInfo,
    ErrorInfo,
    ExecutionResult,
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    ExperienceInput,
    ExperienceMetadata,
    InputSource,
    IntentResult,
    LatencyInfo,
    ResponseResult,
    STTResult,
    TargetInfo,
    VerificationResult,
    VerificationStatus,
)
from core.experience.patterns import (
    detect_all_patterns,
    detect_latency_degradations,
    detect_low_intent_confidence,
    detect_low_stt_confidence,
    detect_repeated_actions,
    detect_repeated_clarifications,
    detect_repeated_failures,
    detect_repeated_successes,
    detect_stt_variants,
    detect_tool_skill_failures,
    detect_user_corrections,
    detect_verification_failures,
)
from core.experience.repository import ExperienceRepository, IExperienceRepository
from core.experience.sanitization import (
    is_sensitive_key,
    sanitize_experience_data,
)

__all__ = [
    "AnalysisWindow",
    "CorrectionInfo",
    "CorrectionPattern",
    "ErrorInfo",
    "ExecutionResult",
    "ExecutionStatus",
    "Experience",
    "ExperienceAnalysis",
    "ExperienceAnalyzer",
    "ExperienceCategory",
    "ExperienceInput",
    "ExperienceLogger",
    "ExperienceMetadata",
    "ExperienceMetrics",
    "ExperienceRepository",
    "FailurePattern",
    "IExperienceRepository",
    "IExperienceStore",
    "InMemoryExperienceStore",
    "InputSource",
    "IntentPattern",
    "IntentResult",
    "LatencyInfo",
    "LatencyPattern",
    "Pattern",
    "PatternSeverity",
    "PatternType",
    "ResponseResult",
    "SQLiteExperienceStore",
    "STTPattern",
    "STTResult",
    "SuccessPattern",
    "TargetInfo",
    "VerificationResult",
    "VerificationStatus",
    "calculate_metrics",
    "detect_all_patterns",
    "detect_latency_degradations",
    "detect_low_intent_confidence",
    "detect_low_stt_confidence",
    "detect_repeated_actions",
    "detect_repeated_clarifications",
    "detect_repeated_failures",
    "detect_repeated_successes",
    "detect_stt_variants",
    "detect_tool_skill_failures",
    "detect_user_corrections",
    "detect_verification_failures",
    "get_experience_logger",
    "is_sensitive_key",
    "sanitize_experience_data",
]
