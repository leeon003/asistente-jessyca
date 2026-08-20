"""Pruebas unitarias para IntentValidator (Fase 2)."""

import unittest
from typing import Any

from core.intent_models import IntentStatus, ParsedIntent
from core.intent_validator import IntentValidator
from skills.base_skill import BaseSkill


class DummySkill(BaseSkill):
    def __init__(self, nombre: str, nivel_riesgo: int = 1) -> None:
        super().__init__(nombre=nombre, nivel_riesgo=nivel_riesgo)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": "ok"}


SKILLS: dict[str, BaseSkill] = {
    "abrir_aplicacion": DummySkill("abrir_aplicacion"),
    "cerrar_aplicacion": DummySkill("cerrar_aplicacion"),
    "buscar_archivo": DummySkill("buscar_archivo"),
}


class TestIntentValidator(unittest.TestCase):

    def setUp(self) -> None:
        self.validator = IntentValidator(skills_disponibles=SKILLS)

    def test_clear_intent_validation(self) -> None:
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Abriendo bloc",
            skill="abrir_aplicacion",
            parametros={"nombre_app": "notepad"},
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.status, IntentStatus.CLEAR)
        self.assertEqual(res.skill_name, "abrir_aplicacion")
        self.assertEqual(res.validated_parameters["nombre_app"], "notepad")

    def test_incomplete_intent_missing_param(self) -> None:
        # LLM marcó CLEAR pero falta el parámetro obligatorio nombre_app
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Abriendo",
            skill="abrir_aplicacion",
            parametros={},  # Falta nombre_app
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, IntentStatus.INCOMPLETE)
        self.assertEqual(res.missing_parameter, "nombre_app")
        self.assertIn("¿Qué aplicación", res.clarification_prompt or "")

    def test_ambiguous_parameter_value(self) -> None:
        # El parámetro contiene una referencia ambigua ("eso")
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Cerrando eso",
            skill="cerrar_aplicacion",
            parametros={"nombre_app": "eso"},
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, IntentStatus.AMBIGUOUS)
        self.assertIn("¿Qué ventana o aplicación", res.clarification_prompt or "")

    def test_unsupported_skill(self) -> None:
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Controlando luces",
            skill="controlar_luces_hogar",
            parametros={"luz": "salon"},
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, IntentStatus.UNSUPPORTED)

    def test_conversational_without_skill(self) -> None:
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="¡Hola! ¿En qué te ayudo?",
            skill=None,
            parametros=None,
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.status, IntentStatus.CLEAR)
        self.assertIsNone(res.skill_name)

    def test_invalid_intent_error(self) -> None:
        intent = ParsedIntent(
            estado=IntentStatus.INVALID,
            respuesta_hablada="Error",
            error="JSON roto",
        )
        res = self.validator.validate(intent, SKILLS)
        self.assertFalse(res.is_valid)
        self.assertEqual(res.status, IntentStatus.INVALID)


if __name__ == "__main__":
    unittest.main()
