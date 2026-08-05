import os
import unittest
from unittest.mock import patch, MagicMock
from audio.tts import _obtener_voz_configurada, hablar


class TestTTS(unittest.TestCase):
    def test_obtener_voz_configurada_defecto(self):
        voz = _obtener_voz_configurada("/ruta/inexistente/settings.yaml")
        self.assertEqual(voz, "es-PE-CamilaNeural")

    @patch("audio.tts._generar_audio_async")
    @patch("audio.tts._reproducir_audio")
    def test_hablar_exito(self, mock_reproducir, mock_generar):
        mock_generar.return_value = None
        mock_reproducir.return_value = None

        res = hablar("Hola jefecito")
        self.assertTrue(res)
        mock_generar.assert_called_once()
        mock_reproducir.assert_called_once()

    def test_hablar_texto_vacio(self):
        self.assertFalse(hablar(""))
        self.assertFalse(hablar("   "))

    @patch("audio.tts._generar_audio_async")
    def test_hablar_error_conexion(self, mock_generar):
        mock_generar.side_effect = Exception("Connection error")
        res = hablar("Hola test")
        self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()
