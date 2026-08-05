import unittest
from unittest.mock import patch, MagicMock
from skills.base_skill import BaseSkill
from core.orquestador import ejecutar_orden_texto


class DummySkillBaja(BaseSkill):
    """Skill de prueba de riesgo bajo (nivel 1)."""
    def __init__(self):
        super().__init__(nombre="skill_baja", nivel_riesgo=1)
    def ejecutar(self, parametros):
        return {"exito": True, "mensaje": "Acción ejecutada OK"}


class DummySkillMedia(BaseSkill):
    """Skill de prueba de riesgo medio (nivel 2)."""
    def __init__(self):
        super().__init__(nombre="skill_media", nivel_riesgo=2)
    def ejecutar(self, parametros):
        return {"exito": True, "mensaje": "Acción media ejecutada"}


SKILLS_TEST = {
    "skill_baja": DummySkillBaja(),
    "skill_media": DummySkillMedia(),
}


class TestOrquestador(unittest.TestCase):

    @patch("core.orquestador.procesar_orden")
    def test_respuesta_conversacional_sin_skill(self, mock_brain):
        """Cerebro responde sin skill → orquestador retorna respuesta_hablada directamente."""
        mock_brain.return_value = {
            "respuesta_hablada": "¡Hola! Estoy aquí.",
            "skill": None,
            "parametros": None,
            "error": None,
        }
        respuesta = ejecutar_orden_texto("hola", SKILLS_TEST)
        self.assertEqual(respuesta, "¡Hola! Estoy aquí.")

    @patch("core.orquestador.procesar_orden")
    def test_skill_nivel1_se_ejecuta_sin_confirmacion(self, mock_brain):
        """Skill de riesgo 1 se ejecuta automáticamente sin pedir confirmación."""
        mock_brain.return_value = {
            "respuesta_hablada": "Ejecutando skill baja.",
            "skill": "skill_baja",
            "parametros": {},
            "error": None,
        }
        respuesta = ejecutar_orden_texto("haz algo simple", SKILLS_TEST)
        self.assertEqual(respuesta, "Ejecutando skill baja.")

    @patch("core.orquestador.confirmar_con_usuario", return_value=True)
    @patch("core.orquestador.procesar_orden")
    def test_skill_nivel2_confirmada_se_ejecuta(self, mock_brain, mock_confirmar):
        """Skill de riesgo 2 confirmada por el usuario → se ejecuta."""
        mock_brain.return_value = {
            "respuesta_hablada": "Voy a cerrar la app.",
            "skill": "skill_media",
            "parametros": {"nombre": "notepad"},
            "error": None,
        }
        respuesta = ejecutar_orden_texto("cierra notepad", SKILLS_TEST)
        mock_confirmar.assert_called_once()
        self.assertEqual(respuesta, "Voy a cerrar la app.")

    @patch("core.orquestador.confirmar_con_usuario", return_value=False)
    @patch("core.orquestador.procesar_orden")
    def test_skill_nivel2_cancelada(self, mock_brain, mock_confirmar):
        """Skill de riesgo 2 rechazada por el usuario → se cancela."""
        mock_brain.return_value = {
            "respuesta_hablada": "Voy a cerrar la app.",
            "skill": "skill_media",
            "parametros": {"nombre": "notepad"},
            "error": None,
        }
        respuesta = ejecutar_orden_texto("cierra notepad", SKILLS_TEST)
        self.assertIn("cancelé", respuesta)

    @patch("core.orquestador.procesar_orden")
    def test_skill_desconocida_retorna_mensaje_claro(self, mock_brain):
        """Cerebro pide skill que no existe en el registro → mensaje amigable."""
        mock_brain.return_value = {
            "respuesta_hablada": "Voy a volar.",
            "skill": "volar_a_la_luna",
            "parametros": {},
            "error": None,
        }
        respuesta = ejecutar_orden_texto("vuela a la luna", SKILLS_TEST)
        self.assertIn("volar_a_la_luna", respuesta)

    @patch("core.orquestador.procesar_orden")
    def test_error_en_cerebro_retorna_mensaje_claro(self, mock_brain):
        """Error en Cerebro (Ollama caído) → mensaje amigable, sin crash."""
        mock_brain.return_value = {
            "respuesta_hablada": "No puedo conectarme a Ollama.",
            "skill": None,
            "parametros": None,
            "error": "Ollama no disponible en http://localhost:11434.",
        }
        respuesta = ejecutar_orden_texto("abre algo", SKILLS_TEST)
        self.assertIn("Ollama", respuesta)

    @patch("core.orquestador.procesar_orden")
    def test_skill_falla_retorna_mensaje_error(self, mock_brain):
        """Skill ejecutada pero retorna exito=False → se informa al usuario."""
        mock_brain.return_value = {
            "respuesta_hablada": "Buscando el archivo.",
            "skill": "skill_baja",
            "parametros": {},
            "error": None,
        }
        # Parcheamos ejecutar para simular fallo
        with patch.object(SKILLS_TEST["skill_baja"], "ejecutar",
                          return_value={"exito": False, "mensaje": "Archivo no encontrado."}):
            respuesta = ejecutar_orden_texto("busca algo", SKILLS_TEST)
        self.assertEqual(respuesta, "Archivo no encontrado.")


if __name__ == "__main__":
    unittest.main()
