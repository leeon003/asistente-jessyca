# JESSYCA 4.0 — GUÍA OPERATIVA E INSTRUCCIONES DE USO

**Versión:** 4.0.0-PROD  
**Audiencia:** Propietario / Administrador del Sistema  
**Seguridad:** *Nunca almacenar credenciales reales ni claves privadas en el repositorio. Utilizar variables de entorno en el archivo `.env` local.*

---

## 1. REQUISITOS PREVIOS Y ENTORNO

- **Sistema Operativo:** Windows 10 u 11 (64-bit) con sesión gráfica interactiva.
- **Python:** Versión 3.11.x recomendada (instalado en PATH).
- **Ollama:** Instalado localmente para inferencia y descomposición agéntica autónoma.
- **Hardware de Red:** Tarjeta Ethernet Realtek GbE conectada al router local para funciones Wake-on-LAN.

---

## 2. CONFIGURACIÓN DE OLLAMA Y SELECCIÓN DE MODELOS

### 2.1. Iniciar el Servicio Ollama
Asegúrate de que Ollama se esté ejecutando en segundo plano en su puerto predeterminado (`11434`):
```powershell
# En una terminal de PowerShell:
ollama serve
```

### 2.2. Descargar los Modelos Certificados de JESSYCA 4.0
JESSYCA utiliza una arquitectura multi-modelo según el tipo de tarea:
```powershell
# Modelo para razonamiento rápido y diálogo general:
ollama pull qwen2.5:7b

# Modelo para tareas técnicas y síntesis estructurada:
ollama pull gemma:7b

# Modelo ligero para procesamiento rápido:
ollama pull llama3.2:3b
```

### 2.3. Configuración en `config/models_config.json`
El enrutador dinámico (`ShadowRouter`) selecciona el modelo idóneo automáticamente:
```json
{
  "default_model": "qwen2.5:7b",
  "task_mapping": {
    "conversation": "qwen2.5:7b",
    "technical": "gemma:7b",
    "agent_planning": "qwen2.5:7b",
    "fast_classification": "llama3.2:3b"
  },
  "ollama_host": "http://localhost:11434"
}
```

---

## 3. INICIO DE JESSYCA 4.0

### 3.1. Modo Consola Interactivo (Agente Local)
Para interactuar directamente mediante texto por terminal:
```powershell
# Activar entorno virtual
.\venv\Scripts\Activate.ps1

# Iniciar JESSYCA en modo interactivo
python main.py --mode interactive
```

### 3.2. Modo Voz y Conversación Natural
Para activar el reconocimiento continuo por micrófono con detección de voz (VAD), síntesis TTS y detención por voz (Barge-In):
```powershell
python main.py --mode voice
```
- **Interrupción por Voz**: Puedes decir *"JESSYCA, detente"*, *"para"*, o *"silencio"* en cualquier momento mientras el asistente habla para interrumpir la respuesta de forma inmediata (<15 ms).
- **Parada de Emergencia Física**: Mueve el cursor bruscamente a la esquina superior izquierda de la pantalla (`0, 0`) para activar el failsafe de hardware si una automatización visual requiere ser abortada.

---

## 4. CONTROL DE ESCRITORIO (CUA - COMPUTER USE ADAPTER)

El controlador unificado (`UnifiedDesktopController`) opera bajo estricta gobernanza:
- **Mutex de Sesión Única**: Solo una orden gráfica interactúa a la vez con el mouse o teclado para evitar conflictos.
- **Resolución Dinámica de Coordenadas**: Las coordenadas se recalculan en tiempo real antes de cada clic (`Anti-Stale Coordinates`).
- **Verificación de Ventanas**: Cada lanzamiento de aplicación verifica el PID real en Windows mediante `ExecutionVerifier`.

Para invocar tareas de control de escritorio desde lenguaje natural:
- *"Abre el Bloc de notas y escribe mi lista de pendientes"*
- *"Consulta el volumen del sistema y siléncialo"*
- *"Toma una captura de pantalla de la ventana activa"*

---

## 5. CONTROL REMOTO SEGURO VÍA WHATSAPP Y WAKE-ON-LAN

### 5.1. Variables de Entorno en `.env` (No guardar en Git)
Crea o edita tu archivo `.env` en la raíz del proyecto:
```ini
# Configuración del Propietario (Número personal con código de país)
OWNER_PHONE_JID="51999999999@s.whatsapp.net"
AUTHORIZED_DEVICE_IDS="owner-primary-phone"

# Clave secreta para firma y verificación HMAC de comandos remotos
WHATSAPP_HMAC_SECRET="tu_clave_secreta_super_segura_aqui"

# Parámetros Wake-on-LAN
WOL_TARGET_MAC="04-7C-16-6E-B4-70"
WOL_BROADCAST_IP="192.168.1.255"
WOL_PORT=9
```

### 5.2. Comandos Remotos Disponibles por WhatsApp
Solo los mensajes enviados desde el `OWNER_PHONE_JID` registrado y con `device_id` autorizado son procesados:
- `¿Estás ahí, JESSYCA?`: Consulta el estado de la PC y disponibilidad de la sesión.
- `estado`: Reporta métricas de CPU, memoria RAM, volumen y ventanas activas.
- `abrir [aplicación]`: Inicia una aplicación autorizada en la PC remota.
- `silenciar`: Silencia el audio maestro de Windows.
- `captura`: Toma una captura de pantalla y la envía cifrada al propietario.
- `detener`: Activa la parada de emergencia global remota.

---

## 6. DIAGNÓSTICO Y RECUPERACIÓN

### 6.1. Verificación del Adaptador de Red para Wake-on-LAN
Si la PC no despierta al recibir el Magic Packet, ejecuta el script de diagnóstico:
```powershell
python scripts/diagnose_wol.py
```
Verifica que:
1. `wake_armed` esté en `True` en la tarjeta `Realtek PCIe GbE Family Controller`.
2. El BIOS tenga habilitado *"Resume By Onboard DMI / PCIE Device"*.
3. El enlace esté activo en modo de espera a 10 Mbps (LED ámbar/verde encendido en el puerto RJ45).

### 6.2. Registro de Auditoría y Eventos de Seguridad
Todos los accesos, bloqueos y ejecuciones se guardan en formato estructurado:
- Log principal: `logs/jessyca.log`
- Auditoría de seguridad: `logs/audit_security.jsonl`
- Registro de rendimiento y anomalías: `data/learning_reports/`

### 6.3. Restablecimiento tras Parada de Emergencia
Si el sistema entra en estado de parada de emergencia (`EMERGENCY_STOP_TRIGGERED`), ninguna herramienta se ejecutará hasta su reinicio seguro:
```powershell
# En consola interactiva de JESSYCA:
JESSYCA> reset_emergency_stop
```
O programáticamente:
```python
from core.emergency_stop import EmergencyStopManager
EmergencyStopManager.get_instance().reset("Autorizado por el propietario")
```
