"""Pruebas de integración para el ciclo de diálogo, aclaración y revalidación de seguridad en Orquestador (Fase 2)."""

import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from core.intent_models import IntentStatus, ParsedIntent
from core.orquestador import (
    clear_pending_intent,
    ejecutar_orden_texto,
    get_pending_intent,
    set_pending_intent,
)
from skills.base_skill import BaseSkill


class DummySafeSkill(BaseSkill):
    """Skill de bajo riesgo (nivel 1, auto-ejecutable)."""

    def __init__(self, nombre: str) -> None:
        super().__init__(nombre=nombre, nivel_riesgo=1)
        self.invocaciones: list[dict[str, Any]] = []

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.invocaciones.append(parametros)
        return {"exito": True, "mensaje": f"{self.nombre} ejecutado con éxito."}


class DummyDangerousSkill(BaseSkill):
    """Skill de riesgo medio/alto (nivel 2, requiere confirmación)."""

    def __init__(self, nombre: str) -> None:
        super().__init__(nombre=nombre, nivel_riesgo=2)
        self.invocaciones: list[dict[str, Any]] = []

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        self.invocaciones.append(parametros)
        return {"exito": True, "mensaje": f"{self.nombre} ejecutado con éxito."}


class TestOrquestadorClarification(unittest.TestCase):

    def setUp(self) -> None:
        clear_pending_intent()
        self.safe_skill = DummySafeSkill("abrir_aplicacion")
        self.danger_skill = DummyDangerousSkill("cerrar_aplicacion")
        self.skills = {
            "abrir_aplicacion": self.safe_skill,
            "cerrar_aplicacion": self.danger_skill,
        }

    def tearDown(self) -> None:
        clear_pending_intent()

    @patch("core.orquestador.procesar_orden")
    def test_direct_clear_intent_executes(self, mock_brain: MagicMock) -> None:
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Abriendo el bloc de notas.",
            skill="abrir_aplicacion",
            parametros={"nombre_app": "notepad"},
        )
        resp = ejecutar_orden_texto("abre bloc de notas", self.skills)
        self.assertIn("Abriendo", resp)
        self.assertEqual(len(self.safe_skill.invocaciones), 1)
        self.assertEqual(self.safe_skill.invocaciones[0]["nombre_app"], "notepad")
        self.assertIsNone(get_pending_intent())

    @patch("core.orquestador.procesar_orden")
    def test_incomplete_intent_asks_clarification_and_executes_on_second_turn(
        self, mock_brain: MagicMock
    ) -> None:
        # Turno 1: Usuario dice "abre...", Brain devuelve INCOMPLETE
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.INCOMPLETE,
            respuesta_hablada="¿Qué aplicación deseas abrir?",
            skill="abrir_aplicacion",
            parametros={},
            pregunta_aclaratoria="¿Qué aplicación quieres que abra?",
            parametro_faltante="nombre_app",
        )
        resp1 = ejecutar_orden_texto("abre...", self.skills)
        self.assertEqual(resp1, "¿Qué aplicación quieres que abra?")
        self.assertEqual(len(self.safe_skill.invocaciones), 0)

        pending = get_pending_intent()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.skill_nombre, "abrir_aplicacion")  # type: ignore[union-attr]
        self.assertEqual(pending.parametro_esperado, "nombre_app")  # type: ignore[union-attr]

        # Turno 2: Usuario responde "notepad", Brain resuelve con contexto a CLEAR
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Abriendo el bloc de notas.",
            skill="abrir_aplicacion",
            parametros={"nombre_app": "notepad"},
        )
        resp2 = ejecutar_orden_texto("notepad", self.skills)
        self.assertIn("Abriendo", resp2)
        self.assertEqual(len(self.safe_skill.invocaciones), 1)
        self.assertIsNone(get_pending_intent())

    @patch("core.orquestador.procesar_orden")
    def test_explicit_cancellation_during_clarification(self, mock_brain: MagicMock) -> None:
        # Turno 1: Generar estado pendiente
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.AMBIGUOUS,
            respuesta_hablada="¿Qué ventana quieres cerrar?",
            skill="cerrar_aplicacion",
            parametros={"nombre_app": "eso"},
            pregunta_aclaratoria="¿Qué ventana quieres cerrar?",
        )
        resp1 = ejecutar_orden_texto("cierra eso", self.skills)
        self.assertEqual(resp1, "¿Qué ventana quieres cerrar?")
        self.assertIsNotNone(get_pending_intent())

        # Turno 2: Usuario dice "cancelar"
        resp2 = ejecutar_orden_texto("cancelar", self.skills)
        self.assertEqual(resp2, "De acuerdo, cancelé la acción.")
        self.assertEqual(len(self.danger_skill.invocaciones), 0)
        self.assertIsNone(get_pending_intent())

    @patch("core.orquestador.procesar_orden")
    def test_anti_loop_max_two_clarification_attempts(self, mock_brain: MagicMock) -> None:
        # Turno 1: Genera pendiente
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.INCOMPLETE,
            respuesta_hablada="¿Qué app?",
            skill="abrir_aplicacion",
            parametros={},
            pregunta_aclaratoria="¿Qué app?",
            parametro_faltante="nombre_app",
        )
        ejecutar_orden_texto("abre", self.skills)

        # Turno 2: Intento 1 de aclaración (sigue incompleto)
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.INCOMPLETE,
            respuesta_hablada="¿Cuál exactamente?",
            skill="abrir_aplicacion",
            parametros={},
            pregunta_aclaratoria="¿Cuál exactamente?",
            parametro_faltante="nombre_app",
        )
        resp2 = ejecutar_orden_texto("algo", self.skills)
        self.assertEqual(resp2, "¿Cuál exactamente?")

        # Turno 3: Intento 2 de aclaración (sigue incompleto) -> supera límite
        resp3 = ejecutar_orden_texto("no se", self.skills)
        self.assertIn("No pude determinar la opción solicitada tras dos intentos", resp3)
        self.assertIsNone(get_pending_intent())

    @patch("core.orquestador.procesar_orden")
    def test_ttl_expiration_discards_stale_intent(self, mock_brain: MagicMock) -> None:
        # Generar pendiente expirado
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.INCOMPLETE,
            respuesta_hablada="¿Qué app?",
            skill="abrir_aplicacion",
            parametros={},
            pregunta_aclaratoria="¿Qué app?",
            parametro_faltante="nombre_app",
        )
        ejecutar_orden_texto("abre", self.skills)

        # Forzar timestamp antiguo (> 60s)
        pending = get_pending_intent()
        assert pending is not None
        pending.timestamp = time.time() - 75.0
        set_pending_intent(pending)

        # Turno siguiente: Llega nueva orden independiente
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="¡Hola! ¿Cómo estás?",
            skill=None,
            parametros=None,
        )
        resp = ejecutar_orden_texto("hola", self.skills)
        self.assertIn("Hola", resp)
        self.assertIsNone(get_pending_intent())

    @patch("core.orquestador.confirmar_con_usuario", return_value=True)
    @patch("core.orquestador.procesar_orden")
    def test_security_revalidation_after_clarification(
        self, mock_brain: MagicMock, mock_confirm: MagicMock
    ) -> None:
        # Turno 1: "cierra..." -> Incomplete
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.INCOMPLETE,
            respuesta_hablada="¿Qué proceso quieres cerrar?",
            skill="cerrar_aplicacion",
            parametros={},
            pregunta_aclaratoria="¿Qué proceso quieres cerrar?",
            parametro_faltante="nombre_proceso",
        )
        ejecutar_orden_texto("cierra", self.skills)

        # Turno 2: "notepad" -> Brain resuelve a CLEAR para cerrar_aplicacion (riesgo 2)
        mock_brain.return_value = ParsedIntent(
            estado=IntentStatus.CLEAR,
            respuesta_hablada="Cerrando notepad.",
            skill="cerrar_aplicacion",
            parametros={"nombre_app": "notepad"},
        )
        resp = ejecutar_orden_texto("notepad", self.skills)
        # Debe haber llamado a confirmar_con_usuario por ser riesgo 2
        self.assertTrue(mock_confirm.called)
        self.assertIn("Cerrando", resp)
        self.assertEqual(len(self.danger_skill.invocaciones), 1)


if __name__ == "__main__":
    unittest.main()
