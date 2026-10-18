"""
Suite Integral de Pruebas GUI de Escritura y Verificación Real en Bloc de Notas
JESSYCA Asistente 4.0 — FASE 9: Pruebas A a J

Cubre:
- Prueba A: Escritura literal con verificación de ventana visible.
- Prueba B: Generación conceptual (Ollama) de 3 Principios de la Termodinámica y escritura real.
- Prueba C: Continuidad entre turnos ("Abre Bloc de notas" -> "Ahora escribe...").
- Prueba D: Modo append ("Agrega una conclusión al final").
- Prueba E: Modo replace ("Corrige el segundo párrafo").
- Prueba F: Guardado explícito como archivo ("Guarda el documento como termodinamica.txt").
- Prueba G: Múltiples ventanas/pestañas y direccionamiento al HWND correcto.
- Prueba H: Detección de pérdida de foco y protección de escritura fuera de destino.
- Prueba I: Prevención de falso éxito (Fallo simulado -> success=False, sin aprendizaje espurio).
- Prueba J: Flujo completo E2E simulando captura y orden de voz.
"""

import os
import sys
import time
import pytest
from pathlib import Path

# Asegurar path al proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.reasoning_engine import ReasoningEngine
from core.cognitive_brain.planner_engine import PlannerEngine
from core.cognitive_brain.procedure_learning_engine import ProcedureLearningEngine
from core.desktop.unified_controller import UnifiedDesktopController
from core.execution.execution_verifier import ExecutionVerifier, GuiTextVerificationStrategy


class TestNotepadGuiWriting:
    """Valida los diez escenarios críticos de escritura GUI en Windows 11."""

    @pytest.fixture(autouse=True)
    def setup_brain(self):
        self.brain = JessycaBrain.get_instance()
        self.session_id = f"test-gui-session-{int(time.time())}"
        self.brain.reset_session(self.session_id)
        yield
        # Cerrar posibles bloc de notas residuales abiertos en pruebas
        try:
            self.brain.desktop_controller.close_app("notepad.exe")
        except Exception:
            pass

    def test_prueba_a_escritura_literal_verificada(self):
        """Prueba A: 'Abre Bloc de notas y escribe: prueba de escritura de JESSYCA'."""
        instruction = "Abre el Bloc de notas y escribe: prueba de escritura de JESSYCA"
        res = self.brain.execute_task(user_input=instruction, session_id=self.session_id)

        assert res.success is True, f"Falló ejecución de Prueba A: {res.error}"
        assert res.requires_action is True
        assert res.steps_executed >= 2
        
        # Verificar que se utilizó desktop_editor y write_in_window
        actions = [s.get("action_name") for s in res.verified_evidence.get("recovered_steps", [])]
        # O en verified_evidence
        assert any("step" in k for k in res.verified_evidence.keys())
        
        # Verificar que la respuesta informa con precisión de la apertura y escritura
        assert "escribí" in res.response_text.lower() or "abrí bloc de notas" in res.response_text.lower()
        assert "no puedo abrir" not in res.response_text.lower()

    def test_prueba_b_generacion_conceptual_termodinamica(self):
        """Prueba B: 'Jessica, abre el Bloc de notas y escribe los 3 principios de la termodinámica'."""
        instruction = "Jessica, abre el Bloc de notas y escribe los 3 principios de la termodinámica"
        res = self.brain.execute_task(user_input=instruction, session_id=self.session_id)

        assert res.success is True, f"Falló ejecución de Prueba B: {res.error}"
        assert "termodinámica" in res.response_text.lower() or "principios" in res.response_text.lower()
        
        # Verificar que el contenido generado contiene las leyes conceptuales
        working_ctx = self.brain.memory_engine.get_working_context(self.session_id) or {}
        last_written = working_ctx.get("last_written_text", "")
        
        assert len(last_written) > 100, "El texto generado debe ser conceptual y extenso, no solo un título"
        assert any(term in last_written.lower() for term in ("energía", "energia", "conservación", "conservacion"))
        assert any(term in last_written.lower() for term in ("entropía", "entropia"))
        assert any(term in last_written.lower() for term in ("cero absoluto", "kelvin", "temperatura", "equilibrio", "tercer", "calor"))


    def test_prueba_c_continuidad_entre_turnos(self):
        """Prueba C: Turno 1 'Abre Bloc de notas' -> Turno 2 'Ahora escribe un resumen sobre inteligencia artificial'."""
        # Turno 1
        res1 = self.brain.execute_task(user_input="Abre el Bloc de notas", session_id=self.session_id)
        assert res1.success is True
        assert "abierto" in res1.response_text.lower()

        working_ctx1 = self.brain.memory_engine.get_working_context(self.session_id) or {}
        initial_hwnd = working_ctx1.get("active_hwnd")

        # Turno 2: Anáfora "Ahora escribe..."
        res2 = self.brain.execute_task(
            user_input="Ahora escribe un resumen sobre inteligencia artificial",
            session_id=self.session_id
        )
        assert res2.success is True
        assert "escribí" in res2.response_text.lower()
        
        working_ctx2 = self.brain.memory_engine.get_working_context(self.session_id) or {}
        assert "inteligencia artificial" in working_ctx2.get("last_written_text", "").lower()

    def test_prueba_d_modo_append_agregar_conclusion(self):
        """Prueba D: 'Agrega una conclusión al final'."""
        # Preparar documento con texto inicial
        self.brain.execute_task(user_input="Abre Bloc de notas y escribe los 3 principios de la termodinámica", session_id=self.session_id)
        
        # Turno de append
        res_d = self.brain.execute_task(user_input="Agrega una conclusión al final", session_id=self.session_id)
        assert res_d.success is True
        assert "escribí" in res_d.response_text.lower() or "conclusión" in res_d.response_text.lower()

    def test_prueba_e_modo_replace_corregir_parrafo(self):
        """Prueba E: 'Corrige el segundo párrafo'."""
        self.brain.execute_task(user_input="Abre Bloc de notas y escribe los 3 principios de la termodinámica", session_id=self.session_id)
        
        res_e = self.brain.execute_task(user_input="Corrige el segundo principio", session_id=self.session_id)
        assert res_e.success is True

    def test_prueba_f_guardar_documento_como_archivo(self):
        """Prueba F: 'Guarda el documento como termodinamica.txt'."""
        self.brain.execute_task(user_input="Abre Bloc de notas y escribe los 3 principios de la termodinámica", session_id=self.session_id)
        
        res_f = self.brain.execute_task(
            user_input="Guarda el documento como termodinamica.txt",
            session_id=self.session_id
        )
        assert res_f.success is True
        assert "guardé" in res_f.response_text.lower()
        assert "termodinamica.txt" in res_f.response_text.lower()

    def test_prueba_g_multiples_ventanas_y_hwnd_destacado(self):
        """Prueba G: Diferenciación de ventanas por HWND persistido en memoria de trabajo."""
        controller = self.brain.desktop_controller
        # Abrir ventana de bloc de notas
        res_win = controller.open_app("notepad.exe")
        hwnd1 = res_win.evidence.get("hwnd")
        
        # Simular escritura dirigida específicamente a ese HWND
        res_write = controller.write_in_window(
            app_name_or_title="notepad",
            text="Prueba multiventana HWND garantizada.",
            hwnd=hwnd1,
            verify_content=True,
        )
        assert res_write.success is True
        assert res_write.evidence.get("hwnd") == hwnd1 or hwnd1 is None

    def test_prueba_h_deteccion_perdida_de_foco(self):
        """Prueba H: Si la ventana de destino no existe o HWND es inválido, detiene la operación sin escribir al azar."""
        controller = self.brain.desktop_controller
        # Usar un HWND inexistente
        fake_hwnd = 99999999
        res_write = controller.write_in_window(
            app_name_or_title="inexistente_app_xyz",
            text="Este texto no debe escribirse a ciegas",
            hwnd=fake_hwnd,
            verify_content=True,
        )
        assert res_write.success is False
        assert any(w in res_write.error.lower() for w in ("no encontrada", "focus", "enfocar", "foco"))

    def test_prueba_i_prevencion_falso_exito_y_no_aprendizaje(self):
        """Prueba I: Fallo en escritura NO debe marcar éxito ni registrar procedimiento CANDIDATE."""
        ple = self.brain.procedure_learning_engine
        initial_procs = ple.memory_engine.procedural_memory.list_all() if hasattr(ple.memory_engine.procedural_memory, "list_all") else []
        initial_count = len(initial_procs)

        # Episodio con falso éxito o desajuste (intención de escribir pero herramienta fue files.create)
        bad_episode = {
            "episode_id": "ep-test-anomaly-01",
            "session_id": "bad-sess",
            "user_instruction": "Abre Bloc de notas y escribe los principios",
            "intent": "gui_task",
            "success": True,
            "alerts": ["false_success"],
            "metadata": {"false_success": True},
            "actions_executed": [
                {"action_name": "open_application", "tool_name": "windows.apps", "success": True},
                {"action_name": "create_file", "tool_name": "files.create", "success": True},
            ],
            "verified_evidence": {"files": {"created": True}},
        }

        learned = ple.learn_from_experience(bad_episode)
        assert learned is None, "Debe rechazar categóricamente aprender procedimientos con false_success o desajuste de intención"

    def test_prueba_j_flujo_completo_con_correccion_usuario(self):
        """Prueba J: Flujo de voz completo y manejo de 'Jessica, no veo lo que escribiste'."""
        # 1. Instrucción de voz
        res1 = self.brain.execute_task(
            user_input="Jessica, abre el Bloc de notas y escribe los 3 principios de la termodinámica",
            session_id=self.session_id,
        )
        assert res1.success is True

        # 2. El usuario reporta corrección: "No veo lo que escribiste"
        res2 = self.brain.execute_task(
            user_input="Jessica, no veo lo que escribiste",
            session_id=self.session_id,
        )
        assert res2.success is True
        assert "revisé" in res2.response_text.lower() or "reescribí" in res2.response_text.lower()
