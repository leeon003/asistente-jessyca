import unittest
from unittest.mock import patch, MagicMock
from interfaces.modo_voz import iniciar_modo_voz


class TestModoVoz(unittest.TestCase):
    @patch("interfaces.modo_voz.esperar_wake_word")
    @patch("interfaces.modo_voz.hablar")
    @patch("interfaces.modo_voz.escuchar")
    @patch("interfaces.modo_voz.ejecutar_orden_texto")
    def test_iniciar_modo_voz_flujo_exitoso_y_seguimiento(
        self,
        mock_orquestador,
        mock_escuchar,
        mock_hablar,
        mock_esperar_wake
    ):
        mock_esperar_wake.side_effect = [None, KeyboardInterrupt()]
        # Primera orden, luego seguimiento con "gracias"
        mock_escuchar.side_effect = ["abre block de notas", "gracias"]
        mock_orquestador.return_value = "Abriendo Block de Notas"

        iniciar_modo_voz()

        mock_esperar_wake.assert_called()
        mock_hablar.assert_any_call("Dime, jefecito")
        mock_orquestador.assert_called_once_with("abre block de notas")
        mock_hablar.assert_any_call("Abriendo Block de Notas")
        mock_hablar.assert_any_call("¿Necesitas algo más, jefecito?")
        mock_hablar.assert_any_call("De nada, quedo atenta jefecito.")

    @patch("interfaces.modo_voz.esperar_wake_word")
    @patch("interfaces.modo_voz.hablar")
    @patch("interfaces.modo_voz.escuchar")
    def test_iniciar_modo_voz_orden_vacia(
        self,
        mock_escuchar,
        mock_hablar,
        mock_esperar_wake
    ):
        mock_esperar_wake.side_effect = [None, KeyboardInterrupt()]
        mock_escuchar.return_value = ""

        iniciar_modo_voz()

        mock_hablar.assert_any_call("No logré escucharte, jefecito.")


if __name__ == "__main__":
    unittest.main()
