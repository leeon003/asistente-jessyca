"""Script de diagnóstico exhaustivo de Wake-on-LAN y capacidades de energía en Windows."""

import json
import os
import subprocess
import sys


def run_ps(cmd: str) -> str:
    full_cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    try:
        res = subprocess.run(full_cmd, capture_output=True, text=True, timeout=15)
        return res.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def main():
    print("=== DIAGNÓSTICO DE HARDWARE Y WAKE-ON-LAN ===")
    
    # 1. Placa Base y BIOS
    print("\n--- 1. Placa Base y BIOS ---")
    mb_raw = run_ps("Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, Version | ConvertTo-Json")
    bios_raw = run_ps("Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SMBIOSBIOSVersion, ReleaseDate | ConvertTo-Json")
    print("Placa Base:", mb_raw)
    print("BIOS:", bios_raw)

    # 2. Estados de Energía (powercfg /a)
    print("\n--- 2. Estados de Energía ---")
    try:
        powercfg_a = subprocess.run(["powercfg", "/a"], capture_output=True, text=True, timeout=10).stdout
        print(powercfg_a)
    except Exception as e:
        print("Error powercfg /a:", e)

    # 3. Dispositivos que pueden reactivar el equipo (powercfg /devicequery wake_armed)
    print("\n--- 3. Dispositivos Habilitados para Reactivar (wake_armed) ---")
    try:
        wake_armed = subprocess.run(["powercfg", "-devicequery", "wake_armed"], capture_output=True, text=True, timeout=10).stdout
        print(wake_armed)
    except Exception as e:
        print("Error wake_armed:", e)

    # 4. Todos los dispositivos capaces de reactivar (powercfg /devicequery wake_programmable)
    print("\n--- 4. Dispositivos Programables para Reactivar (wake_programmable) ---")
    try:
        wake_prog = subprocess.run(["powercfg", "-devicequery", "wake_programmable"], capture_output=True, text=True, timeout=10).stdout
        print(wake_prog)
    except Exception as e:
        print("Error wake_programmable:", e)

    # 5. Adaptadores de Red y Propiedades Avanzadas
    print("\n--- 5. Adaptadores de Red Físicos y Propiedades WOL ---")
    adapters_raw = run_ps(
        "Get-NetAdapter | Where-Object { $_.Virtual -ne $true } | "
        "Select-Object Name, InterfaceDescription, Status, MacAddress, LinkSpeed | ConvertTo-Json"
    )
    print("Adaptadores:", adapters_raw)

    eth_props = run_ps(
        "Get-NetAdapterAdvancedProperty -Name 'Ethernet' | "
        "Where-Object { $_.DisplayName -match 'Wake|Magic|Power|Green|Apagado|WOL|Energ' } | "
        "Select-Object DisplayName, DisplayValue | ConvertTo-Json"
    )
    print("\nPropiedades WOL Ethernet:\n", eth_props)

    wifi_props = run_ps(
        "Get-NetAdapterAdvancedProperty -Name 'Wi-Fi' | "
        "Where-Object { $_.DisplayName -match 'Wake|Magic|Power|WOWLAN|Reactiv' } | "
        "Select-Object DisplayName, DisplayValue | ConvertTo-Json"
    )
    print("\nPropiedades WOL Wi-Fi:\n", wifi_props)

    # 6. Estado de Fast Startup (Inicio Rápido en Registro)
    print("\n--- 6. Configuración de Inicio Rápido (HiberbootEnabled) ---")
    fast_startup = run_ps(
        "Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power' -Name 'HiberbootEnabled' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty HiberbootEnabled"
    )
    print("HiberbootEnabled (1=Activado, 0=Desactivado):", fast_startup)


if __name__ == "__main__":
    main()
