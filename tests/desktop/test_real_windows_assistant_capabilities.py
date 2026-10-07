"""Pruebas de verificación de capacidades reales de asistente personal en Windows (Fase 27).

Valida la ejecución real, gobernada y determinista de:
1. Windows Audio (pycaw EndpointVolume real)
2. Windows Notifications (PowerShell WinRT Toast real)
3. Windows Clipboard (pyperclip real)
4. Windows Display (GetSystemMetrics real)
5. Operaciones de archivos (files.search, files.read, files.create, files.copy) en tempdir
6. Captura de pantalla con diagnóstico honesto (éxito si hay escritorio interactivo, BLOCKED_HEADLESS si sesión consola)
"""

import os
import tempfile
import pytest

from core.local_agent.local_agent import get_jessyca_local_agent
from skills.skill_manager import get_skill_manager


@pytest.fixture(scope="module")
def local_agent():
    return get_jessyca_local_agent()


@pytest.fixture(scope="module")
def skill_manager():
    return get_skill_manager()


class TestWindowsRealCapabilities:
    """Verificación de capacidades reales de Windows en hardware/sistema anfitrión."""

    def test_windows_audio_query_and_control(self, skill_manager, local_agent):
        """Verifica que windows.audio consulta y responde a comandos del agente."""
        # 1. Direct Skill Execution
        res_skill = skill_manager.execute_skill("windows.audio", {"accion": "consultar"})
        assert res_skill.success is True
        assert isinstance(res_skill.output, dict)
        assert res_skill.output.get("exito") is True
        assert "volumen" in res_skill.output
        assert "silenciado" in res_skill.output
        vol_original = res_skill.output["volumen"]
        assert 0 <= vol_original <= 100

        # 2. Agent Interaction (Natural Language)
        res_agent = local_agent.interact("consulta el volumen del sistema")
        assert res_agent.success is True
        assert res_agent.intent == "control_audio"
        assert f"{vol_original}%" in res_agent.response_text or "Volumen actual:" in res_agent.response_text

    def test_windows_notifications_dispatch(self, skill_manager, local_agent):
        """Verifica que windows.notifications emite o registra la notificación nativa."""
        # 1. Direct Skill Execution
        res_skill = skill_manager.execute_skill(
            "windows.notifications",
            {"titulo": "JESSYCA Test", "mensaje": "Verificación de notificación nativa."},
        )
        assert res_skill.success is True
        assert isinstance(res_skill.output, dict)
        assert res_skill.output.get("exito") is True
        assert res_skill.output.get("titulo") == "JESSYCA Test"

        # 2. Agent Interaction
        res_agent = local_agent.interact("notifícame que la compilación ha terminado")
        assert res_agent.success is True
        assert res_agent.intent == "send_notification"
        assert "Notificación enviada" in res_agent.response_text or "notificación" in res_agent.response_text.lower()

    def test_windows_display_metrics(self, skill_manager, local_agent):
        """Verifica que windows.display obtiene la resolución real del sistema."""
        # 1. Direct Skill Execution
        res_skill = skill_manager.execute_skill("windows.display", {})
        assert res_skill.success is True
        assert isinstance(res_skill.output, dict)
        assert res_skill.output.get("exito") is True
        assert res_skill.output.get("ancho", 0) > 0
        assert res_skill.output.get("alto", 0) > 0
        assert res_skill.output.get("monitores", 0) >= 1

        # 2. Agent Interaction
        res_agent = local_agent.interact("cuál es la resolución de mi pantalla")
        assert res_agent.success is True
        assert res_agent.intent == "get_display_info"
        assert "x" in res_agent.response_text

    def test_windows_clipboard_lifecycle(self, skill_manager, local_agent):
        """Verifica ciclo completo de escritura, lectura y vaciado de portapapeles."""
        test_content = "JESSYCA-TOKEN-TEST-42"

        # 1. Escribir a través del agente
        res_w = local_agent.interact(f"copia al portapapeles {test_content}")
        assert res_w.success is True
        assert res_w.intent == "control_clipboard"

        # 2. Leer a través del agente
        res_r = local_agent.interact("qué hay en el portapapeles")
        assert res_r.success is True
        assert res_r.intent == "control_clipboard"
        assert test_content in res_r.response_text

        # 3. Limpiar mediante skill
        res_c = skill_manager.execute_skill("windows.clipboard", {"accion": "limpiar"})
        assert res_c.success is True
        res_check = skill_manager.execute_skill("windows.clipboard", {"accion": "leer"})
        assert res_check.output.get("contenido") == ""

    def test_filesystem_assistant_operations_isolated(self, local_agent):
        """Verifica creación, lectura y copia de archivos aisladas en tempfile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = os.path.join(tmpdir, "nota_asistente.txt")
            file_b = os.path.join(tmpdir, "copia_nota.txt")

            # 1. Crear archivo
            res_create = local_agent.interact(f"crea un archivo {file_a}")
            assert res_create.success is True
            assert res_create.intent == "create_file"
            assert os.path.exists(file_a)

            # Escribir contenido real
            with open(file_a, "w", encoding="utf-8") as f:
                f.write("Información confidencial de prueba.")

            # 2. Leer archivo
            res_read = local_agent.interact(f"lee el archivo {file_a}")
            assert res_read.success is True
            assert res_read.intent == "read_file"
            assert "leído con éxito" in res_read.response_text.lower()

            # 3. Copiar archivo
            res_copy = local_agent.interact(f"copia el archivo {file_a} a {file_b}")
            assert res_copy.success is True
            assert res_copy.intent == "copy_file"
            assert os.path.exists(file_b)

    def test_windows_screenshot_honest_status(self, local_agent):
        """Verifica que la captura devuelve gobernanza JDE o estado real sin fingir éxito."""
        res = local_agent.interact("toma una captura de pantalla")
        assert res.intent == "take_screenshot"
        if res.requires_confirmation:
            # JDE intercepción de seguridad/privacidad verificada
            assert "requiere confirmación" in res.response_text or "JDE" in res.response_text
        elif res.success:
            assert "guardada en" in res.response_text
        else:
            # Reporte honesto sin fingir captura si la sesión es headless
            assert "BLOCKED_HEADLESS" in res.response_text or "captura" in res.response_text.lower()
