import os
import unittest
from unittest.mock import patch, MagicMock
from skills.apps import AbrirAplicacion, CerrarAplicacion, _normalizar, _buscar_en_mapeo
from skills.archivos import BuscarArchivo
from skills import SKILLS_DISPONIBLES


class TestAbrirAplicacion(unittest.TestCase):
    def test_abrir_aplicacion_sin_parametro(self):
        skill = AbrirAplicacion()
        res = skill.ejecutar({})
        self.assertFalse(res["exito"])
        self.assertIn("Debe especificar", res["mensaje"])

    def test_abrir_aplicacion_no_registrada(self):
        skill = AbrirAplicacion()
        res = skill.ejecutar({"nombre_app": "app_fantasma_inexistente"})
        self.assertFalse(res["exito"])
        self.assertIn("no está registrada", res["mensaje"])

    @patch("subprocess.Popen")
    def test_abrir_aplicacion_exito(self, mock_popen):
        skill = AbrirAplicacion()
        skill._cargar_mapeo = MagicMock(return_value={"bloc de notas": "notepad.exe"})
        res = skill.ejecutar({"nombre_app": "bloc de notas"})
        self.assertTrue(res["exito"])
        self.assertIn("lanzada con éxito", res["mensaje"])
        mock_popen.assert_called_once_with("notepad.exe", shell=True)


class TestCerrarAplicacion(unittest.TestCase):
    def test_cerrar_aplicacion_sin_parametro(self):
        skill = CerrarAplicacion()
        res = skill.ejecutar({})
        self.assertFalse(res["exito"])

    def test_cerrar_aplicacion_no_existente(self):
        skill = CerrarAplicacion()
        res = skill.ejecutar({"nombre_proceso": "proceso_falso_12345.exe"})
        self.assertFalse(res["exito"])
        self.assertIn("No se encontró ningún proceso", res["mensaje"])

    @patch("psutil.process_iter")
    def test_cerrar_aplicacion_exito(self, mock_process_iter):
        proc_mock = MagicMock()
        proc_mock.info = {'name': 'notepad.exe'}
        mock_process_iter.return_value = [proc_mock]

        skill = CerrarAplicacion()
        res = skill.ejecutar({"nombre_proceso": "notepad"})
        self.assertTrue(res["exito"])
        self.assertIn("Se cerraron 1 instancia(s)", res["mensaje"])
        proc_mock.terminate.assert_called_once()


class TestBuscarArchivo(unittest.TestCase):
    def test_buscar_archivo_sin_parametro(self):
        skill = BuscarArchivo()
        res = skill.ejecutar({})
        self.assertFalse(res["exito"])

    def test_buscar_archivo_exito(self):
        skill = BuscarArchivo()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        res = skill.ejecutar({"nombre_archivo": "test_skills.py", "ruta": current_dir})
        self.assertTrue(res["exito"])
        self.assertIn("archivos", res)
        self.assertTrue(any("test_skills.py" in path for path in res["archivos"]))

    def test_buscar_archivo_no_encontrado(self):
        skill = BuscarArchivo()
        current_dir = os.path.dirname(os.path.abspath(__file__))
        res = skill.ejecutar({"nombre_archivo": "archivo_imposible_9999.xyz", "ruta": current_dir})
        self.assertFalse(res["exito"])


class TestNormalizacion(unittest.TestCase):
    """Verifica que _normalizar y _buscar_en_mapeo toleran las variaciones que puede producir el LLM."""

    MAPEO = {
        "bloc de notas": "notepad.exe",
        "calculadora":   "calc.exe",
    }

    def test_normalizar_mayusculas(self):
        self.assertEqual(_normalizar("Bloc de Notas"), "bloc de notas")

    def test_normalizar_tildes(self):
        self.assertEqual(_normalizar("Calculàdora"), "calculadora")

    def test_normalizar_guiones_bajos(self):
        self.assertEqual(_normalizar("bloc_de_notas"), "bloc de notas")

    def test_normalizar_espacios_extra(self):
        self.assertEqual(_normalizar("  bloc   de   notas  "), "bloc de notas")

    def test_buscar_exacto(self):
        self.assertEqual(_buscar_en_mapeo("bloc de notas", self.MAPEO), "notepad.exe")

    def test_buscar_con_mayusculas_llm(self):
        """El LLM devolvió 'Bloc de Notas' → debe matchear igual."""
        self.assertEqual(_buscar_en_mapeo("Bloc de Notas", self.MAPEO), "notepad.exe")

    def test_buscar_con_guion_bajo(self):
        """El LLM puede devolver 'bloc_de_notas' → debe matchear."""
        self.assertEqual(_buscar_en_mapeo("bloc_de_notas", self.MAPEO), "notepad.exe")

    def test_buscar_sin_tildes(self):
        """Variante sin acento."""
        mapeo_con_tilde = {"calculádora": "calc.exe"}
        self.assertEqual(_buscar_en_mapeo("calculadora", mapeo_con_tilde), "calc.exe")

    def test_buscar_substring(self):
        """El LLM dice 'bloc notas' (sin 'de') → el substring 'bloc notas' está en 'bloc de notas'? No,
        pero 'bloc de notas' contiene 'bloc' → este test documenta el límite del fallback."""
        resultado = _buscar_en_mapeo("bloc notas", self.MAPEO)
        # Puede ser None (límite) o notepad.exe (si el substring lo atrapa parcial)
        # Lo importante: NO debe lanzar excepción
        self.assertIn(resultado, ["notepad.exe", None])

    def test_buscar_no_registrada(self):
        self.assertIsNone(_buscar_en_mapeo("programa_inventado", self.MAPEO))

    @patch("subprocess.Popen")
    def test_abrir_con_nombre_mayusculas_llm(self, mock_popen):
        """Integración: AbrirAplicacion tolera 'Bloc de Notas' del LLM."""
        skill = AbrirAplicacion()
        skill._cargar_mapeo = MagicMock(return_value={"bloc de notas": "notepad.exe"})
        res = skill.ejecutar({"nombre": "Bloc de Notas"})
        self.assertTrue(res["exito"])
        mock_popen.assert_called_once_with("notepad.exe", shell=True)


class TestSkillsDisponibles(unittest.TestCase):
    def test_registro_skills(self):
        self.assertIn("abrir_aplicacion", SKILLS_DISPONIBLES)
        self.assertIn("cerrar_aplicacion", SKILLS_DISPONIBLES)
        self.assertIn("buscar_archivo", SKILLS_DISPONIBLES)


if __name__ == "__main__":
    unittest.main()
