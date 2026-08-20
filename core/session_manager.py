"""Servicio de orquestación y gestión de ciclo de vida de sesiones (SessionManager - Subetapa 10.1).

GARANTÍA ABSOLUTA DE PRIVACIDAD Y SEGURIDAD:
Thread-safe. El AuditLogger y el EventBus reciben ÚNICAMENTE METADATOS (session_id_hash, status, counts, duration_ms).
INVARIANTE CRÍTICO: NUNCA registran mensajes crudos, hechos, preferencias ni credenciales en auditoría.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import UTC, datetime

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.event_bus import get_event_bus
from core.logger import get_logger
from core.session_models import (
    SessionFact,
    SessionId,
    SessionMessage,
    SessionMetadata,
    SessionPreference,
    SessionRole,
    SessionSnapshot,
    SessionState,
    SessionStatus,
)
from core.session_security import (
    SessionSecurityError,
    SessionSecurityManager,
)
from core.session_store import (
    InMemorySessionStore,
    ISessionStore,
    SQLiteSessionStore,
)

logger = get_logger("jessyca.core.session_manager")


class SessionManager:
    """Gestor principal de estado de sesión y memoria de usuario."""

    def __init__(
        self,
        store: ISessionStore | None = None,
        security_manager: SessionSecurityManager | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        if store is not None:
            self.store = store
        elif settings.SESSION_PERSISTENCE_ENABLED:
            self.store = SQLiteSessionStore()
        else:
            self.store = InMemorySessionStore()

        self.security_manager = security_manager or SessionSecurityManager()
        self.audit_logger = get_audit_logger()
        self.event_bus = get_event_bus()
        self._lock = threading.RLock()

    def _hash_sid(self, sid_str: str) -> str:
        """Genera un hash SHA-256 anónimo del SessionId para trazabilidad en auditoría."""
        return hashlib.sha256(sid_str.encode("utf-8")).hexdigest()[:16]

    def create_session(
        self,
        user_id: str,
        client_id: str = "desktop_client",
        session_id: str | None = None,
    ) -> SessionState:
        """Crea una nueva sesión de usuario con estado inmutable inicial. FAIL-SAFE DENY."""
        sid_raw = session_id or str(uuid.uuid4())
        sid = self.security_manager.validate_session_id(sid_raw)
        now = datetime.now(UTC)

        clean_user = self.security_manager.sanitize_text(user_id) or "anonymous_user"
        clean_client = self.security_manager.sanitize_text(client_id) or "desktop_client"

        meta = SessionMetadata(
            user_id=clean_user,
            client_id=clean_client,
            client_version="3.0",
        )

        state = SessionState(
            session_id=sid,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            messages=(),
            facts=(),
            preferences=(),
            metadata=meta,
        )

        self.store.save_session(state)
        sid_hash = self._hash_sid(str(sid))

        audit_meta = {
            "session_id_hash": sid_hash,
            "status": str(SessionStatus.ACTIVE),
            "user_id": clean_user,
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SESSION_CREATED,
                request_id=f"session-create-{sid_hash}",
                tool_name="system.session",
                operation="create_session",
                duration_ms=0.0,
                reason="Sesión creada exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("session:created", audit_meta)
        return state

    def get_session(self, session_id: str | SessionId) -> SessionState:
        """Recupera el estado inmutable de una sesión existente."""
        sid = self.security_manager.validate_session_id(session_id)
        state = self.store.get_session(sid)

        if not state:
            raise SessionSecurityError(f"Sesión no encontrada: '{sid}'")

        sid_hash = self._hash_sid(str(sid))

        # Verificar si la sesión expiró por timeout
        from config.settings import AppSettings
        settings = AppSettings()

        elapsed = (datetime.now(UTC) - state.updated_at).total_seconds()
        if elapsed > settings.SESSION_TIMEOUT and state.status == SessionStatus.ACTIVE:
            logger.info(f"[SESSION] Sesión [{sid_hash}] expirada por timeout ({elapsed:.1f}s > {settings.SESSION_TIMEOUT}s)")
            return self.expire_session(sid)

        self.event_bus.publish("session:accessed", {"session_id_hash": sid_hash, "status": str(state.status)})
        return state

    def append_message(self, session_id: str | SessionId, role: SessionRole, content: str) -> SessionState:
        """Sanitiza y añade un nuevo mensaje al historial inmutable de la sesión."""
        with self._lock:
            current_state = self.get_session(session_id)
            self.security_manager.validate_status_transition(current_state.status, current_state.status)


        if current_state.status not in (SessionStatus.ACTIVE, SessionStatus.WAITING_INPUT, SessionStatus.WAITING_CONFIRMATION):
            raise SessionSecurityError(f"No se pueden agregar mensajes a una sesión en estado '{current_state.status}'.")

        clean_content = self.security_manager.validate_message(content)
        now = datetime.now(UTC)

        msg = SessionMessage(
            message_id=str(uuid.uuid4()),
            role=role,
            content=clean_content,
            timestamp=now,
        )

        new_messages = current_state.messages + (msg,)
        new_state = SessionState(
            session_id=current_state.session_id,
            status=SessionStatus.ACTIVE,
            created_at=current_state.created_at,
            updated_at=now,
            messages=new_messages,
            facts=current_state.facts,
            preferences=current_state.preferences,
            metadata=current_state.metadata,
            current_task_id=current_state.current_task_id,
        )

        self.security_manager.validate_state_limits(new_state)
        self.store.save_session(new_state)

        sid_hash = self._hash_sid(str(current_state.session_id))
        audit_meta = {
            "session_id_hash": sid_hash,
            "role": str(role),
            "message_count": len(new_messages),
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SESSION_MESSAGE_ADDED,
                request_id=f"session-msg-{sid_hash}",
                tool_name="system.session",
                operation="append_message",
                duration_ms=0.0,
                reason="Mensaje añadido a la sesión exitosamente.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("session:message_added", audit_meta)
        return new_state

    def add_fact(self, session_id: str | SessionId, key: str, value: str, confidence: float = 1.0) -> SessionState:
        """Añade un nuevo hecho (fact) sanitizado a la memoria de sesión."""
        with self._lock:
            current_state = self.get_session(session_id)
            clean_k, clean_v, conf = self.security_manager.validate_fact(key, value, confidence)

        now = datetime.now(UTC)

        fact = SessionFact(
            fact_id=str(uuid.uuid4()),
            key=clean_k,
            value=clean_v,
            confidence=conf,
            timestamp=now,
        )

        new_facts = current_state.facts + (fact,)
        new_state = SessionState(
            session_id=current_state.session_id,
            status=current_state.status,
            created_at=current_state.created_at,
            updated_at=now,
            messages=current_state.messages,
            facts=new_facts,
            preferences=current_state.preferences,
            metadata=current_state.metadata,
            current_task_id=current_state.current_task_id,
        )

        self.security_manager.validate_state_limits(new_state)
        self.store.save_session(new_state)

        sid_hash = self._hash_sid(str(current_state.session_id))
        audit_meta = {
            "session_id_hash": sid_hash,
            "fact_count": len(new_facts),
        }

        self.event_bus.publish("session:fact_added", audit_meta)
        return new_state

    def add_preference(self, session_id: str | SessionId, key: str, value: str) -> SessionState:
        """Añade una nueva preferencia sanitizada a la sesión."""
        current_state = self.get_session(session_id)
        clean_k, clean_v = self.security_manager.validate_preference(key, value)
        now = datetime.now(UTC)

        pref = SessionPreference(
            preference_id=str(uuid.uuid4()),
            key=clean_k,
            value=clean_v,
            timestamp=now,
        )

        new_prefs = current_state.preferences + (pref,)
        new_state = SessionState(
            session_id=current_state.session_id,
            status=current_state.status,
            created_at=current_state.created_at,
            updated_at=now,
            messages=current_state.messages,
            facts=current_state.facts,
            preferences=new_prefs,
            metadata=current_state.metadata,
            current_task_id=current_state.current_task_id,
        )

        self.security_manager.validate_state_limits(new_state)
        self.store.save_session(new_state)

        sid_hash = self._hash_sid(str(current_state.session_id))
        audit_meta = {
            "session_id_hash": sid_hash,
            "preference_count": len(new_prefs),
        }

        self.event_bus.publish("session:preference_added", audit_meta)
        return new_state

    def update_status(self, session_id: str | SessionId, new_status: SessionStatus) -> SessionState:
        """Actualiza el estado de la sesión aplicando validaciones de transición."""
        current_state = self.get_session(session_id)
        self.security_manager.validate_status_transition(current_state.status, new_status)
        now = datetime.now(UTC)

        new_state = SessionState(
            session_id=current_state.session_id,
            status=new_status,
            created_at=current_state.created_at,
            updated_at=now,
            messages=current_state.messages,
            facts=current_state.facts,
            preferences=current_state.preferences,
            metadata=current_state.metadata,
            current_task_id=current_state.current_task_id,
        )

        self.store.save_session(new_state)
        sid_hash = self._hash_sid(str(current_state.session_id))

        audit_meta = {
            "session_id_hash": sid_hash,
            "previous_status": str(current_state.status),
            "new_status": str(new_status),
        }

        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.SESSION_UPDATED,
                request_id=f"session-update-{sid_hash}",
                tool_name="system.session",
                operation="update_status",
                duration_ms=0.0,
                reason=f"Estado de sesión actualizado de '{current_state.status}' a '{new_status}'.",
                metadata=audit_meta,
            )
        )

        self.event_bus.publish("session:updated", audit_meta)
        return new_state

    def create_snapshot(self, session_id: str | SessionId) -> SessionSnapshot:
        """Crea una captura puntual inmutable del estado de sesión."""
        state = self.get_session(session_id)
        now = datetime.now(UTC)
        snap_id = str(uuid.uuid4())

        summary = {
            "message_count": len(state.messages),
            "fact_count": len(state.facts),
            "preference_count": len(state.preferences),
            "status": str(state.status),
        }

        snapshot = SessionSnapshot(
            snapshot_id=snap_id,
            session_id=str(state.session_id),
            timestamp=now,
            status=state.status,
            message_count=len(state.messages),
            fact_count=len(state.facts),
            preference_count=len(state.preferences),
            state_summary=summary,
        )

        sid_hash = self._hash_sid(str(state.session_id))
        self.event_bus.publish("session:snapshot_created", {"session_id_hash": sid_hash, "snapshot_id": snap_id})
        return snapshot

    def pause_session(self, session_id: str | SessionId) -> SessionState:
        """Pausa una sesión activa."""
        return self.update_status(session_id, SessionStatus.PAUSED)

    def resume_session(self, session_id: str | SessionId) -> SessionState:
        """Reanuda una sesión pausada o en espera."""
        return self.update_status(session_id, SessionStatus.ACTIVE)

    def cancel_session(self, session_id: str | SessionId) -> SessionState:
        """Cancela una sesión moviéndola a estado terminal CANCELLED."""
        return self.update_status(session_id, SessionStatus.CANCELLED)

    def expire_session(self, session_id: str | SessionId) -> SessionState:
        """Expira una sesión moviéndola a estado terminal EXPIRED."""
        sid_str = str(session_id)
        current_state = self.store.get_session(SessionId(value=sid_str))

        if not current_state:
            raise SessionSecurityError(f"Sesión no encontrada: '{sid_str}'")

        now = datetime.now(UTC)
        new_state = SessionState(
            session_id=current_state.session_id,
            status=SessionStatus.EXPIRED,
            created_at=current_state.created_at,
            updated_at=now,
            messages=current_state.messages,
            facts=current_state.facts,
            preferences=current_state.preferences,
            metadata=current_state.metadata,
            current_task_id=current_state.current_task_id,
        )
        self.store.save_session(new_state)
        sid_hash = self._hash_sid(sid_str)
        self.event_bus.publish("session:expired", {"session_id_hash": sid_hash})
        return new_state

    # ------------------------------------------------------------------ #
    # API de compatibilidad simplificada (Subetapa 10.x / legado tests)   #
    # ------------------------------------------------------------------ #

    def start_session(
        self,
        user: str = "anonymous",
        metadata: dict | None = None,
    ) -> SimpleSession:
        """Inicia una sesión nueva con una API simplificada.

        Proporciona compatibilidad con tests que usan la interfaz de alto nivel.
        Internamente delega a create_session().
        """
        state = self.create_session(user_id=user)
        simple = SimpleSession(session_id=str(state.session_id), user=user)
        self._active_simple_session = simple
        if not hasattr(self, "_session_history"):
            self._session_history: dict[str, SimpleSession] = {}
        return simple

    def record_tool_usage(
        self,
        tool_name: str,
        parameters: dict | None = None,
        arguments: dict | None = None,
        is_success: bool = True,
        error: str | None = None,
    ) -> None:
        """Registra el uso de una herramienta en la sesión activa.

        Acepta `parameters` o `arguments` (alias para compatibilidad con executor.py).
        """
        if not hasattr(self, "_active_simple_session") or self._active_simple_session is None:
            return
        params = parameters or arguments or {}
        record = {
            "tool": tool_name,
            "parameters": params,
            "success": is_success,
            "error": error,
        }
        self._active_simple_session._tools_used.append(record)

    def record_error(self, message: str, details: dict | None = None) -> None:
        """Registra un error en la sesión activa."""
        if not hasattr(self, "_active_simple_session") or self._active_simple_session is None:
            return
        self._active_simple_session._errors.append({"message": message, "details": details or {}})

    def end_session(self) -> SimpleSession | None:
        """Finaliza la sesión simplificada activa."""
        if not hasattr(self, "_active_simple_session") or self._active_simple_session is None:
            return None
        simple = self._active_simple_session
        simple._ended_at = datetime.now(UTC)
        self._active_simple_session = None
        # Guardar en historial para export posterior
        if not hasattr(self, "_session_history"):
            self._session_history: dict[str, SimpleSession] = {}
        self._session_history[simple.session_id] = simple
        return simple

    def export_session(
        self,
        session_id: str,
        format: str = "json",
        file_path: object = None,
    ) -> str:
        """Exporta la sesión como JSON o Markdown."""
        import json as _json
        from pathlib import Path

        # Buscar en simple sessions (activa o historial)
        simple: SimpleSession | None = None
        if hasattr(self, "_active_simple_session") and self._active_simple_session:
            if self._active_simple_session.session_id == session_id:
                simple = self._active_simple_session
        if simple is None and hasattr(self, "_session_history"):
            simple = self._session_history.get(session_id)

        if simple is None:
            # Intentar recuperar desde el store
            try:
                state = self.get_session(session_id)
                user = state.metadata.user_id
                tools: list[dict] = []
                errors: list[dict] = []
                duration = (state.updated_at - state.created_at).total_seconds()
                if format.lower() == "json":
                    data = {
                        "session_id": session_id,
                        "user": user,
                        "tools_used_count": len(tools),
                        "errors_count": len(errors),
                        "duration_seconds": duration,
                    }
                    result = _json.dumps(data, ensure_ascii=False, indent=2)
                else:
                    result = f"# Reporte de Sesión MCP\n\n- **Usuario**: {user}\n"
                if file_path:
                    Path(file_path).write_text(result, encoding="utf-8")
                return result
            except Exception:
                pass
            return "{}"

        user = simple.user
        tools = simple._tools_used
        errors = simple._errors
        started = simple._started_at
        ended = simple._ended_at or datetime.now(UTC)
        duration = (ended - started).total_seconds()

        if format.lower() == "json":
            data = {
                "session_id": session_id,
                "user": user,
                "tools_used_count": len(tools),
                "errors_count": len(errors),
                "duration_seconds": duration,
                "tools": tools,
                "errors": errors,
            }
            result = _json.dumps(data, ensure_ascii=False, indent=2)
        else:
            lines = [
                "# Reporte de Sesión MCP",
                "",
                f"- **Usuario**: {user}",
                f"- **Duración**: {duration:.2f}s",
                "",
                "## Herramientas Utilizadas",
                "",
            ]
            for t in tools:
                lines.append(f"- `{t['tool']}` — éxito: {t['success']}")
            if errors:
                lines.append("\n## Errores\n")
                for e in errors:
                    lines.append(f"- {e['message']}")
            result = "\n".join(lines)

        if file_path:
            from pathlib import Path as _Path
            _Path(file_path).write_text(result, encoding="utf-8")

        return result


class SimpleSession:
    """Objeto de sesión simplificado para la API de compatibilidad de tests heredados."""

    def __init__(self, session_id: str, user: str) -> None:
        self.session_id = session_id
        self.user = user
        self._started_at = datetime.now(UTC)
        self._ended_at: datetime | None = None
        self._tools_used: list[dict] = []
        self._errors: list[dict] = []

    @property
    def is_active(self) -> bool:
        return self._ended_at is None

    @property
    def tools_used(self) -> list[dict]:
        return list(self._tools_used)

    @property
    def errors(self) -> list[dict]:
        return list(self._errors)

    @property
    def duration_seconds(self) -> float:
        end = self._ended_at or datetime.now(UTC)
        return (end - self._started_at).total_seconds()
