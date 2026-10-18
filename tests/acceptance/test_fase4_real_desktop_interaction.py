"""test_fase4_real_desktop_interaction.py
Validación de control real de Windows 11 mediante UnifiedDesktopController (NativeWindowsDriver).
Verifica:
1. Abrir Calculadora y verificar ventana.
2. Abrir Bloc de notas.
3. Escribir texto real en la ventana con el teclado.
4. Ajustar volumen del sistema.
5. Cerrar aplicaciones autorizadas.
"""
import time
import pytest
from core.desktop.unified_controller import UnifiedDesktopController
from skills.skill_manager import get_skill_manager

@pytest.fixture(scope="module")
def controller():
    return UnifiedDesktopController()

def test_windows_calculator_launch_and_close(controller):
    """Verifica apertura y detección real de la Calculadora de Windows 11."""
    res_open = controller.open_app("calc.exe")
    assert res_open.success is True, f"Error abriendo calc: {res_open.error}"
    time.sleep(1.0)

    # Verificar existencia en ventanas del sistema
    win = controller.find_window("calc") or controller.find_window("calculadora")
    assert win is not None, "Ventana de Calculadora no detectada en el escritorio de Windows"

    # Cerrar ventana
    res_close = controller.close_app("calc.exe")
    assert res_close.success is True
    print("\n[OK] Calculadora abierta, verificada y cerrada con éxito.")

def test_notepad_typing_and_close(controller):
    """Verifica apertura, foco y escritura real mediante teclado en Bloc de notas."""
    res_open = controller.open_app("notepad.exe")
    assert res_open.success is True
    time.sleep(1.0)

    win = controller.find_window("notepad") or controller.find_window("bloc de notas")
    assert win is not None, "Ventana de Bloc de notas no detectada en Windows"

    hwnd = win["hwnd"]
    controller.focus_window(hwnd)
    time.sleep(0.3)

    # Escribir texto real mediante teclado físico del controlador
    sample_text = "JESSYCA BRAIN 1.0 - Windows 11 Native Interaction Verified."
    res_type = controller.type_text(sample_text, hwnd=hwnd)
    assert res_type.success is True
    print(f"\n[OK] Texto tecleado en Bloc de notas: '{sample_text}'")

    # Cerrar bloc de notas
    controller.close_app("notepad.exe")
    time.sleep(0.5)

def test_system_audio_volume(controller):
    """Verifica control de volumen de Windows mediante skill autorizada."""
    sm = get_skill_manager()
    res = sm.execute_skill("windows.audio", parameters={"accion": "bajar", "nivel": 10})
    assert res.success is True
    print(f"\n[OK] Volumen ajustado por controlador nativo.")
