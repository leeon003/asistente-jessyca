"""Arquitectura de Memoria a Largo Plazo Inteligente de JESSYCA (long_term_memory.py - Fase 42).

PRINCIPIOS E INVARIANTES:
1. MEMORY IS NOT AUTHORITY: Ningún registro en memoria puede sustituir, conceder ni relajar permisos de seguridad.
2. PROVENANCE & INTEGRITY: Trazabilidad completa de origen, emisor, confianza, alcance y sensibilidad.
3. POISONING DEFENSE: Neutralización activa de prompt injections y afirmaciones falsas de autorización.
4. PRIVACY BY DESIGN: Redacción de secretos sensibles antes de la persistencia y soporte para borrado por el usuario.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.logger import get_logger

logger = get_logger("jessyca.memory.long_term")


class MemoryRecordType(StrEnum):
    """Tipos formales de memoria a largo plazo."""

    SESSION_MEMORY = "SESSION_MEMORY"          # Contexto conversacional y estado transitorio.
    SEMANTIC_MEMORY = "SEMANTIC_MEMORY"        # Conceptos, hechos y conocimiento estructurado.
    EPISODIC_MEMORY = "EPISODIC_MEMORY"        # Eventos pasados y resultados de tareas ejecutadas.
    USER_PREFERENCES = "USER_PREFERENCES"      # Preferencias explícitas de estilo y configuración.
    TASK_HISTORY = "TASK_HISTORY"              # Historial estructurado de tareas ejecutadas.
    SKILL_EXPERIENCE = "SKILL_EXPERIENCE"      # Métricas empíricas y rendimiento histórico de Skills.
    SYSTEM_KNOWLEDGE = "SYSTEM_KNOWLEDGE"      # Conocimiento inmutable del entorno operativo y hardware.


class MemorySensitivity(StrEnum):
    """Niveles de sensibilidad y privacidad del contenido almacenado."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


@dataclass
class LongTermMemoryRecord:
    """Registro canónico de memoria a largo plazo con procedencia y versionado."""

    id: str = field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:8]}")
    type: MemoryRecordType = MemoryRecordType.SEMANTIC_MEMORY
    content: str = ""
    source: str = "system"
    provenance: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    scope: str = "global"
    confidence: float = 1.0
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    expiration: float | None = None
    version: int = 1
    history: list[dict[str, Any]] = field(default_factory=list)

    def is_expired(self) -> bool:
        if self.expiration is None:
            return False
        return time.time() > self.expiration

    def compute_decayed_confidence(self, half_life_days: float = 30.0) -> float:
        """Calcula el decaimiento exponencial de confianza basado en la antigüedad del registro."""
        if self.type in (MemoryRecordType.SYSTEM_KNOWLEDGE, MemoryRecordType.USER_PREFERENCES):
            return self.confidence  # Las preferencias y el conocimiento del sistema no decaen automáticamente

        age_days = (time.time() - self.timestamp) / (24 * 3600)
        decay_factor = math.exp(-math.log(2) * (age_days / half_life_days))
        return max(0.1, round(self.confidence * decay_factor, 4))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LongTermMemoryEngine:
    """Motor de inteligencia, almacenamiento, recuperación y protección de memoria a largo plazo."""

    SECRET_PATTERNS = [
        re.compile(r"(password|secret|token|api_key|private_key)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?", re.IGNORECASE),
        re.compile(r"(ghp_[A-Za-z0-9_]{36}|ey[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*)"),
    ]

    INJECTION_PATTERNS = [
        re.compile(r"(\[INST\]|\[/INST\]|DAN jailbreak|ignore previous instructions)", re.IGNORECASE),
        re.compile(r"(security approved|permission granted to|bypass security pipeline)", re.IGNORECASE),
        re.compile(r"(always allow|always allow this|grant root access|authorization:\s*allowed|permission:\s*allow|override permission)", re.IGNORECASE),
    ]

    def __init__(
        self,
        storage_dir: str = "data/memory_long_term",
        emergency_stop: EmergencyStopManager | None = None,
    ) -> None:
        self.storage_dir = storage_dir
        self.emergency_stop = emergency_stop or get_emergency_stop_manager()
        self._disabled_categories: set[MemoryRecordType] = set()
        self._records: dict[str, LongTermMemoryRecord] = {}
        self._lock = threading.RLock()
        os.makedirs(self.storage_dir, exist_ok=True)
        self._load_all_records()

    def store_record(
        self,
        content: str,
        record_type: MemoryRecordType = MemoryRecordType.SEMANTIC_MEMORY,
        source: str = "system",
        provenance: dict[str, Any] | None = None,
        scope: str = "global",
        confidence: float = 1.0,
        sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL,
        ttl_seconds: float | None = None,
    ) -> LongTermMemoryRecord | None:
        """Almacena un nuevo registro de memoria sanitizado con procedencia y control de privacidad."""
        if record_type in self._disabled_categories:
            logger.info(f"[MEMORY] Categoría '{record_type.value}' desactivada por el usuario. Almacenamiento omitido.")
            return None

        # 1. Defensa contra Envenenamiento y Prompt Injection
        sanitized_content, is_poisoned = self._sanitize_and_detect_poisoning(content)
        if is_poisoned:
            logger.warning(f"[MEMORY POISONING DEFENSE] Se detectó e interceptó inyección maliciosa en memoria de origen '{source}'.")

        # 2. Redacción de Secretos Sensibles (Privacy by Design)
        redacted_content = self._redact_secrets(sanitized_content)

        expiration = (time.time() + ttl_seconds) if ttl_seconds is not None else None
        prov = provenance or {}
        prov.setdefault("stored_by", "LongTermMemoryEngine")
        prov.setdefault("initial_source", source)

        record = LongTermMemoryRecord(
            type=record_type,
            content=redacted_content,
            source=source,
            provenance=prov,
            scope=scope,
            confidence=max(0.0, min(1.0, confidence)),
            sensitivity=sensitivity,
            expiration=expiration,
        )

        with self._lock:
            self._records[record.id] = record
            self._persist_record(record)
            return record

    def retrieve_records(
        self,
        query: str,
        record_type: MemoryRecordType | None = None,
        scope: str | None = None,
        min_confidence: float = 0.3,
        apply_decay: bool = True,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Recupera memorias clasificadas por ranking multidimensional (relevancia, recencia, confianza, procedencia)."""
        results: list[dict[str, Any]] = []
        now = time.time()
        query_words = set(query.lower().split())

        with self._lock:
            for rec in self._records.values():
                # Filtrar expirados
                if rec.is_expired():
                    continue

                # Filtrar por categoría y alcance
                if record_type and rec.type != record_type:
                    continue
                if scope and rec.scope != scope and rec.scope != "global":
                    continue

                # Calcular confianza ajustada por decaimiento temporal
                effective_conf = rec.compute_decayed_confidence() if apply_decay else rec.confidence
                if effective_conf < min_confidence:
                    continue

                # Cálculo de relevancia léxica simple
                rec_words = set(rec.content.lower().split())
                matched = query_words.intersection(rec_words)
                relevance_score = len(matched) / max(1, len(query_words)) if query_words else 0.5

                # Cálculo de recencia (más reciente = score más alto)
                age_hours = (now - rec.timestamp) / 3600
                recency_score = max(0.1, 1.0 / (1.0 + age_hours * 0.05))

                # Ranking total ponderado
                total_rank = (relevance_score * 0.45) + (effective_conf * 0.35) + (recency_score * 0.20)

                results.append({
                    "record": rec,
                    "effective_confidence": effective_conf,
                    "relevance_score": round(relevance_score, 4),
                    "recency_score": round(recency_score, 4),
                    "total_rank": round(total_rank, 4),
                    "untrusted_data": True,  # Invariante: memoria es untrusted
                })

        results.sort(key=lambda x: x["total_rank"], reverse=True)
        return results[:limit]

    def update_record(self, record_id: str, new_content: str, reason: str = "user_correction") -> bool:
        """Actualiza un registro existente preservando el historial de versiones."""
        with self._lock:
            if record_id not in self._records:
                return False
            rec = self._records[record_id]
            # Guardar versión anterior en historial
            rec.history.append({
                "version": rec.version,
                "content": rec.content,
                "timestamp": rec.timestamp,
                "reason": reason,
            })
            rec.version += 1
            rec.content = self._redact_secrets(new_content)
            rec.timestamp = time.time()
            self._persist_record(rec)
            logger.info(f"[MEMORY] Registro '{record_id}' actualizado a versión {rec.version}.")
            return True

    def delete_record(self, record_id: str) -> bool:
        """Elimina permanentemente un registro de memoria por solicitud del usuario (GDPR)."""
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            fpath = os.path.join(self.storage_dir, f"{record_id}.json")
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    logger.error(f"Error eliminando archivo de memoria '{fpath}': {e}")
            logger.info(f"[MEMORY] Registro '{record_id}' eliminado permanentemente.")
            return True

    def disable_category(self, category: MemoryRecordType) -> None:
        """Desactiva una categoría de memoria a largo plazo."""
        self._disabled_categories.add(category)

    def enable_category(self, category: MemoryRecordType) -> None:
        """Habilita una categoría de memoria a largo plazo."""
        self._disabled_categories.discard(category)

    def _sanitize_and_detect_poisoning(self, content: str) -> tuple[str, bool]:
        sanitized = content
        poisoned = False
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(sanitized):
                poisoned = True
                sanitized = pattern.sub("[POISONING_ATTEMPT_NEUTRALIZED]", sanitized)
        return sanitized, poisoned

    def _redact_secrets(self, text: str) -> str:
        redacted = text
        for pattern in self.SECRET_PATTERNS:
            redacted = pattern.sub(r"\1: [REDACTED_SECRET]", redacted)
        return redacted

    def _persist_record(self, record: LongTermMemoryRecord) -> None:
        fpath = os.path.join(self.storage_dir, f"{record.id}.json")
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(record.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Error persistiendo memoria {record.id}: {e}")

    def _load_all_records(self) -> None:
        if not os.path.exists(self.storage_dir):
            return
        for fname in os.listdir(self.storage_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(self.storage_dir, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        d = json.load(f)
                    rec = LongTermMemoryRecord(
                        id=d["id"],
                        type=MemoryRecordType(d["type"]),
                        content=d["content"],
                        source=d.get("source", "system"),
                        provenance=d.get("provenance", {}),
                        timestamp=d.get("timestamp", time.time()),
                        scope=d.get("scope", "global"),
                        confidence=d.get("confidence", 1.0),
                        sensitivity=MemorySensitivity(d.get("sensitivity", MemorySensitivity.INTERNAL)),
                        expiration=d.get("expiration"),
                        version=d.get("version", 1),
                        history=d.get("history", []),
                    )
                    self._records[rec.id] = rec
                except Exception as e:
                    logger.error(f"Error cargando archivo de memoria {fname}: {e}")
