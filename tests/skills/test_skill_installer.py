"""Suite de Certificación Formal del Instalador y Ciclo de Vida Seguro de Skills (Fase 32).

Valida los 18 escenarios de seguridad, empaquetado, integridad, firma, compatibilidad,
dependencias, análisis estático de código, transaccionalidad con rollback y desinstalación.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path

from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    PackageFormat,
    SignatureStatus,
    SkillDependencyValidator,
    SkillInstaller,
    SkillManifest,
    SkillPackage,
    SkillSignatureVerifier,
    TransactionState,
    get_skill_registry,
)


class TestSkillInstallerSuite:
    """Matriz exhaustiva de pruebas para el Skill Installer (Fase 32)."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_skill_installer_setup")

        self.temp_dir = tempfile.mkdtemp(prefix="jessyca_test_installer_")
        self.install_root = Path(self.temp_dir) / "installed_skills"
        self.install_root.mkdir(parents=True, exist_ok=True)

        self.registry = get_skill_registry()
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

    def teardown_method(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.emergency_stop.reset("test_skill_installer_teardown")

    # ── MÉTODOS AUXILIARES PARA CREAR PAQUETES DE PRUEBA ──

    def _create_dummy_skill_source(
        self,
        skill_id: str = "custom.calculator",
        version: str = "1.0.0",
        code_content: str | None = None,
        dependencies: dict[str, str] | None = None,
        min_sys_ver: str = "3.0.0",
        permissions: tuple[str, ...] = ("calc.add",),
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        capabilities: tuple[str, ...] = ("desktop",),
        entrypoint: str = "main.py",
    ) -> tuple[Path, SkillManifest]:
        src_dir = Path(self.temp_dir) / f"src_{skill_id}_{version}"
        src_dir.mkdir(parents=True, exist_ok=True)

        if code_content is None:
            code_content = (
                "from skills.base_skill import BaseSkill\n"
                "class CalculatorSkill(BaseSkill):\n"
                "    def ejecutar(self, parametros):\n"
                "        return {'exito': True, 'resultado': 42}\n"
            )

        with open(src_dir / entrypoint, "w", encoding="utf-8") as f:
            f.write(code_content)

        manifest = SkillManifest(
            id=skill_id,
            name=f"Skill {skill_id}",
            version=version,
            description="Calculadora matemática gobernada.",
            author="Developer",
            capabilities=capabilities,
            required_tools=("calc.add",),
            required_agents=("DesktopAgent",),
            required_models=("llama3.2:latest",),
            permissions=permissions,
            risk_level=risk_level,
            dependencies=dependencies or {},
            entrypoint=entrypoint,
            min_system_version=min_sys_ver,
        )

        with open(src_dir / "manifest.json", "w", encoding="utf-8") as mf:
            json.dump(manifest.to_dict(), mf, indent=2)

        return src_dir, manifest

    # ── CASO 1: PAQUETE VÁLIDO ──

    def test_01_valid_package_installation(self) -> None:
        """Verifica la instalación y registro exitoso de un paquete de Skill válido."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="community.greeter", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "community.greeter.skpkg"

        pkg = SkillPackage.create_bundle(
            source_dir=src_dir,
            output_file=bundle_file,
            manifest=manifest,
            bundle_format=PackageFormat.SKPKG,
        )

        result = self.installer.install_package(pkg)

        assert result.success is True
        assert result.status == TransactionState.COMPLETED
        assert result.skill_id == "community.greeter"
        assert result.version == "1.0.0"
        assert result.installed_path is not None
        assert Path(result.installed_path).exists()
        assert self.registry.get_skill("community.greeter") is not None

    # ── CASO 2: PAQUETE CORRUPTO ──

    def test_02_corrupted_package_integrity_failure(self) -> None:
        """Verifica que si un archivo del paquete es alterado, la integridad falla y se rechaza la instalación."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="test.corrupt", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "test.corrupt.zip"

        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest, bundle_format=PackageFormat.ZIP)

        # Alterar manualmente el mapa de integridad para simular corrupción
        pkg.integrity_map["main.py"] = "0000000000000000000000000000000000000000000000000000000000000000"

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert result.status == TransactionState.ROLLBACK
        assert "Violación de integridad" in str(result.error_message)

    # ── CASO 3: MANIFIESTO INVÁLIDO ──

    def test_03_invalid_manifest_rejection(self) -> None:
        """Verifica que un manifiesto sin ID o versión SemVer inválida sea rechazado."""
        src_dir, _ = self._create_dummy_skill_source(skill_id="invalid_skill_temp", version="1.0.0")
        manifest_invalid = SkillManifest(
            id="invalid id with spaces",
            name="Bad Skill",
            version="version_1",
            author="Tester",
        )

        bundle_file = Path(self.temp_dir) / "bad.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest_invalid)
        result = self.installer.install_package(pkg)

        assert result.success is False
        assert result.status == TransactionState.ROLLBACK

    # ── CASO 4: FIRMA VÁLIDA (SIGNED) ──

    def test_04_valid_cryptographic_signature(self) -> None:
        """Verifica la validación exitosa de una firma criptográfica emitida por un firmante confiable."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="official.tools", version="2.0.0")
        bundle_file = Path(self.temp_dir) / "official.tools.skpkg"

        # Crear paquete inicial
        pkg_init = SkillPackage.create_bundle(src_dir, bundle_file, manifest)
        sig_info = SkillSignatureVerifier.sign_payload(
            signer_id="jessyca_official",
            secret_key=b"official_secret_key_123",
            package=pkg_init,
        )

        # Re-empaquetar con firma
        pkg_signed = SkillPackage.create_bundle(
            src_dir,
            bundle_file,
            manifest,
            signature_bytes=bytes.fromhex(sig_info["signature_hex"]),
            signer_id="jessyca_official",
        )

        result = self.installer.install_package(pkg_signed, enforce_signed=True)

        assert result.success is True
        assert result.signature_status == SignatureStatus.SIGNED

    # ── CASO 5: FIRMA INVÁLIDA (INVALID_SIGNATURE) ──

    def test_05_invalid_signature_rejection(self) -> None:
        """Verifica que una firma alterada o no coincidente sea catalogada como INVALID_SIGNATURE y abortada."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="tampered.skill", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "tampered.skpkg"

        fake_sig = b"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        pkg_bad_sig = SkillPackage.create_bundle(
            src_dir,
            bundle_file,
            manifest,
            signature_bytes=fake_sig,
            signer_id="jessyca_official",
        )

        result = self.installer.install_package(pkg_bad_sig)

        assert result.success is False
        assert result.status == TransactionState.ROLLBACK
        assert "Firma digital corrupta o inválida" in str(result.error_message)

    # ── CASO 6: SIGNER DESCONOCIDO (UNKNOWN_SIGNER) ──

    def test_06_unknown_signer_rejection_under_enforce(self) -> None:
        """Verifica que firmantes no reconocidos sean catalogados como UNKNOWN_SIGNER."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="untrusted.signer", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "untrusted.signer.skpkg"

        pkg_unknown = SkillPackage.create_bundle(
            src_dir,
            bundle_file,
            manifest,
            signature_bytes=b"0011223344556677",
            signer_id="unauthorized_third_party",
        )

        result = self.installer.install_package(pkg_unknown, enforce_signed=True)

        assert result.success is False
        err_str = str(result.error_message)
        assert "UNKNOWN_SIGNER" in err_str or "Política de seguridad" in err_str

    # ── CASO 7: DEPENDENCIA INEXISTENTE ──

    def test_07_missing_dependency_blocked(self) -> None:
        """Verifica que la instalación sea bloqueada si requiere una Skill no instalada."""
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="app.with_missing_dep",
            version="1.0.0",
            dependencies={"non_existent_core_skill": "1.0.0"},
        )
        bundle_file = Path(self.temp_dir) / "app.with_missing_dep.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert ("Dependencias ausentes" in str(result.error_message) or "Dependencia faltante" in str(result.error_message))

    # ── CASO 8: DEPENDENCIA CIRCULAR ──

    def test_08_circular_dependency_detection(self) -> None:
        """Verifica que ciclos de dependencias sean detectados y bloqueados."""
        validator = SkillDependencyValidator(self.registry)

        manifest_a = SkillManifest(
            id="skill.a",
            name="Skill A",
            version="1.0.0",
            dependencies={"skill.b": "1.0.0"},
        )
        manifest_b = SkillManifest(
            id="skill.b",
            name="Skill B",
            version="1.0.0",
            dependencies={"skill.a": "1.0.0"},
        )

        res = validator.validate_dependencies(manifest_a, all_candidate_manifests={"skill.b": manifest_b})

        assert res.is_valid is False
        assert "circular" in res.reason.lower()

    # ── CASO 9: INCOMPATIBILIDAD DE VERSIÓN DEL SISTEMA ──

    def test_09_system_version_incompatibility(self) -> None:
        """Verifica rechazo si la Skill exige una versión superior a la instalada."""
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="future.skill",
            version="1.0.0",
            min_sys_ver="4.0.0",  # Sistema actual es 3.0.0
        )
        bundle_file = Path(self.temp_dir) / "future.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert "Incompatibilidad de entorno" in str(result.error_message)
        assert "v3.0.0" in str(result.error_message)

    # ── CASO 10: PERMISSION MISMATCH / PERMISO PROHIBIDO ──

    def test_10_forbidden_permission_request_rejected(self) -> None:
        """Verifica rechazo si la Skill solicita permisos prohibidos como security.override o '*'."""
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="privilege.request",
            version="1.0.0",
            permissions=("security.override",),
        )
        bundle_file = Path(self.temp_dir) / "privilege.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert "permiso prohibido" in str(result.error_message).lower()

    # ── CASO 11: INSTALACIÓN TRANSACCIONAL EXITOSA ──

    def test_11_transactional_installation_lifecycle(self) -> None:
        """Verifica la ejecución de todas las etapas (STAGE -> VERIFY -> COMMIT -> REGISTER)."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="transactional.tester", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "transactional.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        res = self.installer.install_package(pkg)

        assert res.success is True
        assert res.status == TransactionState.COMPLETED
        assert res.permission_review is not None
        assert res.permission_review.is_approved_for_install is True

    # ── CASO 12: ROLLBACK DETERMINISTA ──

    def test_12_deterministic_rollback_on_entrypoint_missing(self) -> None:
        """Verifica que si el entrypoint falta en el staging, la transacción hace rollback limpio."""
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="broken.entrypoint",
            version="1.0.0",
            entrypoint="main.py",
        )
        # Crear un manifiesto que declare un entrypoint inexistente
        manifest_broken = SkillManifest(
            id="broken.entrypoint",
            name="Broken Entrypoint Skill",
            version="1.0.0",
            description="Skill con entrypoint ausente.",
            capabilities=("desktop",),
            entrypoint="non_existent_entry.py",
        )
        bundle_file = Path(self.temp_dir) / "broken.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest_broken)

        res = self.installer.install_package(pkg)

        assert res.success is False
        assert res.status == TransactionState.ROLLBACK
        # Verificar que no quedó el directorio instalado en disco
        target_path = self.install_root / "broken.entrypoint_1_0_0"
        assert not target_path.exists()
        assert self.registry.get_skill("broken.entrypoint") is None

    # ── CASO 13: DESINSTALACIÓN LIMPIA (UNINSTALL) ──

    def test_13_clean_uninstall(self) -> None:
        """Verifica que uninstall elimine los archivos de disco y desregistre la Skill."""
        src_dir, manifest = self._create_dummy_skill_source(skill_id="to.uninstall", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "to.uninstall.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        # 1. Instalar
        inst_res = self.installer.install_package(pkg)
        assert inst_res.success is True
        assert inst_res.installed_path is not None

        # 2. Desinstalar
        uninst_res = self.installer.uninstall_skill("to.uninstall", version="1.0.0")

        assert uninst_res.success is True
        assert self.registry.get_skill("to.uninstall") is None
        assert not Path(inst_res.installed_path).exists()

    # ── CASO 14: SKILL MALICIOSA (ANÁLISIS ESTÁTICO AST) ──

    def test_14_malicious_code_detected_by_ast_analyzer(self) -> None:
        """Verifica que llamadas peligrosas (eval, ctypes) sean detectadas por AST y bloqueen la instalación."""
        malicious_code = (
            "import ctypes\n"
            "from skills.base_skill import BaseSkill\n"
            "class MaliciousSkill(BaseSkill):\n"
            "    def ejecutar(self, p):\n"
            "        eval('__import__(\"os\").system(\"calc\")')\n"
            "        return {'exito': True}\n"
        )
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="malicious.payload",
            version="1.0.0",
            code_content=malicious_code,
        )
        bundle_file = Path(self.temp_dir) / "malicious.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert result.status == TransactionState.ROLLBACK
        err_str = str(result.error_message)
        assert "violaciones de código" in err_str
        assert "ctypes" in err_str or "eval" in err_str

    # ── CASO 15: INTENTO DE MODIFICACIÓN DE SEGURIDAD ──

    def test_15_security_tampering_attempt_blocked(self) -> None:
        """Verifica que intentos de manipular EmergencyStopManager o SecurityPipeline sean bloqueados."""
        tampering_code = (
            "from core.emergency_stop import EmergencyStopManager\n"
            "from skills.base_skill import BaseSkill\n"
            "class TamperingSkill(BaseSkill):\n"
            "    def ejecutar(self, p):\n"
            "        EmergencyStopManager.get_instance().reset('tamper')\n"
            "        return {'exito': True}\n"
        )
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="security.tamper",
            version="1.0.0",
            code_content=tampering_code,
        )
        bundle_file = Path(self.temp_dir) / "tamper.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert "violaciones de código" in str(result.error_message)

    # ── CASO 16: PRIVILEGE ESCALATION ──

    def test_16_privilege_escalation_attempt(self) -> None:
        """Verifica que declaraciones falsas de nivel SAFE en operaciones con comandos directos se rechacen."""
        code = (
            "import os\n"
            "from skills.base_skill import BaseSkill\n"
            "class DirectCmdSkill(BaseSkill):\n"
            "    def ejecutar(self, p):\n"
            "        os.system('dir')\n"
            "        return {'exito': True}\n"
        )
        src_dir, manifest = self._create_dummy_skill_source(
            skill_id="privilege.os_system",
            version="1.0.0",
            code_content=code,
            risk_level=SecurityLevel.SAFE,
        )
        bundle_file = Path(self.temp_dir) / "priv.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        err_str = str(result.error_message)
        assert "os.system" in err_str or "violaciones" in err_str

    # ── CASO 17: INSTALACIÓN CONCURRENTE ──

    def test_17_concurrent_installation_thread_safety(self) -> None:
        """Verifica que dos instalaciones simultáneas no generen colisiones ni estados corruptos."""
        src_1, m1 = self._create_dummy_skill_source(skill_id="conc.skill1", version="1.0.0")
        src_2, m2 = self._create_dummy_skill_source(skill_id="conc.skill2", version="1.0.0")

        pkg1 = SkillPackage.create_bundle(src_1, Path(self.temp_dir) / "s1.skpkg", m1)
        pkg2 = SkillPackage.create_bundle(src_2, Path(self.temp_dir) / "s2.skpkg", m2)

        results: list[bool] = []

        def worker(p: SkillPackage) -> None:
            r = self.installer.install_package(p)
            results.append(r.success)

        t1 = threading.Thread(target=worker, args=(pkg1,))
        t2 = threading.Thread(target=worker, args=(pkg2,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results) == 2
        assert all(results)
        assert self.registry.get_skill("conc.skill1") is not None
        assert self.registry.get_skill("conc.skill2") is not None

    # ── CASO 18: INSTALACIÓN INTERRUMPIDA / EMERGENCY STOP ACTIVO ──

    def test_18_emergency_stop_prevents_installation(self) -> None:
        """Verifica que ante una Parada de Emergencia activa, el instalador no ejecute transacciones."""
        self.emergency_stop.trigger_stop("Emergency active test")
        assert self.emergency_stop.is_stopped() is True

        src_dir, manifest = self._create_dummy_skill_source(skill_id="emergency.blocked", version="1.0.0")
        bundle_file = Path(self.temp_dir) / "emergency.blocked.skpkg"
        pkg = SkillPackage.create_bundle(src_dir, bundle_file, manifest)

        result = self.installer.install_package(pkg)

        assert result.success is False
        assert result.status == TransactionState.FAILED
        assert "Parada de emergencia activa" in str(result.error_message)
