"""Pruebas unitarias para modelos tipados de intención y aclaración (Fase 2)."""

import time
import unittest

from core.intent_models import IntentStatus, ParsedIntent, PendingIntent, ValidationResult


class TestIntentModels(unittest.TestCase):

    def test_parsed_intent_dict_compatibility(self) -> None:
        intent = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Abriendo bloc",
            skill="abrir_aplicacion",
            parametros={"nombre_app": "notepad"},
            pregunta_aclaratoria=None,
            parametro_faltante=None,
            candidatos=[],
            error=None,
        )

        # Acceso directo por atributo
        self.assertEqual(intent.estado, IntentStatus.CLEAR)
        self.assertEqual(intent.skill, "abrir_aplicacion")

        # Acceso por get() y __getitem__
        self.assertEqual(intent.get("skill"), "abrir_aplicacion")
        self.assertEqual(intent["skill"], "abrir_aplicacion")
        self.assertEqual(intent["parametros"]["nombre_app"], "notepad")
        self.assertIsNone(intent.get("error"))

        # Acceso con in
        self.assertIn("respuesta_hablada", intent)

        # to_dict()
        d = intent.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["estado"], "CLEAR")

    def test_pending_intent_ttl_expiration(self) -> None:
        pending = PendingIntent(
            skill_nombre="cerrar_aplicacion",
            parametros_parciales={},
            parametro_esperado="nombre_app",
            pregunta_formulada="¿Qué ventana quieres cerrar?",
            timestamp=time.time() - 70.0,  # 70s atrás
            intentos=1,
            estado_origen=IntentStatus.AMBIGUOUS,
        )
        self.assertTrue(pending.ha_expirado(ttl_segundos=60.0))

        pending_fresh = PendingIntent(
            skill_nombre="abrir_aplicacion",
            timestamp=time.time(),
        )
        self.assertFalse(pending_fresh.ha_expirado(ttl_segundos=60.0))

    def test_validation_result_structure(self) -> None:
        val = ValidationResult(
            is_valid=True,
            status=IntentStatus.CLEAR,
            skill_name="abrir_aplicacion",
            validated_parameters={"nombre_app": "notepad"},
            reason="Ok",
        )
        self.assertTrue(val.is_valid)
        self.assertEqual(val.status, IntentStatus.CLEAR)
        self.assertEqual(val.validated_parameters["nombre_app"], "notepad")


if __name__ == "__main__":
    unittest.main()
