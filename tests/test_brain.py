import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from core.brain import _extraer_json, procesar_orden


class DummySkill:
    """Abre o cierra aplicaciones de prueba."""

    def __init__(self, nombre: str, nivel_riesgo: int = 1) -> None:
        self.nombre = nombre
        self.nivel_riesgo = nivel_riesgo

    def descripcion(self) -> str:
        return f"Habilidad de prueba {self.nombre}"

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": "ok"}


SKILLS = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "cerrar_aplicacion": DummySkill("cerrar_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
    "reproducir_youtube": DummySkill("reproducir_youtube"),
}


def _respuesta_ollama(json_dict: dict[str, Any]) -> MagicMock:
    """Fabrica un mock de requests.post que devuelve el JSON indicado."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"response": json.dumps(json_dict)}
    return mock_resp


def _respuesta_ollama_markdown(json_dict: dict[str, Any]) -> MagicMock:
    """Fabrica un mock de requests.post que devuelve el JSON envuelto en bloques markdown."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"response": f"```json\n{json.dumps(json_dict)}\n```"}
    return mock_resp


class TestExtraerJson(unittest.TestCase):

    def test_json_limpio(self) -> None:
        texto = '{"respuesta_hablada": "Ok", "skill": null, "parametros": null}'
        result = _extraer_json(texto)
        self.assertIsNotNone(result)
        self.assertIsNone(result["skill"])  # type: ignore[index]

    def test_json_con_texto_extra(self) -> None:
        texto = 'Aquí va el JSON: {"respuesta_hablada": "Abriendo", "skill": "abrir_aplicacion", "parametros": {"nombre": "notepad"}} fin.'
        result = _extraer_json(texto)
        self.assertIsNotNone(result)
        self.assertEqual(result["skill"], "abrir_aplicacion")  # type: ignore[index]

    def test_json_con_bloque_markdown(self) -> None:
        texto = '```json\n{"respuesta_hablada": "Abriendo bloc", "skill": "abrir_aplicacion", "parametros": {"nombre_app": "notepad"}}\n```'
        result = _extraer_json(texto)
        self.assertIsNotNone(result)
        self.assertEqual(result["skill"], "abrir_aplicacion")  # type: ignore[index]
        self.assertEqual(result["parametros"]["nombre_app"], "notepad")  # type: ignore[index]

    def test_json_invalido_retorna_none(self) -> None:
        result = _extraer_json("esto no es json en absoluto")
        self.assertIsNone(result)


class TestProcesarOrden(unittest.TestCase):

    @patch("core.brain.requests.post")
    def test_respuesta_con_skill_valida(self, mock_post: MagicMock) -> None:
        """LLM devuelve skill existente → se retorna correctamente."""
        mock_post.return_value = _respuesta_ollama({
            "respuesta_hablada": "Voy a abrir el bloc de notas.",
            "skill": "abrir_aplicacion",
            "parametros": {"nombre_app": "bloc de notas"}
        })
        result = procesar_orden("abre el bloc de notas", SKILLS)
        self.assertIsNone(result["error"])
        self.assertEqual(result["skill"], "abrir_aplicacion")
        self.assertEqual(result["parametros"]["nombre_app"], "bloc de notas")

    @patch("core.brain.requests.post")
    def test_respuesta_markdown_gemma(self, mock_post: MagicMock) -> None:
        """gemma4:e4b devuelve respuesta envuelta en markdown → se parsea correctamente."""
        mock_post.return_value = _respuesta_ollama_markdown({
            "respuesta_hablada": "Buscando archivos PDF.",
            "skill": "buscar_archivo",
            "parametros": {"extension": "pdf"}
        })
        result = procesar_orden("busca archivos pdf", SKILLS)
        self.assertIsNone(result["error"])
        self.assertEqual(result["skill"], "buscar_archivo")
        self.assertEqual(result["parametros"]["extension"], "pdf")

    @patch("core.brain.requests.post")
    def test_respuesta_sin_skill(self, mock_post: MagicMock) -> None:
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
    def test_skill_desconocida_se_ignora(self, mock_post: MagicMock) -> None:
        """LLM sugiere skill no registrada → se descarta y skill queda None."""
        mock_post.return_value = _respuesta_ollama({
            "respuesta_hablada": "Voy a volar a la luna.",
            "skill": "skill_que_no_existe",
            "parametros": {}
        })
        result = procesar_orden("vuela a la luna", SKILLS)
        self.assertIsNone(result["skill"])

    @patch("core.brain.requests.post")
    def test_json_mal_formado_reintenta_y_falla(self, mock_post: MagicMock) -> None:
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
    def test_ollama_no_disponible(self, mock_post: MagicMock) -> None:
        """Ollama no está corriendo → error legible, sin crash."""
        result = procesar_orden("abre algo", SKILLS)
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["skill"])
        self.assertIn("Ollama", result["error"])


if __name__ == "__main__":
    unittest.main()
