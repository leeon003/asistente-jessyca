import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from audio.stt import escuchar


class TestSTT(unittest.TestCase):
    def test_escuchar_duracion_invalida(self):
        self.assertEqual(escuchar(0), "")
        self.assertEqual(escuchar(-1), "")

    @patch("sounddevice.default")
    @patch("sounddevice.query_devices")
    def test_escuchar_sin_microfono(self, mock_query, mock_default):
        mock_default.device = [-1, -1]
        resultado = escuchar(1)
        self.assertEqual(resultado, "")

    @patch("sounddevice.default")
    @patch("sounddevice.query_devices")
    @patch("sounddevice.rec")
    @patch("sounddevice.wait")
    def test_escuchar_silencio(self, mock_wait, mock_rec, mock_query, mock_default):
        mock_default.device = [1, 0]
        mock_query.return_value = {"name": "Mic", "max_input_channels": 1}
        # Array con amplitud 0 (silencio)
        mock_rec.return_value = np.zeros((16000, 1), dtype=np.int16)
        resultado = escuchar(1)
        self.assertEqual(resultado, "")

    @patch("sounddevice.default")
    @patch("sounddevice.query_devices")
    @patch("sounddevice.rec")
    @patch("sounddevice.wait")
    @patch("audio.stt._get_model")
    @patch("scipy.io.wavfile.write")
    def test_escuchar_exito(self, mock_wav_write, mock_get_model, mock_wait, mock_rec, mock_query, mock_default):
        mock_default.device = [1, 0]
        mock_query.return_value = {"name": "Mic", "max_input_channels": 1}
        # Simulamos audio grabado con señal
        mock_rec.return_value = np.full((16000, 1), 1000, dtype=np.int16)

        # Mock del modelo faster-whisper
        segment_mock = MagicMock()
        segment_mock.text = "hola jessyca"
        model_mock = MagicMock()
        model_mock.transcribe.return_value = ([segment_mock], None)
        mock_get_model.return_value = model_mock

        resultado = escuchar(1)
        self.assertEqual(resultado, "hola jessyca")


if __name__ == "__main__":
    unittest.main()
