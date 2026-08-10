"""Recuperación desacoplada y determinista de memoria de sesión (MemoryRetriever - Subetapa 10.2).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Protocolo abstracto IMemoryRetriever. Implementaciones SessionMemoryRetriever y FakeMemoryRetriever.
Lectura pura en modo solo lectura (READ-ONLY) sin ejecución de herramientas ni comandos del sistema.
"""

from __future__ import annotations

from typing import Protocol

from core.context_models import (
    ContextItem,
    ContextQuery,
    ContextSource,
)
from core.logger import get_logger
from core.session_manager import SessionManager

logger = get_logger("jessyca.core.memory_retriever")


class IMemoryRetriever(Protocol):
    """Protocolo abstracto para la recuperación de elementos de memoria de sesión."""

    def retrieve_context_items(self, query: ContextQuery) -> tuple[ContextItem, ...]:
        """Recupera elementos de contexto acotados y deterministas."""
        ...


class SessionMemoryRetriever:
    """Recuperador real seguro de memoria a partir de SessionManager."""

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self.session_manager = session_manager or SessionManager()

    def retrieve_context_items(self, query: ContextQuery) -> tuple[ContextItem, ...]:
        """Recupera mensajes, hechos, preferencias y metadatos desde SessionManager."""
        try:
            state = self.session_manager.get_session(query.session_id)
        except Exception as err:
            logger.warning(f"[MEMORY RETRIEVER] Error al recuperar sesión '{query.session_id}': {err}")
            return ()

        items: list[ContextItem] = []

        # 1. Estado de sesión y metadatos (Prioridad 1)
        state_item = ContextItem(
            item_id=f"state-{state.session_id}",
            source=ContextSource.SESSION_STATE,
            key="session_status",
            content=f"Status: {state.status}, Created: {state.created_at.isoformat()}",
            priority=1,
            timestamp=state.updated_at,
            metadata={"user_id": state.metadata.user_id, "client_id": state.metadata.client_id},
        )
        items.append(state_item)

        # 2. Mensajes recientes (Prioridad 2)
        if query.include_messages and state.messages:
            recent_msgs = state.messages[-query.max_messages :]
            for idx, msg in enumerate(recent_msgs):
                items.append(
                    ContextItem(
                        item_id=f"msg-{msg.message_id}",
                        source=ContextSource.RECENT_MESSAGES,
                        key=f"msg_{idx}_{msg.role}",
                        content=f"[{msg.role}] {msg.content}",
                        priority=2,
                        timestamp=msg.timestamp,
                        metadata={"role": str(msg.role)},
                    )
                )

        # 3. Preferencias del usuario (Prioridad 3)
        if query.include_preferences and state.preferences:
            prefs = state.preferences[-query.max_preferences :]
            for pref in prefs:
                items.append(
                    ContextItem(
                        item_id=f"pref-{pref.preference_id}",
                        source=ContextSource.PREFERENCES,
                        key=pref.key,
                        content=f"{pref.key} = {pref.value}",
                        priority=3,
                        timestamp=pref.timestamp,
                        metadata={},
                    )
                )

        # 4. Hechos de memoria (Facts - Prioridad 4)
        if query.include_facts and state.facts:
            facts = state.facts[-query.max_facts :]
            for fact in facts:
                items.append(
                    ContextItem(
                        item_id=f"fact-{fact.fact_id}",
                        source=ContextSource.FACTS,
                        key=fact.key,
                        content=f"{fact.key}: {fact.value} (conf: {fact.confidence})",
                        priority=4,
                        timestamp=fact.timestamp,
                        metadata={"confidence": fact.confidence},
                    )
                )

        # 5. Filtrado opcional si se especificó query_filter
        if query.query_filter:
            flt = query.query_filter.lower()
            items = [item for item in items if flt in item.key.lower() or flt in item.content.lower()]

        return tuple(items)


class FakeMemoryRetriever:
    """Recuperador sintético in-memory para pruebas unitarias deterministas."""

    def __init__(self, preset_items: tuple[ContextItem, ...] = ()) -> None:
        self.preset_items = preset_items

    def retrieve_context_items(self, query: ContextQuery) -> tuple[ContextItem, ...]:
        return self.preset_items
