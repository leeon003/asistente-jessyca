"""Pruebas unitarias para Brain con soporte de evaluación de estados y aclaración (Fase 2)."""

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from core.brain import procesar_orden
from core.intent_models import IntentStatus, PendingIntent
from skills.base_skill import BaseSkill


class DummySkill(BaseSkill):
    def __init__(self, nombre: str) -> None:
        super().__init__(nombre=nombre, nivel_riesgo=1)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": "ok"}


SKILLS = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "cerrar_aplicacion": DummySkill("cerrar_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
}


def _respuesta_ollama(json_dict: dict[str, Any]) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"response": json.dumps(json_dict)}
    return mock_resp


class TestBrainClarification(unittest.TestCase):

    @patch("core.brain.requests.post")
    def test_brain_returns_clear_intent(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _respuesta_ollama({
            "estado": "CLEAR",
            "respuesta_hablada": "Abriendo el bloc de notas.",
            "skill": "abrir_aplicacion",
            "parametros": {"nombre_app": "bloc de notas"},
        })
        res = procesar_orden("abre el bloc de notas", SKILLS)
        self.assertEqual(res.estado, IntentStatus.CLEAR)
        self.assertEqual(res.skill, "abrir_aplicacion")
        self.assertIsNotNone(res.parametros)
        self.assertEqual(res.parametros["nombre_app"], "bloc de notas")  # type: ignore[index]

    @patch("core.brain.requests.post")
    def test_brain_returns_incomplete_intent(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _respuesta_ollama({
            "estado": "INCOMPLETE",
            "respuesta_hablada": "¿Qué aplicación deseas abrir?",
            "skill": "abrir_aplicacion",
            "parametros": {},
            "pregunta_aclaratoria": "¿Qué aplicación quieres que abra?",
            "parametro_faltante": "nombre_app",
        })
        res = procesar_orden("abre...", SKILLS)
        self.assertEqual(res.estado, IntentStatus.INCOMPLETE)
        self.assertEqual(res.skill, "abrir_aplicacion")
        self.assertEqual(res.parametro_faltante, "nombre_app")
        self.assertIn("¿Qué aplicación", res.pregunta_aclaratoria or "")

    @patch("core.brain.requests.post")
    def test_brain_returns_ambiguous_intent(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _respuesta_ollama({
            "estado": "AMBIGUOUS",
            "respuesta_hablada": "¿Qué ventana quieres cerrar?",
            "skill": "cerrar_aplicacion",
            "parametros": {"nombre_app": "eso"},
            "pregunta_aclaratoria": "¿Qué ventana quieres cerrar?",
            "candidatos": ["notepad", "chrome"],
        })
        res = procesar_orden("cierra eso", SKILLS)
        self.assertEqual(res.estado, IntentStatus.AMBIGUOUS)
        self.assertEqual(res.skill, "cerrar_aplicacion")
        self.assertEqual(res.candidatos, ["notepad", "chrome"])

    @patch("core.brain.requests.post")
    def test_brain_resolves_with_clarification_context(self, mock_post: MagicMock) -> None:
        mock_post.return_value = _respuesta_ollama({
            "estado": "CLEAR",
            "respuesta_hablada": "Cerrando Google Chrome.",
            "skill": "cerrar_aplicacion",
            "parametros": {"nombre_app": "chrome"},
        })
        context = PendingIntent(
            skill_nombre="cerrar_aplicacion",
            parametros_parciales={},
            parametro_esperado="nombre_app",
            pregunta_formulada="¿Qué ventana quieres cerrar?",
            intentos=1,
            estado_origen=IntentStatus.AMBIGUOUS,
        )
        res = procesar_orden("chrome", SKILLS, contexto_aclaracion=context)
        self.assertEqual(res.estado, IntentStatus.CLEAR)
        self.assertEqual(res.skill, "cerrar_aplicacion")
        self.assertIsNotNone(res.parametros)
        self.assertEqual(res.parametros["nombre_app"], "chrome")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
