"""Test Suite Exhaustiva para Productización, Instalación y Distribución (Fase 46).

Valida los 10 escenarios requeridos:
1. clean install
2. upgrade
3. failed upgrade
4. rollback
5. uninstall
6. reinstall
7. configuration migration
8. memory migration
9. Skill compatibility
10. diagnostics

Además de pruebas para el First Run Wizard (8 pasos) e Invariantes de Seguridad.
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from core.distribution import (
    BackupManager,
    EnvironmentDiagnosticsEngine,
    FirstRunStatus,
    FirstRunStep,
    FirstRunWizard,
    InstallationState,
    ProductConfigManager,
    ProductUnifiedConfig,
    ProductVersion,
    ReleaseManifest,
    RollbackManager,
    SkillDistributionManager,
    SkillPackageMetadata,
    UninstallScope,
    WindowsInstallerEngine,
)


class TestProductizationPhase46:
    """Suite de pruebas de certificación para Instalación, Distribución y Mantenimiento."""

    def setup_method(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="jessyca_test_dist_"))
        self.install_root = self.temp_dir / "ProgramFiles" / "JESSYCA"
        self.data_root = self.temp_dir / "AppData" / "JESSYCA"

        self.installer = WindowsInstallerEngine(
            install_root=self.install_root,
            data_root=self.data_root,
        )

        self.manifest_v300 = ReleaseManifest(
            product_name="JESSYCA",
            version=ProductVersion(3, 0, 0),
            release_date="2026-08-21",
            changelog=("Initial JESSYCA 3.0 Local Agent release",),
            binary_sha256="VALID_SHA256_HASH_V300",
        )

        self.manifest_v310 = ReleaseManifest(
            product_name="JESSYCA",
            version=ProductVersion(3, 1, 0),
            release_date="2026-09-01",
            changelog=("Enhanced voice latency and smart model routing",),
            binary_sha256="VALID_SHA256_HASH_V310",
        )

    def teardown_method(self) -> None:
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── 1. CLEAN INSTALL ──
    def test_01_clean_install(self) -> None:
        """Verifica una instalación limpia: carpetas, version.json, configuraciones y accesos directos."""
        ok, err = self.installer.clean_install(self.manifest_v300)

        assert ok is True
        assert err is None
        assert self.installer.state == InstallationState.INSTALLED
        assert self.installer.current_version == ProductVersion(3, 0, 0)
        assert (self.install_root / "version.json").exists()
        assert (self.data_root / "config" / "settings.json").exists()
        assert len(self.installer._installed_shortcuts) == 2

    # ── 2. UPGRADE ──
    def test_02_successful_upgrade(self) -> None:
        """Verifica una actualización exitosa a una versión superior con reemplazo atómico."""
        self.installer.clean_install(self.manifest_v300)

        ok, err = self.installer.upgrade(self.manifest_v310)

        assert ok is True
        assert err is None
        assert self.installer.state == InstallationState.INSTALLED
        assert self.installer.current_version == ProductVersion(3, 1, 0)

        # Verificar manifiesto actualizado
        with open(self.install_root / "version.json", encoding="utf-8") as f:
            vdata = json.load(f)
            assert vdata["version"] == "3.1.0"

    # ── 3. FAILED UPGRADE & 4. ROLLBACK ──
    def test_03_failed_upgrade_and_automatic_rollback(self) -> None:
        """Verifica que un fallo durante la actualización revierta el sistema al snapshot previo de forma automática."""
        self.installer.clean_install(self.manifest_v300)

        # Modificar archivo de configuración para verificar que se preserva tras el rollback
        cfg = self.installer.config_manager.get_config()
        cfg.user.theme = "custom_cyberpunk"
        self.installer.config_manager.update_config(cfg)
        self.installer.config_manager.save_to_disk(self.installer.config_dir / "settings.json")

        corrupted_manifest = ReleaseManifest(
            product_name="JESSYCA",
            version=ProductVersion(3, 2, 0),
            release_date="2026-10-01",
            changelog=("Corrupted build",),
            binary_sha256="CORRUPT_HASH",
        )

        ok, err = self.installer.upgrade(corrupted_manifest)

        assert ok is False
        assert "rollback" in str(err).lower()
        assert self.installer.state == InstallationState.ROLLED_BACK

        # Verificar que la versión se restauró
        with open(self.install_root / "version.json", encoding="utf-8") as f:
            vdata = json.load(f)
            assert vdata["version"] == "3.0.0"

        # Verificar que la configuración previa sigue intacta
        cfg_restored = ProductConfigManager()
        cfg_restored.load_from_disk(self.installer.config_dir / "settings.json")
        assert cfg_restored.get_config().user.theme == "custom_cyberpunk"

    # ── 4. ROLLBACK DIRECT API ──
    def test_04_explicit_rollback_from_snapshot(self) -> None:
        """Verifica la API explícita de RollbackManager para revertir cambios a partir de una instantánea."""
        rollback_mgr = RollbackManager(self.temp_dir / "test_snapshots")
        test_dir = self.temp_dir / "app_state"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "app.txt").write_text("v1_stable")

        # 1. Crear instantánea
        snap_path = rollback_mgr.create_snapshot("snap-v1", [test_dir])
        assert snap_path.exists()

        # 2. Modificar estado
        (test_dir / "app.txt").write_text("v2_corrupted")
        assert (test_dir / "app.txt").read_text() == "v2_corrupted"

        # 3. Ejecutar rollback
        ok = rollback_mgr.rollback("snap-v1", {"app_state": test_dir})
        assert ok is True
        assert (test_dir / "app.txt").read_text() == "v1_stable"

    # ── 5. UNINSTALL ──
    def test_05_uninstall_preserving_user_data(self) -> None:
        """Verifica la desinstalación con alcance granular: elimina binarios pero conserva memoria y datos."""
        self.installer.clean_install(self.manifest_v300)

        # Crear archivo de memoria de usuario
        user_memory_file = self.installer.memory_dir / "episodic_memory.db"
        user_memory_file.write_text("user_conversation_facts_and_vectors")

        scope = UninstallScope(
            remove_application_binaries=True,
            remove_shortcuts=True,
            preserve_user_data=True,
            remove_memory_databases=False,
            remove_configuration_files=False,
        )

        ok, err = self.installer.uninstall(scope)

        assert ok is True
        assert err is None
        assert self.installer.state == InstallationState.UNINSTALLED
        assert not self.install_root.exists()             # Binarios eliminados
        assert len(self.installer._installed_shortcuts) == 0  # Accesos directos eliminados
        assert user_memory_file.exists()                  # Memoria preservada

    # ── 6. REINSTALL ──
    def test_06_reinstall_over_preserved_data(self) -> None:
        """Verifica la reinstalación sobre un entorno desinstalado que conservaba datos previos."""
        self.installer.clean_install(self.manifest_v300)
        user_memory_file = self.installer.memory_dir / "episodic_memory.db"
        user_memory_file.write_text("important_user_history")

        self.installer.uninstall(UninstallScope(preserve_user_data=True, remove_memory_databases=False))

        # Reinstalación
        ok, err = self.installer.reinstall(self.manifest_v300)

        assert ok is True
        assert self.installer.state == InstallationState.INSTALLED
        assert user_memory_file.exists()
        assert user_memory_file.read_text() == "important_user_history"

    # ── 7. CONFIGURATION MIGRATION ──
    def test_07_configuration_schema_migration(self) -> None:
        """Verifica la migración automática de un esquema de configuración legado (0.9.0) al esquema segregado 1.0.0."""
        legacy_data = {
            "schema_version": "0.9.0",
            "language": "es-PE",
            "server_port": 9000,
        }

        migrated = ProductConfigManager.migrate_schema(legacy_data, target_version="1.0.0")

        assert migrated["schema_version"] == "1.0.0"
        assert migrated["user"]["language"] == "es-PE"
        assert migrated["system"]["server_port"] == 9000

        # Carga en ProductUnifiedConfig
        unified_cfg = ProductUnifiedConfig.from_dict(migrated)
        assert unified_cfg.user.language == "es-PE"
        assert unified_cfg.system.server_port == 9000

    # ── 8. MEMORY & BACKUP MIGRATION (SECRET REDACTION) ──
    def test_08_memory_backup_and_restore_with_secret_redaction(self) -> None:
        """Verifica la creación de backup con sanitización de secretos y restauración verificada."""
        backup_mgr = BackupManager(self.temp_dir / "backups")

        # Configuración que contiene un secreto por error
        config_with_secret = {
            "api_key": "sk-secret123456789",
            "user": {"name": "Test User", "token": "eyJhbGciOiJIUzI1NiJ9.test"},
        }

        # Archivo de memoria
        mem_file = self.temp_dir / "test_memory.db"
        mem_file.write_text("vector_data_content")

        manifest, err = backup_mgr.create_backup(
            config_data=config_with_secret,
            memory_files=[mem_file],
            product_version="3.0.0",
        )

        assert manifest is not None
        assert err is None
        assert manifest.secrets_excluded is True

        # Verificar que el archivo de configuración dentro del backup tiene los secretos enmascarados
        bck_config = Path(manifest.backup_path) / "config.json"
        content = bck_config.read_text(encoding="utf-8")
        assert "sk-secret123456789" not in content
        assert "***REDACTED_API_KEY***" in content

        # Restauración
        restore_target = self.temp_dir / "restored_data"
        rest_ok, rest_err = backup_mgr.restore_backup(Path(manifest.backup_path), restore_target)
        assert rest_ok is True
        assert (restore_target / "memory" / "test_memory.db").exists()

    # ── 9. SKILL COMPATIBILITY & SECURITY (MARKETPLACE != TRUST) ──
    def test_09_skill_compatibility_and_security_analysis(self) -> None:
        """Verifica la política 'Marketplace != Trust': rechazo de skills con código sospechoso o incompatibles."""
        skill_dist = SkillDistributionManager(self.temp_dir / "installed_skills")

        # 1. Skill Maliciosa (contiene exec())
        malicious_file = self.temp_dir / "malicious_skill.py"
        malicious_file.write_text("import os\nexec('dangerous_code')\n")
        sha_malicious = hashlib.sha256(malicious_file.read_bytes()).hexdigest()

        meta_malicious = SkillPackageMetadata(
            skill_id="custom.untrusted_skill",
            version="1.0.0",
            author="Unknown",
            description="Suspicious skill",
            required_permissions=("filesystem.read",),
            checksum_sha256=sha_malicious,
        )

        ok, err = skill_dist.install_skill(malicious_file, meta_malicious, jessyca_version="3.0.0")
        assert ok is False
        assert "amenazas de seguridad" in str(err).lower()

        # 2. Skill Válida y Limpia
        clean_file = self.temp_dir / "clean_skill.py"
        clean_file.write_text("def run():\n    return 'Hello World'\n")
        sha_clean = hashlib.sha256(clean_file.read_bytes()).hexdigest()

        meta_clean = SkillPackageMetadata(
            skill_id="community.clean_calc",
            version="1.0.0",
            author="Verified Partner",
            description="Simple calculator skill",
            required_permissions=("math.calc",),
            checksum_sha256=sha_clean,
        )

        ok_clean, err_clean = skill_dist.install_skill(clean_file, meta_clean, jessyca_version="3.0.0")
        assert ok_clean is True
        assert err_clean is None

    # ── 10. DIAGNOSTICS & SECRET SANITIZATION ──
    def test_10_diagnostics_report_and_sanitization(self) -> None:
        """Verifica la generación del reporte diagnóstico de entorno y la sanitización de secretos en logs."""
        raw_logs = [
            "User connected with token=eyJhbGciOiJIUzI1NiJ9.abcdef123456",
            "Connecting to database with password=SuperSecretP@ssw0rd!",
            "Ollama model loaded successfully",
        ]

        report = EnvironmentDiagnosticsEngine.run_diagnostics(custom_logs=raw_logs)
        json_output = EnvironmentDiagnosticsEngine.export_report_json(report)

        assert report.windows_version != ""
        assert report.python_version != ""
        assert "eyJhbGciOiJIUzI1NiJ9" not in json_output
        assert "SuperSecretP@ssw0rd!" not in json_output
        assert "***REDACTED_TOKEN***" in json_output
        assert "***REDACTED_PASSWORD***" in json_output

    # ── 11. FIRST RUN WIZARD ──
    def test_11_first_run_wizard_pipeline(self) -> None:
        """Verifica la ejecución secuencial completa de los 8 pasos del First Run Wizard."""
        self.installer.clean_install(self.manifest_v300)

        wizard = FirstRunWizard(self.installer)
        status: FirstRunStatus = wizard.run_wizard()

        assert status.is_success is True
        assert status.first_launch_ready is True
        assert len(status.completed_steps) == 8
        assert FirstRunStep.INSTALLATION in status.completed_steps
        assert FirstRunStep.SECURITY_INITIALIZATION in status.completed_steps
        assert FirstRunStep.FIRST_LAUNCH in status.completed_steps
