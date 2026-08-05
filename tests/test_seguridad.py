import os
import unittest
from skills.base_skill import BaseSkill
from core.seguridad import requiere_confirmacion, registrar_auditoria, LOG_FILE


class DummySkill(BaseSkill):
    """Skill de prueba para testear niveles de seguridad."""

    def __init__(self, nombre: str, nivel_riesgo: int):
        super().__init__(nombre=nombre, nivel_riesgo=nivel_riesgo)

    def ejecutar(self, parametros: dict) -> dict:
        return {"exito": True, "mensaje": "Ejecutado"}


class TestSeguridad(unittest.TestCase):
    def test_requiere_confirmacion_nivel_1_bajo(self):
        """Verifica que el nivel 1 (bajo) NO requiere confirmación."""
        skill = DummySkill(nombre="skill_baja", nivel_riesgo=1)
        self.assertFalse(requiere_confirmacion(skill))

    def test_requiere_confirmacion_nivel_2_medio(self):
        """Verifica que el nivel 2 (medio) SI requiere confirmación."""
        skill = DummySkill(nombre="skill_media", nivel_riesgo=2)
        self.assertTrue(requiere_confirmacion(skill))

    def test_requiere_confirmacion_nivel_3_alto(self):
        """Verifica que el nivel 3 (alto) SI requiere confirmación."""
        skill = DummySkill(nombre="skill_alta", nivel_riesgo=3)
        self.assertTrue(requiere_confirmacion(skill))

    def test_registrar_auditoria_logs_correctly(self):
        """Verifica que registrar_auditoria genera entradas en logs/auditoria.log para nivel >= 2."""
        registrar_auditoria("skill_test", {"param": "valor"}, confirmado=True, nivel_riesgo=2)
        registrar_auditoria("skill_test_cancel", {}, confirmado=False, nivel_riesgo=3)
        
        self.assertTrue(os.path.exists(LOG_FILE))
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Skill: skill_test", content)
            self.assertIn("CONFIRMADO", content)
            self.assertIn("CANCELADO", content)


if __name__ == "__main__":
    unittest.main()
