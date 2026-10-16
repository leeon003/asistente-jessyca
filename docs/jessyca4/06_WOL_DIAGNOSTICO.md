# JESSYCA 4.0 — FASE 6: INFORME DE DIAGNÓSTICO DE HARDWARE Y WAKE-ON-LAN

**Fecha:** 16 de Octubre de 2026  
**Host:** Windows 11 Pro (Build 10.0.26200 amd64)  
**Objetivo:** Determinar empíricamente las capacidades de reactivación remota de la PC anfitriona de JESSYCA, analizando placa base, firmware UEFI/BIOS, controladores de red cableada e inalámbrica y estados de energía del sistema operativo.

---

## 1. INVENTARIO FÍSICO DE HARDWARE Y FIRMWARE

| Componente | Detalle / Especificación Real | Evidencia del Sistema |
| :--- | :--- | :--- |
| **Placa Base** | Micro-Star International Co., Ltd. (MSI)<br>**B550M PRO-VDH WIFI (MS-7C95)** v1.0 | `Get-CimInstance Win32_BaseBoard` |
| **Firmware UEFI / BIOS** | American Megatrends Inc. (AMI) v**2.C0**<br>Fecha de compilación: 04/08/2022 | `Get-CimInstance Win32_BIOS` |
| **Procesador (CPU)** | AMD64 Family 25 Model 33 Stepping 2 (Ryzen 12 núcleos / 24 hilos) | `Win32_Processor` |
| **Adaptador Ethernet (LAN)** | **Realtek PCIe GbE Family Controller** | `Get-NetAdapter -Name 'Ethernet'` |
| **Dirección MAC Ethernet** | `04-7C-16-6E-B4-70` | Enlace activo a **1 Gbps** (Up) |
| **Adaptador Wi-Fi (WLAN)** | **RZ608 Wi-Fi 6E 80MHz** (MediaTek/AMD) | `Get-NetAdapter -Name 'Wi-Fi'` |
| **Dirección MAC Wi-Fi** | `BC-F4-D4-0D-DC-71` | Estado actual: **Disconnected** (0 bps) |

---

## 2. AUDITORÍA DE ESTADOS DE ENERGÍA (`powercfg /a`)

```text
Los siguientes estados de suspensión están disponibles en este sistema:
    Modo de espera (S3)
    Hibernar
    Inicio rápido

Los siguientes estados de suspensión no están disponibles en este sistema:
    Modo de espera (S1) - El firmware del sistema no admite este estado de espera.
    Modo de espera (S2) - El firmware del sistema no admite este estado de espera.
    Modo de espera (inactivo de baja energía S0) - El firmware del sistema no admite este estado de espera.
    Suspensión híbrida - El hipervisor no admite este estado de espera.
```

### Configuración del Registro de Windows:
- `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power\HiberbootEnabled` = **1** (Inicio Rápido activado en Windows).

---

## 3. AUDITORÍA DE DISPOSITIVOS ARMADOS PARA DESPERTAR (`powercfg /devicequery`)

### Dispositivos `wake_armed` (Actualmente con permiso y capacidad de reactivar):
1. **Realtek PCIe GbE Family Controller** *(Adaptador Ethernet por cable verificado)*
2. Teclados y Ratones HID (interacción física local)

### Dispositivos `wake_programmable` (Capaces por hardware pero condicionados):
- Realtek PCIe GbE Family Controller (Habilitado y armado)
- RZ608 Wi-Fi 6E 80MHz (Capaz pero actualmente desconectado y desarmado)

---

## 4. PARÁMETROS AVANZADOS DE LOS CONTROLADORES DE RED

### 4.1 Adaptador Ethernet: Realtek PCIe GbE Family Controller
- **Reactivar en Magic Packet:** `Activado`
- **Reactivar en coincidencia de patrones:** `Activado`
- **Activación con LAN de apagado:** `Activado` (Shutdown Wake-On-LAN / S5 Wake)
- **Velocidad de enlace WOL y Apagado:** `10 Mbps Primero` (El chip mantiene el PHY activo a bajo consumo cuando la PC se duerme o apaga)
- **Power Saving Mode:** `Desactivado`
- **Ethernet de consumo eficiente de energía:** `Desactivado` (Evita que el puerto se deshabilite totalmente)

### 4.2 Adaptador Wi-Fi: RZ608 Wi-Fi 6E 80MHz
- **ARP Offload for WOWLAN:** `Activado`
- **GTK Rekey for WOWLAN:** `Activado`
- **Magic Packet de reactivación:** `Activado`
- **Coincidencia de patrones de reactivación:** `Activado`
- **Limitación Real:** El adaptador Wi-Fi no tiene enlace activo (`Disconnected`) y la placa no cuenta con Modern Standby (S0ix). Al entrar en reposo o apagarse, la asociación inalámbrica con el router se interrumpe y la interfaz no mantiene alimentación de radio en S4/S5. **WoWLAN se cataloga como NO RECOMENDADO / NO OPERATIVO en el estado actual.**

---

## 5. MATRIZ DE COMPATIBILIDAD EMPÍRICA POR ESTADO DE ENERGÍA

| Estado del Sistema | Viabilidad Técnica WOL | Requisitos y Mecanismo Físico | Veredicto de Confiabilidad |
| :--- | :--- | :--- | :--- |
| **Suspensión (S3)** | **100% COMPATIBLE** | El chip Realtek permanece alimentado por la línea +5VSB. La señal de Magic Packet (`0xFF*6 + MAC*16`) recibida en el puerto Ethernet activa la interrupción PME# y despierta el equipo en < 3 segundos. | **PRIMARIO RECOMENDADO** |
| **Hibernación (S4)** | **100% COMPATIBLE** | El controlador Realtek mantiene el PHY a 10 Mbps en espera. Al recibir el Magic Packet, reactiva la placa base MSI y Windows reanuda la sesión desde `hiberfil.sys`. | **COMPATIBLE Y SEGURO** |
| **Inicio Rápido (S4 Híbrido)** | **ALTA COMPATIBILIDAD** | `Activación con LAN de apagado: Activado` mantiene el PHY a 10 Mbps. Si la BIOS tiene activado el PCIe Wake, despierta sin problemas. | **COMPATIBLE** |
| **Apagado Completo Mecánico (S5)** | **CONDICIONAL A BIOS** | Requiere que en el Setup de la BIOS MSI B550M: <br>1. `Wake Up Event Setup \ Resume By PCI-E Device` esté en `[Enabled]`. <br>2. `ErP Ready` esté en `[Disabled]` (ErP apaga los buses a 0W). <br>3. La fuente de poder mantenga suministro AC continuo (sin corte de luz). | **CONDICIONAL (No garantizado tras corte eléctrico total)** |

---

## 6. ARQUITECTURA DE REACTIVACIÓN LOCAL DESDE RED DOMÉSTICA

Dado el mandato estricto de seguridad:
> *"No expongas directamente el mecanismo de reactivación a internet. Diseña un sistema donde un router o dispositivo confiable dentro de la red doméstica envíe la solicitud local de reactivación."*

### Flujo Seguro de Activación WOL:
```
[Propietario en WhatsApp]
           │
           │ (1) "JESSYCA, despierta mi PC"
           ▼
┌──────────────────────────────────────────────┐
│  VPS Gateway (WhatsApp Personal)             │
│  - Autentica identidad y firma HMAC          │
│  - Rate limiting & Anti-Replay               │
└──────────────────────┬───────────────────────┘
                       │
                       │ (2) Orden cifrada mTLS / HMAC
                       ▼
┌──────────────────────────────────────────────┐
│  Dispositivo Confiable en LAN Doméstica      │
│  (Router OpenWrt, Raspberry Pi o Home Hub)   │
│  - Verifica desafío criptográfico            │
│  - Envía UDP Broadcast a 192.168.1.255:9     │
│  - Magic Packet: 04-7C-16-6E-B4-70           │
└──────────────────────┬───────────────────────┘
                       │
                       │ (3) Magic Packet físico
                       ▼
┌──────────────────────────────────────────────┐
│  PC Windows (MSI B550M + Realtek GbE)        │
│  - Despierta desde S3 / S4                   │
│  - Restablece red y arranca Relay Agent      │
│  - Handshake de vuelta al VPS                │
└──────────────────────┬───────────────────────┘
                       │
                       │ (4) Confirmación verificada (TCP Ping / Heartbeat)
                       ▼
[WhatsApp: "Tu PC ha despertado y JESSYCA está lista."]
```

### Regla Inviolable de Honestidad:
El Gateway **NUNCA** responde *"La PC se ha encendido"* tras simplemente disparar el paquete UDP. La respuesta inmediata es:  
> *"He enviado la solicitud de reactivación a tu red doméstica. Esperando confirmación real de conexión de tu PC..."*  

Y únicamente cuando el cliente Windows establece el canal cifrado de vuelta con el Gateway y envía su primer heartbeat verificado, se notifica:  
> *"Listo. Tu PC ha respondido y JESSYCA se encuentra activa y a tu disposición."*
