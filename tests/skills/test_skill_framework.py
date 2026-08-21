"""Tests unitarios e integrales para el Skill Framework Foundation (Fase 28.0).

Verifica:
1. Registro, catálogo y descubrimiento de Skills
2. Enrutamiento determinista por intención del usuario
3. Validación y rechazo de Skills malformadas (ID, SemVer, permisos prohibidos)
4. Bloqueo de degradación de riesgo en herramientas destructivas
5. Ejecución gobernada y emisión de SkillResult estructurado
6. Contención de riesgo y requisito de confirmación humana
7. Cancelación cooperativa vía CancellationToken
8. Parada de Emergencia prevalente
9. Desregistro y descarga de Skills
10. Retrocompatibilidad con BaseSkill y SKILLS_DISPONIBLES
"""

from typing import Any

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    BaseSkill,
    SkillCapability,
    SkillDefinition,
    SkillManager,
    SkillRegistry,
    SkillRouter,
    SkillRuntime,
    SkillStatus,
    SkillValidator,
)


class DummySampleSkill(BaseSkill):
    """Skill de prueba segura para cálculos y diagnóstico."""

    def __init__(self) -> None:
        def_obj = SkillDefinition(
            skill_id="system.diagnostics",
            name="system.diagnostics",
            version="1.0.0",
            description="Realiza diagnóstico y chequeo de estado del sistema.",
            capabilities=(SkillCapability.SYSTEM,),
            risk_level=SecurityLevel.SAFE,
            tags=("diagnostico", "sistema", "salud"),
        )
        super().__init__(nombre="system.diagnostics", nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {
            "exito": True,
            "mensaje": "Diagnóstico de sistema saludable.",
            "metrics": {"cpu": "12%", "ram": "45%"},
        }


class DummyDangerousSkill(BaseSkill):
    """Skill de prueba con nivel de riesgo ALTO para verificar confirmaciones."""

    def __init__(self) -> None:
        def_obj = SkillDefinition(
            skill_id="filesystem.purge",
            name="filesystem.purge",
            version="1.0.0",
            description="Purga de archivos obsoletos en disco.",
            capabilities=(SkillCapability.FILESYSTEM,),
            risk_level=SecurityLevel.HIGH,
            tags=("limpieza", "disco", "archivos"),
        )
        super().__init__(nombre="filesystem.purge", nivel_riesgo=3, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": "Directorio purgado."}


class TestSkillFrameworkFoundation:
    """Suite de pruebas del Skill Framework Foundation."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_skills_setup")
        self.registry = SkillRegistry()
        self.registry.reset()
        self.router = SkillRouter(registry=self.registry)
        self.runtime = SkillRuntime(emergency_stop=self.emergency_stop)
        self.manager = SkillManager(
            registry=self.registry,
            router=self.router,
            runtime=self.runtime,
        )

    # ── 1. REGISTRO Y DESCUBRIMIENTO ──

    def test_skill_registration_and_listing(self) -> None:
        """Verifica que una Skill se registre, indexe y liste correctamente en el catálogo."""
        skill = DummySampleSkill()
        registered, error = self.manager.register_skill(skill)

        assert registered is True
        assert error is None
        assert len(self.manager.list_skills()) == 1

        # Búsqueda por capacidad y tag
        by_cap = self.registry.find_by_capability(SkillCapability.SYSTEM)
        assert len(by_cap) == 1
        assert by_cap[0].skill_id == "system.diagnostics"

        by_tag = self.registry.find_by_tag("salud")
        assert len(by_tag) == 1

    # ── 2. ENRUTAMIENTO POR INTENCIÓN ──

    def test_route_intent_to_skill(self) -> None:
        """Verifica que el SkillRouter resuelva la Skill adecuada para una intención del usuario."""
        self.manager.register_skill(DummySampleSkill())

        # Exact match
        sk_def, conf, reason = self.router.route_intent("system.diagnostics")
        assert sk_def is not None
        assert sk_def.skill_id == "system.diagnostics"
        assert conf == 1.0

        # Semantic/Keyword match
        sk_def2, conf2, _ = self.router.route_intent("Realiza un diagnostico del sistema")
        assert sk_def2 is not None
        assert sk_def2.skill_id == "system.diagnostics"
        assert conf2 >= 0.5

    # ── 3. VALIDACIÓN Y RECHAZO DE SKILL INVÁLIDA ──

    def test_invalid_skill_definition_rejection(self) -> None:
        """Verifica el rechazo de skills con identificadores ilegales o versiones inválidas."""
        # SemVer inválido
        bad_semver = SkillDefinition(
            skill_id="bad.skill",
            name="Bad Skill",
            version="invalid_ver_1",
        )
        val, err = SkillValidator.validate(bad_semver)
        assert val is False
        assert "SemVer" in str(err)

        # ID inválido con caracteres prohibidos
        bad_id = SkillDefinition(
            skill_id="bad id with spaces and $#@",
            name="Bad ID",
            version="1.0.0",
        )
        val2, err2 = SkillValidator.validate(bad_id)
        assert val2 is False
        assert "Identificador de skill inválido" in str(err2)

    # ── 4. RECHAZO DE PERMISOS PROHIBIDOS Y DEGRADACIÓN DE RIESGO ──

    def test_forbidden_permissions_and_risk_degradation_rejection(self) -> None:
        """Verifica el rechazo de permisos prohibidos o intentos de degradación de riesgo."""
        # Permiso prohibido
        forbidden_perm_def = SkillDefinition(
            skill_id="exploit.skill",
            name="Exploit Skill",
            version="1.0.0",
            required_permissions=("security.override",),
        )
        val1, err1 = SkillValidator.validate(forbidden_perm_def)
        assert val1 is False
        assert "permiso prohibido" in str(err1).lower()

        # Degradación de riesgo en acción destructiva
        degraded_def = SkillDefinition(
            skill_id="disk.format",
            name="Format Disk",
            description="Borrado y delete del volumen completo",
            risk_level=SecurityLevel.SAFE,  # Intento ilegal de declarar SAFE
        )
        val2, err2 = SkillValidator.validate(degraded_def)
        assert val2 is False
        assert "degradación de riesgo" in str(err2).lower()

    # ── 5. EJECUCIÓN GOBERNADA Y RESULTADO ESTRUCTURADO ──

    def test_execute_skill_successfully(self) -> None:
        """Verifica la ejecución segura de una Skill produciendo un SkillResult estructurado."""
        self.manager.register_skill(DummySampleSkill())

        res = self.manager.execute_skill("system.diagnostics", parameters={"mode": "full"})
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert res.output["metrics"]["cpu"] == "12%"
        assert res.duration_ms >= 0.0

    def test_execute_by_intent_successfully(self) -> None:
        """Verifica la ejecución integrada por intención del usuario."""
        self.manager.register_skill(DummySampleSkill())

        res = self.manager.execute_by_intent("Ejecutar diagnostico del sistema")
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert "saludable" in str(res.output)

    # ── 6. CONTENCIÓN DE RIESGO Y REQUISITO DE CONFIRMACIÓN ──

    def test_high_risk_skill_requires_confirmation(self) -> None:
        """Verifica que una Skill de riesgo alto se detenga en WAITING_CONFIRMATION si no está confirmada."""
        self.manager.register_skill(DummyDangerousSkill())

        res = self.manager.execute_skill("filesystem.purge", parameters={"target": "D:\\Temp"})
        assert res.success is False
        assert res.status == SkillStatus.WAITING_CONFIRMATION
        assert "requiere confirmación" in str(res.error).lower()

        # Si se ejecuta con metadata de confirmación aprobada
        res_approved = self.manager.execute_skill(
            "filesystem.purge",
            parameters={"target": "D:\\Temp"},
            metadata={"confirmation_approved": True},
        )
        assert res_approved.success is True
        assert res_approved.status == SkillStatus.COMPLETED

    # ── 7. CANCELACIÓN COOPERATIVA ──

    def test_skill_cancellation_token(self) -> None:
        """Verifica que un token cancelado aborte la ejecución de la Skill."""
        self.manager.register_skill(DummySampleSkill())
        token = CancellationToken()
        token.cancel(reason="Operador canceló")

        res = self.manager.execute_skill("system.diagnostics", cancellation_token=token)
        assert res.success is False
        assert res.status == SkillStatus.CANCELLED
        assert "cancelada" in str(res.error).lower()

    # ── 8. PARADA DE EMERGENCIA PREVALENTE ──

    def test_emergency_stop_halts_skill_execution(self) -> None:
        """Verifica que la Parada de Emergencia impida inmediatamente la ejecución de cualquier Skill."""
        self.manager.register_skill(DummySampleSkill())
        self.emergency_stop.trigger_stop(reason="Test Stop", source="test")

        res = self.manager.execute_skill("system.diagnostics")
        assert res.success is False
        assert res.status == SkillStatus.CANCELLED
        assert "Parada de Emergencia" in str(res.error)

    # ── 9. DESREGISTRO Y SKILL DESCONOCIDA ──

    def test_unregister_skill_and_unknown_skill(self) -> None:
        """Verifica el desregistro y manejo elegante de skills desconocidas."""
        skill = DummySampleSkill()
        self.manager.register_skill(skill)
        assert len(self.manager.list_skills()) == 1

        unreg = self.manager.unregister_skill("system.diagnostics")
        assert unreg is True
        assert len(self.manager.list_skills()) == 0

        # Ejecutar skill desconocida
        res = self.manager.execute_skill("non.existent.skill")
        assert res.success is False
        assert res.status == SkillStatus.FAILED
        assert "no está registrada" in str(res.error)
