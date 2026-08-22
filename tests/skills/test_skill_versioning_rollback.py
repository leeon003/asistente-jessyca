"""Suite de Certificación Formal de Versionado, Compatibilidad y Rollback de Skills (Fase 33).

Valida los 16 escenarios requeridos:
1. patch update
2. minor update
3. major update
4. incompatible update (system/framework)
5. dependency conflict
6. invalid signature
7. corrupted package
8. failed activation (automatic rollback)
9. rollback explícito
10. concurrent update
11. update during running task
12. Emergency Stop during update
13. security modification attempt
14. permission escalation
15. downgrade handling
16. uninstall after update
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

from core.audit_logger import get_audit_logger
from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    SemVer,
    SemVerConstraint,
    SkillInstaller,
    SkillManifest,
    SkillPackage,
    SkillSignatureVerifier,
    SkillUpdater,
    VersionBumpType,
    get_skill_manager,
    get_skill_registry,
)


class TestSkillVersioningRollbackSuite:
    """Matriz exhaustiva de pruebas de versionado, compatibilidad y rollback de Skills."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_skill_versioning_setup")

        self.temp_dir = tempfile.mkdtemp(prefix="jessyca_test_versioning_")
        self.install_root = Path(self.temp_dir) / "installed_skills"
        self.install_root.mkdir(parents=True, exist_ok=True)

        self.registry = get_skill_registry()
        self.registry.reset()
        self.manager = get_skill_manager()
        self.audit_logger = get_audit_logger()

        self.sig_verifier = SkillSignatureVerifier(
            trusted_signers={
                "jessyca_official": b"official_secret_key_123",
                "trusted_developer": b"trusted_dev_key_456",
            }
        )
        self.installer = SkillInstaller(
            install_root=self.install_root,
            registry=self.registry,
            signature_verifier=self.sig_verifier,
            emergency_stop=self.emergency_stop,
        )
        self.updater = SkillUpdater(
            install_root=self.install_root,
            registry=self.registry,
            signature_verifier=self.sig_verifier,
            emergency_stop=self.emergency_stop,
        )

    def _skill_ver(self, target: str) -> str:
        s = self.registry.lookup(target)
        assert s is not None
        return s.version

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.registry.reset()
        self.emergency_stop.reset("test_skill_versioning_teardown")

    # ── MÉTODOS AUXILIARES PARA CREACIÓN DE PAQUETES ──

    def _create_skill_package(
        self,
        skill_id: str = "browser.search",
        version: str = "1.0.0",
        code_content: str | None = None,
        dependencies: dict[str, str] | None = None,
        min_sys_ver: str = "3.0.0",
        max_sys_ver: str | None = None,
        min_fw_ver: str = "1.0.0",
        max_fw_ver: str | None = None,
        permissions: tuple[str, ...] = ("browser.navigate",),
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        capabilities: tuple[str, ...] = ("browser",),
        required_tools: tuple[str, ...] = ("browser.navigate",),
        entrypoint: str = "main.py",
        signature_signer: str | None = None,
        secret_key: bytes | None = None,
    ) -> SkillPackage:
        src_dir = Path(self.temp_dir) / f"src_{skill_id}_{version.replace('.', '_')}"
        src_dir.mkdir(parents=True, exist_ok=True)

        if code_content is None:
            code_content = (
                "from skills.base_skill import BaseSkill\n"
                "class GenericSkill(BaseSkill):\n"
                f"    skill_version = '{version}'\n"
                "    def ejecutar(self, parametros):\n"
                f"        return {{'exito': True, 'version': '{version}'}}\n"
            )

        with open(src_dir / entrypoint, "w", encoding="utf-8") as f:
            f.write(code_content)

        manifest = SkillManifest(
            id=skill_id,
            name=f"Skill {skill_id}",
            version=version,
            description="Skill gobernada versionable.",
            author="Developer",
            capabilities=capabilities,
            required_tools=required_tools,
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest",),
            permissions=permissions,
            risk_level=risk_level,
            dependencies=dependencies or {},
            entrypoint=entrypoint,
            min_system_version=min_sys_ver,
            max_system_version=max_sys_ver,
            min_framework_version=min_fw_ver,
            max_framework_version=max_fw_ver,
        )

        with open(src_dir / "manifest.json", "w", encoding="utf-8") as mf:
            json.dump(manifest.to_dict(), mf, indent=2)

        bundle_file = Path(self.temp_dir) / f"{skill_id}_{version.replace('.', '_')}.skpkg"

        # Firma si se solicita
        sig_bytes = None
        if signature_signer and secret_key:
            pkg_init = SkillPackage.create_bundle(src_dir, bundle_file, manifest)
            sig_info = SkillSignatureVerifier.sign_payload(signature_signer, secret_key, pkg_init)
            sig_bytes = bytes.fromhex(sig_info["signature_hex"])

        return SkillPackage.create_bundle(
            source_dir=src_dir,
            output_file=bundle_file,
            manifest=manifest,
            signature_bytes=sig_bytes,
            signer_id=signature_signer,
        )

    # ── 0. PRUEBAS BÁSICAS DE SEMVER Y CONSTRAINTS ──

    def test_00_semver_and_constraint_logic(self) -> None:
        """Verifica el correcto funcionamiento del comparador SemVer y evaluador de restricciones."""
        v100 = SemVer.parse("1.0.0")
        v101 = SemVer.parse("1.0.1")
        v110 = SemVer.parse("1.1.0")
        v200 = SemVer.parse("2.0.0")
        v100_pre = SemVer.parse("1.0.0-beta.1")

        assert v101.is_patch_of(v100) is True
        assert v110.is_minor_of(v100) is True
        assert v200.is_major_of(v100) is True
        assert v100.is_downgrade_of(v200) is True
        assert v100_pre < v100

        assert v101.bump_type_from(v100) == VersionBumpType.PATCH
        assert v110.bump_type_from(v100) == VersionBumpType.MINOR
        assert v200.bump_type_from(v100) == VersionBumpType.MAJOR
        assert v100.bump_type_from(v200) == VersionBumpType.DOWNGRADE
        assert v100.bump_type_from(v100) == VersionBumpType.SAME

        c_caret = SemVerConstraint("^1.0.0")
        assert c_caret.matches("1.0.0") is True
        assert c_caret.matches("1.5.2") is True
        assert c_caret.matches("2.0.0") is False

        c_tilde = SemVerConstraint("~1.2.0")
        assert c_tilde.matches("1.2.5") is True
        assert c_tilde.matches("1.3.0") is False

        c_range = SemVerConstraint(">=1.0.0, <2.0.0")
        assert c_range.matches("1.9.9") is True
        assert c_range.matches("2.0.0") is False

    # ── 1. PATCH UPDATE ──

    def test_01_patch_update(self) -> None:
        """Verifica la actualización PATCH (1.0.0 -> 1.0.1) exitosa y registro como known-good."""
        pkg_v100 = self._create_skill_package(skill_id="browser.search", version="1.0.0")
        inst_res = self.installer.install_package(pkg_v100)
        assert inst_res.success is True
        assert self._skill_ver("browser.search") == "1.0.0"

        pkg_v101 = self._create_skill_package(skill_id="browser.search", version="1.0.1")
        upd_res = self.installer.update_package(pkg_v101)

        assert upd_res.success is True
        assert upd_res.old_version == "1.0.0"
        assert upd_res.new_version == "1.0.1"
        assert upd_res.change_report is not None
        assert upd_res.change_report.bump_type == VersionBumpType.PATCH
        assert self._skill_ver("browser.search") == "1.0.1"
        assert "1.0.1" in self.registry.get_known_good_versions("browser.search")

    # ── 2. MINOR UPDATE ──

    def test_02_minor_update(self) -> None:
        """Verifica la actualización MINOR (1.0.0 -> 1.1.0) con nuevas herramientas compatibles."""
        pkg_v100 = self._create_skill_package(
            skill_id="browser.search",
            version="1.0.0",
            required_tools=("browser.navigate",),
            permissions=("browser.navigate",),
        )
        self.installer.install_package(pkg_v100)

        pkg_v110 = self._create_skill_package(
            skill_id="browser.search",
            version="1.1.0",
            required_tools=("browser.navigate", "browser.quick_read"),
            permissions=("browser.navigate",),
        )
        upd_res = self.installer.update_package(pkg_v110)

        assert upd_res.success is True
        assert upd_res.new_version == "1.1.0"
        assert upd_res.change_report is not None
        assert upd_res.change_report.bump_type == VersionBumpType.MINOR
        assert "browser.quick_read" in upd_res.change_report.new_tools
        assert self._skill_ver("browser.search") == "1.1.0"

    # ── 3. MAJOR UPDATE (BREAKING CHANGE) ──

    def test_03_major_update_with_confirmation(self) -> None:
        """Verifica la actualización MAJOR (1.0.0 -> 2.0.0) como breaking change con confirmación de usuario."""
        pkg_v1 = self._create_skill_package(skill_id="browser.search", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(
            skill_id="browser.search",
            version="2.0.0",
            risk_level=SecurityLevel.MEDIUM,
        )

        # 1. Sin confirmación debe ser rechazado si requires_user_confirmation es True
        upd_no_conf = self.installer.update_package(pkg_v2, user_confirmed=False)
        assert upd_no_conf.success is False
        assert "requiere confirmación" in str(upd_no_conf.error_message)

        # 2. Con confirmación se activa exitosamente
        upd_conf = self.installer.update_package(pkg_v2, user_confirmed=True)
        assert upd_conf.success is True
        assert upd_conf.new_version == "2.0.0"
        assert upd_conf.change_report is not None
        assert upd_conf.change_report.is_breaking is True
        assert self._skill_ver("browser.search") == "2.0.0"

    # ── 4. INCOMPATIBLE UPDATE ──

    def test_04_incompatible_system_and_framework_update(self) -> None:
        """Verifica que una actualización que exceda la versión máxima del sistema o framework sea bloqueada."""
        pkg_v1 = self._create_skill_package(skill_id="system.monitor", version="1.0.0")
        self.installer.install_package(pkg_v1)

        # Intento con max_system_version inferior a la del sistema (2.5.0 < 3.0.0)
        pkg_incomp = self._create_skill_package(
            skill_id="system.monitor",
            version="1.1.0",
            max_sys_ver="2.5.0",
        )
        upd_res = self.installer.update_package(pkg_incomp)

        assert upd_res.success is False
        assert "Incompatibilidad de entorno" in str(upd_res.error_message)
        # La versión activa debe seguir siendo 1.0.0
        assert self._skill_ver("system.monitor") == "1.0.0"

    # ── 5. DEPENDENCY CONFLICT ──

    def test_05_dependency_conflict_during_update(self) -> None:
        """Verifica rechazo de actualización cuando exige una dependencia ausente o de versión incompatible."""
        pkg_v1 = self._create_skill_package(skill_id="custom.app", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2_bad_dep = self._create_skill_package(
            skill_id="custom.app",
            version="1.1.0",
            dependencies={"non.existent.dependency": "2.0.0"},
        )
        upd_res = self.installer.update_package(pkg_v2_bad_dep)

        assert upd_res.success is False
        assert "dependencia" in str(upd_res.error_message).lower()
        assert self._skill_ver("custom.app") == "1.0.0"

    # ── 6. INVALID SIGNATURE ──

    def test_06_invalid_signature_update_rejected(self) -> None:
        """Verifica que una firma alterada o corrupta rechace la actualización."""
        pkg_v1 = self._create_skill_package(skill_id="secure.vault", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(skill_id="secure.vault", version="1.1.0")
        # Simular firma corrupta
        pkg_v2.signature_bytes = b"bad_signature_bytes_1234567890"
        pkg_v2.signer_id = "jessyca_official"

        upd_res = self.installer.update_package(pkg_v2, enforce_signed=True)

        assert upd_res.success is False
        assert "Firma digital" in str(upd_res.error_message)
        assert self._skill_ver("secure.vault") == "1.0.0"

    # ── 7. CORRUPTED PACKAGE ──

    def test_07_corrupted_package_integrity_failure(self) -> None:
        """Verifica que si un archivo del paquete está corrupto, la actualización aborte y no altere la versión activa."""
        pkg_v1 = self._create_skill_package(skill_id="doc.editor", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(skill_id="doc.editor", version="1.0.1")
        # Alterar mapa de integridad
        pkg_v2.integrity_map["main.py"] = "badhash00000000000000000000000000000000000000000000000000000000"

        upd_res = self.installer.update_package(pkg_v2)

        assert upd_res.success is False
        assert "integridad" in str(upd_res.error_message).lower()
        assert self._skill_ver("doc.editor") == "1.0.0"

    # ── 8. FAILED ACTIVATION & AUTOMATIC ROLLBACK ──

    def test_08_failed_activation_automatic_rollback(self) -> None:
        """Verifica que si la sonda post-activación falla, se ejecuta un rollback atómico automático a la versión known-good."""
        pkg_v1 = self._create_skill_package(skill_id="calc.service", version="1.0.0")
        self.installer.install_package(pkg_v1)
        assert self._skill_ver("calc.service") == "1.0.0"

        pkg_v2 = self._create_skill_package(skill_id="calc.service", version="1.1.0")

        # Simular fallo en la sonda de verificación post-activación
        upd_res = self.updater.update_skill(pkg_v2, simulate_verify_failure=True)

        assert upd_res.success is False
        assert upd_res.rolled_back is True
        # La versión activa debe seguir siendo la 1.0.0 operacional
        active_skill = self.registry.lookup("calc.service")
        assert active_skill is not None
        assert active_skill.version == "1.0.0"

    # ── 9. EXPLICIT ROLLBACK ──

    def test_09_explicit_rollback_and_audit(self) -> None:
        """Verifica que el rollback explícito restablezca la versión conocida funcional y quede registrado en AuditLogger."""
        pkg_v1 = self._create_skill_package(skill_id="browser.search", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(skill_id="browser.search", version="1.1.0")
        self.installer.update_package(pkg_v2)
        assert self._skill_ver("browser.search") == "1.1.0"

        # Ejecutar rollback explícito
        rb_res = self.installer.rollback_skill("browser.search", reason="Problema de latencia en v1.1.0")

        assert rb_res.success is True
        assert rb_res.from_version == "1.1.0"
        assert rb_res.to_version == "1.0.0"
        assert self._skill_ver("browser.search") == "1.0.0"

        # Comprobar evento de auditoría
        events = self.audit_logger.get_events(tool_name="skill_updater.browser.search")
        assert len(events) > 0
        rollback_events = [e for e in events if e.operation == "SKILL_ROLLBACK_EXECUTED"]
        assert len(rollback_events) >= 1
        assert rollback_events[0].success is True

    # ── 10. CONCURRENT UPDATE ──

    def test_10_concurrent_updates_thread_safety(self) -> None:
        """Verifica que múltiples actualizaciones concurrentes no corrompan el estado del catálogo ni el directorio."""
        pkg_a1 = self._create_skill_package(skill_id="skill.alpha", version="1.0.0")
        pkg_b1 = self._create_skill_package(skill_id="skill.beta", version="1.0.0")
        self.installer.install_package(pkg_a1)
        self.installer.install_package(pkg_b1)

        pkg_a2 = self._create_skill_package(skill_id="skill.alpha", version="1.0.1")
        pkg_b2 = self._create_skill_package(skill_id="skill.beta", version="1.0.1")

        results: list[bool] = []

        def worker(p: SkillPackage) -> None:
            res = self.installer.update_package(p)
            results.append(res.success)

        t1 = threading.Thread(target=worker, args=(pkg_a2,))
        t2 = threading.Thread(target=worker, args=(pkg_b2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        assert all(results)
        assert self._skill_ver("skill.alpha") == "1.0.1"
        assert self._skill_ver("skill.beta") == "1.0.1"

    # ── 11. UPDATE DURING RUNNING TASK (COEXISTENCIA) ──

    def test_11_update_during_running_task_coexistence(self) -> None:
        """Verifica que ambas versiones coexistan en el registro permitiendo invocaciones dirigidas a v1.0.0 y v1.1.0."""
        pkg_v1 = self._create_skill_package(skill_id="multi.task", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(skill_id="multi.task", version="1.1.0")
        self.installer.update_package(pkg_v2)

        # Ambas versiones deben estar disponibles en el catálogo
        assert self._skill_ver("multi.task@1.0.0") == "1.0.0"
        assert self._skill_ver("multi.task@1.1.0") == "1.1.0"
        assert self._skill_ver("multi.task") == "1.1.0"

    # ── 12. EMERGENCY STOP DURING UPDATE ──

    def test_12_emergency_stop_blocks_update_and_rollback(self) -> None:
        """Verifica que la parada de emergencia activa bloquee inmediatamente cualquier actualización o rollback."""
        pkg_v1 = self._create_skill_package(skill_id="emergency.test", version="1.0.0")
        self.installer.install_package(pkg_v1)

        # Activar Parada de Emergencia
        self.emergency_stop.trigger_stop("Prueba de Parada de Emergencia activa")
        assert self.emergency_stop.is_stopped() is True

        pkg_v2 = self._create_skill_package(skill_id="emergency.test", version="1.1.0")
        upd_res = self.installer.update_package(pkg_v2)

        assert upd_res.success is False
        assert "Parada de emergencia activa" in str(upd_res.error_message)

        rb_res = self.installer.rollback_skill("emergency.test")
        assert rb_res.success is False
        assert "Parada de emergencia activa" in str(rb_res.error_message)

    # ── 13. SECURITY MODIFICATION ATTEMPT ──

    def test_13_security_tampering_in_update_blocked(self) -> None:
        """Verifica que si el código actualizado intenta manipular la seguridad (AST), sea rechazado."""
        pkg_v1 = self._create_skill_package(skill_id="tamper.test", version="1.0.0")
        self.installer.install_package(pkg_v1)

        tamper_code = (
            "from core.emergency_stop import EmergencyStopManager\n"
            "from skills.base_skill import BaseSkill\n"
            "class TamperingSkill(BaseSkill):\n"
            "    def ejecutar(self, p):\n"
            "        EmergencyStopManager.get_instance().reset('tamper')\n"
            "        return {'exito': True}\n"
        )

        pkg_v2_tamper = self._create_skill_package(
            skill_id="tamper.test",
            version="1.1.0",
            code_content=tamper_code,
        )

        upd_res = self.installer.update_package(pkg_v2_tamper)

        assert upd_res.success is False
        assert "violaciones" in str(upd_res.error_message)
        assert self._skill_ver("tamper.test") == "1.0.0"

    # ── 14. PERMISSION ESCALATION ──

    def test_14_permission_escalation_detection(self) -> None:
        """Verifica que si la nueva versión incluye permisos prohibidos o riesgo degradado, sea rechazada."""
        pkg_v1 = self._create_skill_package(skill_id="perm.test", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2_bad_perm = self._create_skill_package(
            skill_id="perm.test",
            version="1.1.0",
            permissions=("security.override",),
        )

        upd_res = self.installer.update_package(pkg_v2_bad_perm)

        assert upd_res.success is False
        assert "permiso prohibido" in str(upd_res.error_message).lower()
        assert self._skill_ver("perm.test") == "1.0.0"

    # ── 15. DOWNGRADE HANDLING ──

    def test_15_downgrade_detection_and_reporting(self) -> None:
        """Verifica que una operación de downgrade (2.0.0 -> 1.0.0) sea catalogada como DOWNGRADE con advertencia."""
        pkg_v2 = self._create_skill_package(skill_id="downgrade.test", version="2.0.0")
        self.installer.install_package(pkg_v2)

        pkg_v1 = self._create_skill_package(skill_id="downgrade.test", version="1.0.0")

        change_report = self.installer.get_change_report(pkg_v1)

        assert change_report.bump_type == VersionBumpType.DOWNGRADE
        assert change_report.requires_user_confirmation is True
        assert any("downgrade" in w.lower() for w in change_report.warnings)

    # ── 16. UNINSTALL AFTER UPDATE ──

    def test_16_uninstall_after_update(self) -> None:
        """Verifica que se pueda desinstalar una versión específica o desinstalar la Skill completa tras actualizarse."""
        pkg_v1 = self._create_skill_package(skill_id="uninstall.test", version="1.0.0")
        self.installer.install_package(pkg_v1)

        pkg_v2 = self._create_skill_package(skill_id="uninstall.test", version="1.1.0")
        self.installer.update_package(pkg_v2)

        assert self.registry.lookup("uninstall.test@1.0.0") is not None
        assert self.registry.lookup("uninstall.test@1.1.0") is not None

        # Desinstalar versión 1.0.0 solamente
        uninst_v1 = self.installer.uninstall_skill("uninstall.test", version="1.0.0")
        assert uninst_v1.success is True
        assert self.registry.lookup("uninstall.test@1.0.0") is None
        assert self.registry.lookup("uninstall.test@1.1.0") is not None

        # Desinstalar toda la Skill
        uninst_all = self.installer.uninstall_skill("uninstall.test")
        assert uninst_all.success is True
        assert self.registry.lookup("uninstall.test") is None
