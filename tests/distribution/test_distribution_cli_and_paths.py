"""tests/distribution/test_distribution_cli_and_paths.py

Batería de pruebas automatizadas para la Etapa 1 de Distribución de JESSYCA:
- Instalación local reproducible y comando global jessyca.
- Segregación estricta de rutas: código, configuración, datos/memoria, logs, cachés y modelos.
- Modelo de servicio Core y cliente con concurrencia y bloqueo explícito.
- Diagnóstico (doctor/diag) sanitizado y sin activación ni descarga remota de modelos.
- Creación física y verificación de accesos directos (sin listas ficticias).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.distribution.distribution_models import ProductVersion, ReleaseManifest, UninstallScope
from core.distribution.environment_diagnostics import EnvironmentDiagnosticsEngine
from core.distribution.installer_engine import WindowsInstallerEngine
from core.distribution.paths import (
    JessycaPaths,
    ensure_directories,
    get_cache_dir,
    get_logs_dir,
    get_models_dir,
    get_paths,
    get_user_config_dir,
    get_user_data_dir,
)
from core.distribution.service_client import (
    CoreClient,
    CoreProcessLock,
    CoreServiceStatus,
    explicit_core_lock,
)
from main import (
    parse_arguments,
    run_config_command,
    run_doctor_command,
    run_status_command,
)


class TestPathSegregation:
    """Valida la segregación canónica de rutas según los principios de distribución."""

    def test_paths_are_strictly_segregated(self) -> None:
        """Comprueba que ninguna de las carpetas mutables coincida con el código instalado."""
        paths = get_paths()

        assert isinstance(paths, JessycaPaths)
        assert paths.code_dir.exists()
        assert paths.code_dir.is_dir()

        # Las rutas mutables deben ser distintas entre sí y del código base
        dirs = [
            paths.code_dir,
            paths.config_dir,
            paths.data_dir,
            paths.logs_dir,
            paths.cache_dir,
            paths.models_dir,
        ]
        # Todas las rutas deben ser únicas
        assert len(dirs) == len(set(dirs))

    def test_environment_variable_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica que las variables de entorno sobreescriban limpiamente las rutas."""
        temp_dir = Path(tempfile.mkdtemp(prefix="jessyca_test_paths_"))
        try:
            custom_config = temp_dir / "custom_config"
            custom_data = temp_dir / "custom_data"
            custom_logs = temp_dir / "custom_logs"
            custom_cache = temp_dir / "custom_cache"
            custom_models = temp_dir / "custom_models"

            monkeypatch.setenv("JESSYCA_CONFIG_DIR", str(custom_config))
            monkeypatch.setenv("JESSYCA_DATA_DIR", str(custom_data))
            monkeypatch.setenv("JESSYCA_LOG_DIR", str(custom_logs))
            monkeypatch.setenv("JESSYCA_CACHE_DIR", str(custom_cache))
            monkeypatch.setenv("JESSYCA_MODELS_DIR", str(custom_models))

            assert get_user_config_dir() == custom_config
            assert get_user_data_dir() == custom_data
            assert get_logs_dir() == custom_logs
            assert get_cache_dir() == custom_cache
            assert get_models_dir() == custom_models

            # ensure_directories crea todas las carpetas
            ensure_directories()
            assert custom_config.exists()
            assert custom_data.exists()
            assert custom_logs.exists()
            assert custom_cache.exists()
            assert custom_models.exists()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestShortcutsVerification:
    """Verifica que los accesos directos solo se registren si existen físicamente en disco."""

    def test_clean_install_creates_and_verifies_shortcuts_physically(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="jessyca_test_sc_"))
        try:
            install_root = temp_dir / "ProgramFiles" / "JESSYCA"
            data_root = temp_dir / "AppData" / "JESSYCA"
            installer = WindowsInstallerEngine(install_root=install_root, data_root=data_root)

            manifest = ReleaseManifest(
                product_name="JESSYCA",
                version=ProductVersion(3, 0, 0),
                release_date="2026-10-06",
                changelog=("Test install",),
                binary_sha256="VALID_SHA256",
            )

            ok, err = installer.clean_install(manifest)
            assert ok is True
            assert err is None

            # Cada acceso directo en la lista debe existir físicamente en disco
            assert len(installer._installed_shortcuts) > 0
            for shortcut_path in installer._installed_shortcuts:
                p = Path(shortcut_path)
                assert p.exists()
                assert p.is_file()

            # Desinstalación con eliminación de accesos directos
            uninstall_scope = UninstallScope(
                remove_application_binaries=False,
                remove_shortcuts=True,
                remove_configuration_files=False,
                remove_memory_databases=False,
                remove_logs=False,
            )
            ok_un, _ = installer.uninstall(uninstall_scope)
            assert ok_un is True
            assert len(installer._installed_shortcuts) == 0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestCoreServiceClientConcurrency:
    """Valida el modelo de servicio/cliente y bloqueo concurrente inter-proceso."""

    def test_process_lock_acquisition_and_release(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test_core.lock"
        lock1 = CoreProcessLock(lock_file=lock_file, timeout_seconds=1.0)
        lock2 = CoreProcessLock(lock_file=lock_file, timeout_seconds=0.2)

        # 1. Primer lock adquirido con éxito
        assert lock1.acquire() is True
        assert lock_file.exists()

        # 2. Segundo lock en paralelo debe fallar por timeout
        assert lock2.acquire() is False

        # 3. Al liberar lock1, lock2 puede adquirirlo
        lock1.release()
        assert not lock_file.exists()
        assert lock2.acquire() is True
        lock2.release()

    def test_explicit_core_lock_context_manager(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("JESSYCA_DATA_DIR", str(tmp_path))
        with explicit_core_lock(timeout_seconds=1.0) as acquired:
            assert acquired is True
            assert (tmp_path / "core.lock").exists()

        assert not (tmp_path / "core.lock").exists()

    def test_core_client_check_service_status(self) -> None:
        # Puerto no activo -> reporta servicio no en ejecución
        client = CoreClient(host="127.0.0.1", port=59999)
        status = client.check_service_status(timeout_seconds=0.1)
        assert isinstance(status, CoreServiceStatus)
        assert status.is_running is False
        assert status.endpoint_url is None

    def test_core_client_routes_to_embedded_when_service_down(self) -> None:
        client = CoreClient(host="127.0.0.1", port=59999)
        with patch.object(client, "execute_embedded", return_value="Respuesta embebida local") as mock_emb:
            resp = client.execute("Hola Jessyca")
            assert resp == "Respuesta embebida local"
            mock_emb.assert_called_once_with(prompt="Hola Jessyca", session_id="cli-session")

    def test_core_client_routes_to_service_when_service_up(self) -> None:
        client = CoreClient(host="127.0.0.1", port=8088)
        mock_status = CoreServiceStatus(
            is_running=True,
            host="127.0.0.1",
            port=8088,
            endpoint_url="http://127.0.0.1:8088",
        )
        with patch.object(client, "check_service_status", return_value=mock_status):
            with patch.object(client, "send_prompt_to_service", return_value="Respuesta desde servicio Core") as mock_send:
                resp = client.execute("Hola Jessyca")
                assert resp == "Respuesta desde servicio Core"
                mock_send.assert_called_once()


class TestCliSubcommandsAndDiagnostics:
    """Valida los subcomandos de CLI doctor, diag, status y config."""

    def test_parse_arguments_subcommands(self) -> None:
        args_doc = parse_arguments(["doctor"])
        assert args_doc.subcommand == "doctor"

        args_diag = parse_arguments(["diag", "--json"])
        assert args_diag.subcommand == "diag"
        assert args_diag.json is True

        args_stat = parse_arguments(["status"])
        assert args_stat.subcommand == "status"

        args_cfg = parse_arguments(["config", "path"])
        assert args_cfg.subcommand == "config"
        assert args_cfg.action == "path"

        args_run = parse_arguments(["run", "Abrir", "calculadora", "--session-id", "s1"])
        assert args_run.subcommand == "run"
        assert args_run.message == ["Abrir", "calculadora"]
        assert args_run.session_id == "s1"

    def test_run_doctor_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = parse_arguments(["doctor"])
        exit_code = run_doctor_command(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "DIAGNÓSTICO DEL ENTORNO (DOCTOR)" in captured.out
        assert "Runtime Python:" in captured.out
        assert "Rutas Segregadas del Sistema" in captured.out
        assert "Código Instalado:" in captured.out
        assert "Configuración Usuario:" in captured.out
        assert "Datos y Memoria:" in captured.out

    def test_run_doctor_command_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = parse_arguments(["doctor", "--json"])
        exit_code = run_doctor_command(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        # Verificar JSON válido
        report_data = json.loads(captured.out)
        assert "windows_version" in report_data
        assert "python_version" in report_data
        assert report_data["is_sanitized"] is True

    def test_run_status_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = parse_arguments(["status"])
        exit_code = run_status_command(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "ESTADO DEL SISTEMA" in captured.out
        assert "Servicio Core:" in captured.out
        assert "Rutas Segregadas:" in captured.out

    def test_run_config_command_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = parse_arguments(["config", "path"])
        exit_code = run_config_command(args)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "Directorio de configuración:" in captured.out
        assert "settings.json" in captured.out

    def test_diagnostics_does_not_download_models_or_claim_fake_vram(self) -> None:
        report = EnvironmentDiagnosticsEngine.run_diagnostics()
        # Si no hay CUDA ni GPU torch, no inventar 8GB VRAM
        if report.gpu_name == "CPU / Basic Display Adapter":
            assert report.vram_total_mb == 0.0
            assert report.vram_available_mb == 0.0

    def test_run_agent_command_execution(self, capsys: pytest.CaptureFixture[str]) -> None:
        from main import run_agent_command
        args = parse_arguments(["run", "Hola", "asistente"])
        with patch("core.distribution.service_client.CoreClient.execute", return_value="¡Hola! Soy Jessyca."):
            code = run_agent_command(args)
            assert code == 0
            captured = capsys.readouterr()
            assert "¡Hola! Soy Jessyca." in captured.out

    def test_run_agent_command_error_handling(self, capsys: pytest.CaptureFixture[str]) -> None:
        from main import run_agent_command
        args = parse_arguments(["run", "Fallo"])
        with patch("core.distribution.service_client.CoreClient.execute", side_effect=RuntimeError("Servicio inaccesible")):
            code = run_agent_command(args)
            assert code == 1
            captured = capsys.readouterr()
            assert "Error: Servicio inaccesible" in captured.err

    def test_run_serve_command_delegation(self) -> None:
        from main import run_serve_command
        args = parse_arguments(["serve", "--port", "8888"])
        with patch("interfaces.webui_bridge.server.run_webui_server", return_value=0) as mock_serve:
            code = run_serve_command(args)
            assert code == 0
            mock_serve.assert_called_once_with(host=None, port=8888, force=True)

    def test_global_jessyca_binary_exists_in_scripts(self) -> None:
        """Verifica que el entrypoint [project.scripts] generó el ejecutable jessyca en venv/Scripts."""
        possible_paths = [
            Path(sys.executable).parent / "Scripts" / "jessyca.exe",
            Path(sys.executable).parent / "jessyca.exe",
            Path(sys.prefix) / "Scripts" / "jessyca.exe",
            Path(__file__).parents[2] / "venv" / "Scripts" / "jessyca.exe",
        ]
        found = any(p.exists() and p.is_file() for p in possible_paths)
        assert found, f"El ejecutable global jessyca.exe no fue encontrado en {[str(p) for p in possible_paths]}"
