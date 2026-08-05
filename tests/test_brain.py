import json
import unittest
from unittest.mock import patch, MagicMock
from skills.base_skill import BaseSkill
from core.brain import procesar_orden, _extraer_json


class DummySkill(BaseSkill):
    """Abre o cierra aplicaciones de prueba."""
    def __init__(self, nombre):
        super().__init__(nombre=nombre, nivel_riesgo=1)
    def ejecutar(self, parametros):
        return {"exito": True, "mensaje": "ok"}


SKILLS = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
}


def _respuesta_ollama(json_dict: dict) -> MagicMock:
    """Fabrica un mock de requests.post que devuelve el JSON indicado."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"response": json.dumps(json_dict)}
    return mock_resp


class TestExtraerJson(unittest.TestCase):
    def test_json_limpio(self):
        texto = '{"respuesta_hablada": "Ok", "skill": null, "parametros": null}'
        result = _extraer_json(texto)
        self.assertIsNotNone(result)
        self.assertIsNone(result["skill"])

    def test_json_con_texto_extra(self):
        texto = 'Aquí va el JSON: {"respuesta_hablada": "Abriendo", "skill": "abrir_aplicacion", "parametros": {"nombre": "notepad"}} fin.'
        result = _extraer_json(texto)
        self.assertIsNotNone(result)
        self.assertEqual(result["skill"], "abrir_aplicacion")

    def test_json_invalido_retorna_none(self):
        result = _extraer_json("esto no es json en absoluto")
        self.assertIsNone(result)


class TestProcesarOrden(unittest.TestCase):

    @patch("core.brain.requests.post")
    def test_respuesta_con_skill_valida(self, mock_post):
        """LLM devuelve skill existente → se retorna correctamente."""
        mock_post.return_value = _respuesta_ollama({
            "respuesta_hablada": "Voy a abrir el bloc de notas.",
            "skill": "abrir_aplicacion",
            "parametros": {"nombre": "bloc de notas"}
        })
        result = procesar_orden("abre el bloc de notas", SKILLS)
        self.assertIsNone(result["error"])
        self.assertEqual(result["skill"], "abrir_aplicacion")
        self.assertEqual(result["parametros"]["nombre"], "bloc de notas")

    @patch("core.brain.requests.post")
    def test_respuesta_sin_skill(self, mock_post):
        """LLM responde conversacionalmente sin skill → skill es None."""
        mock_post.return_value = _respuesta_ollama({
            "respuesta_hablada": "¡Hola! Estoy aquí para ayudarte.",
            "skill": None,
            "parametros": None
        })
        result = procesar_orden("hola", SKILLS)
        self.assertIsNone(result["error"])
        self.assertIsNone(result["skill"])
        self.assertIn("Hola", result["respuesta_hablada"])

    @patch("core.brain.requests.post")
    def test_skill_desconocida_se_ignora(self, mock_post):
        """LLM sugiere skill no registrada → se descarta y skill queda None."""
        mock_post.return_value = _respuesta_ollama({
            "respuesta_hablada": "Voy a volar a la luna.",
            "skill": "skill_que_no_existe",
            "parametros": {}
        })
        result = procesar_orden("vuela a la luna", SKILLS)
        self.assertIsNone(result["skill"])

    @patch("core.brain.requests.post")
    def test_json_mal_formado_reintenta_y_falla(self, mock_post):
        """Ollama devuelve texto no parseable ambas veces → error legible."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": "Aquí va la respuesta pero sin JSON válido..."}
        mock_post.return_value = mock_resp

        result = procesar_orden("algo confuso", SKILLS)
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["skill"])
        self.assertIn("interpretar", result["respuesta_hablada"])

    @patch("core.brain.requests.post", side_effect=__import__("requests").exceptions.ConnectionError)
    def test_ollama_no_disponible(self, mock_post):
        """Ollama no está corriendo → error legible, sin crash."""
        result = procesar_orden("abre algo", SKILLS)
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["skill"])
        self.assertIn("Ollama", result["error"])


if __name__ == "__main__":
    unittest.main()
