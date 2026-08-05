import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from audio.wake_word import (
    esperar_wake_word,
    _normalizar_texto,
    _obtener_wake_word_configurada,
    _es_coincidencia_wake_word
)


class TestWakeWord(unittest.TestCase):
    def test_normalizar_texto(self):
        self.assertEqual(_normalizar_texto("¡Hola Jessyca!"), "hola jessyca")
        self.assertEqual(_normalizar_texto("Jésica"), "jesica")

    def test_obtener_wake_word_configurada(self):
        words = _obtener_wake_word_configurada()
        self.assertIn("jessyca", words)
        self.assertIn("jessica", words)
        self.assertIn("esica", words)
        self.assertIn("jesika", words)

    def test_es_coincidencia_wake_word_exacta_y_difusa(self):
        words = {"jessyca", "jessica", "yesica", "jesica"}

        match_exact, score = _es_coincidencia_wake_word("hola jessyca", words)
        self.assertTrue(match_exact)
        self.assertEqual(score, 1.0)

        match_jessica, _ = _es_coincidencia_wake_word("jessica por favor", words)
        self.assertTrue(match_jessica)

        # "y algo" debe retornar False (evitar falso positivo)
        match_y_algo, score_algo = _es_coincidencia_wake_word("y algo", words)
        self.assertFalse(match_y_algo)
        self.assertLess(score_algo, 0.85)

        match_no, score_no = _es_coincidencia_wake_word("hola mundo como estas", words)
        self.assertFalse(match_no)

    @patch("sounddevice.default")
    @patch("sounddevice.InputStream")
    @patch("audio.wake_word._get_model")
    @patch("scipy.io.wavfile.write")
    def test_esperar_wake_word_deteccion(self, mock_wav, mock_get_model, mock_input_stream, mock_default):
        mock_default.device = [1, 0]

        # Simular lectura de frames de audio (voz activa + silencio de cierre)
        speech_frame = np.full((800, 1), 1000, dtype=np.int16)
        silence_frame = np.zeros((800, 1), dtype=np.int16)

        mock_stream = MagicMock()
        # 10 frames de voz, 11 frames de silencio para activar el fin de frase
        mock_stream.read.side_effect = [(speech_frame, False)] * 10 + [(silence_frame, False)] * 12
        mock_input_stream.return_value.__enter__.return_value = mock_stream

        segment_mock = MagicMock()
        segment_mock.text = "hola jessyca"
        model_mock = MagicMock()
        model_mock.transcribe.return_value = ([segment_mock], None)
        mock_get_model.return_value = model_mock

        # Debe procesar la frase completa y salir al detectar "jessyca"
        esperar_wake_word(silencio_confirmacion_seg=0.1, duracion_minima_seg=0.1)
        mock_input_stream.assert_called_once()


if __name__ == "__main__":
    unittest.main()
