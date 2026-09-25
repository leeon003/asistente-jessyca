"""Pruebas de integración del launcher (main.py) con el modo --webui.

Valida:
1. --webui es reconocido por parse_arguments()
2. Exclusión mutua entre flags (--demo, --voice, --mcp, --mobile, --webui)
3. Delegación de main(["--webui"]) hacia run_webui_mode()
4. Comportamiento seguro ante token ausente en run_webui_server
5. Preservación del funcionamiento de los argumentos existentes (--demo, --voice, --mcp, --mobile)
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from main import main, parse_arguments, run_webui_mode


def test_launcher_webui_arg_parsed() -> None:
    """Verifica que el argumento CLI --webui sea parseado correctamente."""
    args = parse_arguments(["--webui"])
    assert args.webui is True
    assert args.demo is False
    assert args.voice is False
    assert args.mcp is False
    assert args.mobile is False


def test_launcher_custom_host_and_port_with_webui() -> None:
    """Verifica que --host y --port personalizados se propaguen con --webui."""
    args = parse_arguments(["--webui", "--host", "127.0.0.1", "--port", "9090"])
    assert args.webui is True
    assert args.host == "127.0.0.1"
    assert args.port == 9090


def test_launcher_mutually_exclusive_flags() -> None:
    """Verifica que los modos sean mutuamente excluyentes y lancen SystemExit ante combinaciones inválidas."""
    with pytest.raises(SystemExit):
        parse_arguments(["--webui", "--voice"])

    with pytest.raises(SystemExit):
        parse_arguments(["--webui", "--mobile"])

    with pytest.raises(SystemExit):
        parse_arguments(["--webui", "--mcp"])

    with pytest.raises(SystemExit):
        parse_arguments(["--webui", "--demo"])


def test_launcher_existing_flags_unaffected() -> None:
    """Verifica que los argumentos existentes sigan funcionando exactamente igual."""
    args_voice = parse_arguments(["--voice"])
    assert args_voice.voice is True
    assert args_voice.webui is False

    args_mobile = parse_arguments(["--mobile"])
    assert args_mobile.mobile is True
    assert args_mobile.webui is False

    args_mcp = parse_arguments(["--mcp", "--transport", "stdio"])
    assert args_mcp.mcp is True
    assert args_mcp.transport == "stdio"
    assert args_mcp.webui is False

    args_demo = parse_arguments([])
    assert args_demo.demo is False
    assert args_demo.webui is False


def test_launcher_main_delegates_to_run_webui_mode() -> None:
    """Verifica que main(["--webui"]) invoque a run_webui_mode con los parámetros adecuados."""
    with patch("main.run_webui_mode", return_value=0) as mock_run_webui:
        exit_code = main(["--webui", "--host", "0.0.0.0", "--port", "8088"])
        assert exit_code == 0
        mock_run_webui.assert_called_once_with(host="0.0.0.0", port=8088)


def test_run_webui_mode_invokes_run_webui_server() -> None:
    """Verifica que run_webui_mode invoque a run_webui_server del paquete interfaces.webui_bridge."""
    with patch("interfaces.webui_bridge.server.run_webui_server", return_value=0) as mock_server:
        exit_code = run_webui_mode(host="127.0.0.1", port=8088)
        assert exit_code == 0
        mock_server.assert_called_once_with(host="127.0.0.1", port=8088)


def test_run_webui_server_missing_token_fails_safely() -> None:
    """Verifica que run_webui_server falle con código 1 sin iniciar si el token no está configurado."""
    from interfaces.webui_bridge.server import run_webui_server

    with patch.dict(os.environ, {"WEBUI_BRIDGE_AUTH_TOKEN": ""}):
        exit_code = run_webui_server(
            host="127.0.0.1",
            port=8088,
            auth_token="",
            perform_health_check=False,
        )
        assert exit_code == 1
