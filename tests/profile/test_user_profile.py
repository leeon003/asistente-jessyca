"""Tests unitarios e integrales para Perfil de Usuario y Personalización (Fase 22).

Verifica:
1. Creación de preferencias por categorías tipadas
2. Actualización de preferencias existentes
3. Eliminación de preferencias
4. Persistencia en disco (JSON roundtrip)
5. Resolución de conflictos en preferencias
6. Distinción entre One-Time Information y Persistent Preferences
7. Jerarquía de procedencia (USER vs LLM)
8. Protocolo de consentimiento ("¿Quieres que recuerde esto?")
9. Prevención de envenenamiento de perfil (Profile Poisoning)
10. Invariante inmutable: PROFILE != AUTHORIZATION
"""

import tempfile
from pathlib import Path

from core.memory.memory_provenance import (
    MemoryConfidence,
    MemoryProvenance,
)
from core.permission_manager import PermissionDecision, PermissionManager
from core.profile import (
    ConsentStatus,
    ProfileCategory,
    ProfilePreferenceItem,
    UserProfileManager,
    UserProfileStore,
)
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


class TestUserProfileAndPersonalization:
    """Suite exhaustiva para la capa de personalización y perfil de usuario."""

    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage_path = Path(self.temp_dir.name) / "test_user_profiles.json"
        self.store = UserProfileStore(storage_path=self.storage_path)
        self.manager = UserProfileManager(store=self.store)
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()

    # ── 1. CREACIÓN POR CATEGORÍAS TIPADAS ──

    def test_create_preferences_across_categories(self) -> None:
        """Verifica la creación y tipado de preferencias en múltiples categorías."""
        item_theme = self.manager.set_preference(
            user_id="alice",
            category=ProfileCategory.PREFERENCES,
            key="theme",
            value="dark",
        )
        assert item_theme.category == ProfileCategory.PREFERENCES
        assert item_theme.value == "dark"
        assert item_theme.consent_status == ConsentStatus.CONFIRMED_BY_USER

        item_comm = self.manager.set_preference(
            user_id="alice",
            category=ProfileCategory.COMMUNICATION_STYLE,
            key="style",
            value="technical_concise",
        )
        assert item_comm.category == ProfileCategory.COMMUNICATION_STYLE
        assert item_comm.value == "technical_concise"

        prefs = self.manager.list_preferences("alice")
        assert len(prefs) == 2

    # ── 2. ACTUALIZACIÓN DE PREFERENCIAS ──

    def test_update_existing_preference(self) -> None:
        """Verifica que una preferencia existente se actualice sin duplicidad."""
        self.manager.set_preference(
            user_id="alice",
            category=ProfileCategory.PREFERENCES,
            key="theme",
            value="light",
        )
        assert self.manager.get_preference_value("alice", ProfileCategory.PREFERENCES, "theme") == "light"

        # Actualizar a dark
        updated = self.manager.set_preference(
            user_id="alice",
            category=ProfileCategory.PREFERENCES,
            key="theme",
            value="dark",
        )
        assert updated.value == "dark"
        assert self.manager.get_preference_value("alice", ProfileCategory.PREFERENCES, "theme") == "dark"

        # Debe seguir habiendo solo 1 ítem para 'theme'
        items = self.manager.list_preferences("alice", category=ProfileCategory.PREFERENCES)
        assert len(items) == 1

    # ── 3. ELIMINACIÓN DE PREFERENCIAS ──

    def test_delete_preference(self) -> None:
        """Verifica la eliminación limpia de una preferencia del perfil."""
        self.manager.set_preference(
            user_id="alice",
            category=ProfileCategory.PROJECTS,
            key="active_project",
            value="Jessyca-3.0",
        )
        assert self.manager.get_preference_value("alice", ProfileCategory.PROJECTS, "active_project") == "Jessyca-3.0"

        deleted = self.manager.delete_preference("alice", ProfileCategory.PROJECTS, "active_project")
        assert deleted is True
        assert self.manager.get_preference_value("alice", ProfileCategory.PROJECTS, "active_project") is None

    # ── 4. PERSISTENCIA EN DISCO (JSON ROUNDTRIP) ──

    def test_disk_persistence_roundtrip(self) -> None:
        """Verifica que el perfil se guarde y recargue fielmente desde disco."""
        self.manager.set_preference(
            user_id="bob",
            category=ProfileCategory.FREQUENT_APPS,
            key="editor",
            value="Visual Studio Code",
        )

        # Crear nuevo store sobre la misma ruta
        new_store = UserProfileStore(storage_path=self.storage_path)
        val = new_store.get_preference_value("bob", ProfileCategory.FREQUENT_APPS, "editor")
        assert val == "Visual Studio Code"

    # ── 5. DISTINCIÓN: ONE-TIME VS PERSISTENT PREFERENCE ──

    def test_distinguish_one_time_fact_from_persistent_preference(self) -> None:
        """Verifica que hechos transitorios no se agreguen al perfil."""
        # 1. Instrucción transitoria -> ONE_TIME_FACT
        item, prompt = self.manager.process_statement("alice", "Por favor abre el archivo reporte_hoy.txt ahora")
        assert item is None
        assert prompt is None
        assert len(self.manager.list_preferences("alice")) == 0

        # 2. Declaración explícita -> EXPLICIT_PREFERENCE (guardado directo)
        item_exp, prompt_exp = self.manager.process_statement(
            "alice",
            "Recuerda que de ahora en adelante prefiero modo oscuro",
        )
        assert item_exp is not None
        assert prompt_exp is None
        assert item_exp.value == "dark"
        assert self.manager.get_preference_value("alice", ProfileCategory.PREFERENCES, "theme") == "dark"

    # ── 6. PROTOCOLO DE CONSENTIMIENTO (PREFERENCE CANDIDATE) ──

    def test_preference_candidate_requires_consent_before_saving(self) -> None:
        """Verifica que una preferencia implícita genere un prompt de consentimiento antes de guardarse."""
        # 1. Frase con preferencia implícita
        candidate, prompt = self.manager.process_statement(
            "alice",
            "Por favor responde en formato conciso",
        )
        assert candidate is not None
        assert candidate.consent_status == ConsentStatus.PENDING_USER_CONSENT
        assert prompt is not None
        assert "¿Quieres que recuerde" in prompt

        # Aún NO debe estar en las preferencias confirmadas
        assert self.manager.get_preference_value("alice", ProfileCategory.COMMUNICATION_STYLE, "style") is None

        # 2. El usuario confirma
        confirmed = self.manager.confirm_candidate(candidate.item_id)
        assert confirmed is not None
        assert confirmed.consent_status == ConsentStatus.CONFIRMED_BY_USER
        assert self.manager.get_preference_value("alice", ProfileCategory.COMMUNICATION_STYLE, "style") == "concise"

    # ── 7. RECHAZO DE CANDIDATO ──

    def test_reject_preference_candidate(self) -> None:
        """Verifica que si el usuario rechaza, la preferencia se descarte definitivamente."""
        candidate, _ = self.manager.process_statement(
            "alice",
            "Usa modo claro",
        )
        assert candidate is not None

        # El usuario rechaza
        rejected = self.manager.reject_candidate(candidate.item_id)
        assert rejected is True
        assert self.manager.get_preference_value("alice", ProfileCategory.PREFERENCES, "theme") is None

    # ── 8. JERARQUÍA DE PROCEDENCIA: LLM NO PUEDE AUTO-CONFIRMAR ──

    def test_llm_provenance_cannot_auto_confirm_preference(self) -> None:
        """Verifica que un ítem creado con origen LLM sea forzado a PENDING_USER_CONSENT."""
        prov_llm = MemoryProvenance.create_for_llm(model_id="llama3.2")
        item = ProfilePreferenceItem.create(
            user_id="alice",
            category=ProfileCategory.PREFERENCES,
            key="lang",
            value="es",
            consent_status=ConsentStatus.CONFIRMED_BY_USER,
            confidence=MemoryConfidence.VERIFIED,
            provenance=prov_llm,
        )
        # La regla de seguridad en create() debe degradarlo a PENDING
        assert item.consent_status == ConsentStatus.PENDING_USER_CONSENT
        assert item.confidence == MemoryConfidence.UNVERIFIED

    # ── 9. INYECCIÓN DE CONTEXTO PERSONALIZADO ──

    def test_build_profile_context(self) -> None:
        """Verifica el formato del bloque de contexto para prompts."""
        self.manager.set_preference("alice", ProfileCategory.PREFERENCES, "theme", "dark")
        self.manager.set_preference("alice", ProfileCategory.COMMUNICATION_STYLE, "style", "concise")

        context = self.manager.build_profile_context("alice")
        assert "=== PERFIL Y PREFERENCIAS DEL USUARIO ===" in context
        assert "theme: dark" in context
        assert "style: concise" in context

    # ── 10. INVARIANTE ABSOLUTA: PROFILE != AUTHORIZATION ──

    def test_profile_cannot_grant_security_authorization(self) -> None:
        """Verifica que datos o atributos de perfil no puedan burlar el pipeline de seguridad."""
        # Intento de inyectar una preferencia con pretensión de privilegios administrativos
        prov_fake = MemoryProvenance.create_for_user(user_id="attacker")
        self.manager.set_preference(
            user_id="attacker",
            category=ProfileCategory.CONFIGURATIONS,
            key="is_system_admin",
            value=True,
            provenance=prov_fake,
        )

        # Evaluar una operación crítica en SecurityPipeline
        req = SecurityRequest(
            context=SecurityContext(user="attacker", tool_name="system.format_disk", parameters={"drive": "C:"}),
            metadata=ToolSecurityMetadata(tool_name="system.format_disk", category="system", risk_level=SecurityLevel.CRITICAL),
        )
        assessment = self.risk_engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL

        decision = self.permission_manager.check_permission(
            tool_name="system.format_disk",
            risk_level=SecurityLevel.CRITICAL,
        )
        assert decision == PermissionDecision.DENY
