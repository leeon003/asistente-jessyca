# Guía de Compatibilidad con Windows 10 y 11

## Requisitos Mínimos del Sistema Operativo

**Jessyca Windows MCP** está diseñado para ejecutarse nativamente en entornos de escritorio Microsoft Windows.

- **Windows 10**: Build `19041` en adelante (Windows 10 Version 2004 / May 2020 Update o posterior).
- **Windows 11**: Build `22000` en adelante (Windows 11 21H2 o posterior).
- **Arquitectura**: `x86_64` (64-bit) o `ARM64`.
- **Python**: Python 3.11 o superior.

---

## Verificación Programática de Plataforma

La verificación de plataforma se realiza a través de `utils/platform.py`:

```python
from utils.platform import check_windows_compatibility, is_admin

info = check_windows_compatibility()
print(f"Es compatible: {info.is_compatible}")
print(f"Versión: {info.version.value}")
print(f"Build: {info.build_number}")
print(f"Es Administrador: {is_admin()}")
```

## Permisos de Administrador (UAC)

Algunas herramientas MCP futuras o servicios avanzados de diagnóstico de Windows pueden requerir privilegios elevados de administrador.
El módulo `utils/platform.py` proporciona la función `is_admin()` utilizando `ctypes.windll.shell32.IsUserAnAdmin()`.
