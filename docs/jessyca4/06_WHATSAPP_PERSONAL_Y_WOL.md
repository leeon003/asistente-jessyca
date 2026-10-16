# JESSYCA 4.0 — FASE 6: WHATSAPP PERSONAL Y WAKE-ON-LAN

**Documento de Entrega Oficial**  
**Fecha:** 16 de Octubre de 2026  
**Rama:** `feature/jessyca-4-agent`  
**Estado:** **VALIDADO Y EN PRODUCCIÓN (23/23 Pruebas de Seguridad y Conectividad Aprobadas)**

---

## 1. RESUMEN EJECUTIVO

La **Fase 6** dota a JESSYCA de un canal soberano y exclusivo de **WhatsApp Personal** para su propietario, permitiendo solicitar tareas remotas supervisadas, consultar la disponibilidad y el estado físico de la PC, y enviar señales seguras de **Wake-on-LAN (WOL)** a través de la red doméstica sin abrir puertos hacia internet, sin riesgo de intrusión arbitraria y sin falsos éxitos.

Este subsistema se encuentra **estrictamente aislado de cualquier CRM, tienda comercial o bot de ventas**, operando bajo el principio de menor privilegio, listas blancas inmutables y verificación determinista.

---

## 2. ARQUITECTURA DEL CANAL REMOTO CIFRADO

```
                    ┌──────────────────────────────────────────────┐
                    │       Propietario Autenticado (WhatsApp)     │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           │ (1) Mensaje cifrado (E2EE WhatsApp)
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │          Gateway de Mensajes en VPS          │
                    │   (interfaces/whatsapp_personal/gateway.py)  │
                    │  - Filtro remitente & ID dispositivo         │
                    │  - Rate Limiting (Máx 10 req/min)            │
                    │  - Anti-Replay (Nonce único + ventana 60s)   │
                    │  - Desafío 2FA/OTP para acciones sensibles   │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           │ (2) Túnel Cifrado Saliente (WebSocket/mTLS)
                                           │     Firma HMAC-SHA256 con Nonce
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │    Agente Local Windows (Host de JESSYCA)    │
                    │        (core/remote/task_router.py)          │
                    │  - Cero puertos abiertos hacia internet      │
                    │  - Validación contra FORBIDDEN_PATTERNS      │
                    │  - Lista blanca estricta de apps             │
                    │  - Verificación de sesión de usuario         │
                    │  - Parada de emergencia (EmergencyStop)      │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           │ (3) Ejecución física observada
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │       Verificación y Evidencia Real          │
                    │     (PIDs reales, métricas GPU/RAM/CPU)      │
                    └──────────────────────┬───────────────────────┘
                                           │
                                           │ (4) Respuesta honesta y directa
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │           Notificación en WhatsApp           │
                    │      "Listo, he abierto Bloc de notas"       │
                    └──────────────────────────────────────────────┘
```

---

## 3. MODELO DE AUTORIZACIÓN Y BLINDAJE DE SEGURIDAD

### 3.1 Verificación de Identidad Multi-Factor
- **Identidad del Remitente:** Comprobación estricta del número y JID del propietario (`WHATSAPP_OWNER_PHONE_JID`). Se rechaza cualquier remitente desconocido (`REJECTED_UNAUTHORIZED`).
- **Dispositivo Autorizado:** Validación del identificador de dispositivo móvil (`WHATSAPP_AUTHORIZED_DEVICES`). Solicitudes de dispositivos desconocidos son bloqueadas.
- **Integridad y No Repudio:** Firma criptográfica HMAC-SHA256 de cada paquete con clave secreta compartida (`WHATSAPP_REMOTE_SHARED_SECRET`).

### 3.2 Protección Anti-Replay y Control de Abuso
- **Ventana Temporal:** Rechazo automático de mensajes con timestamp desfasado por más de 60 segundos.
- **Nonces Únicos:** Registro en memoria con purga automática de identificadores de mensaje usados. Todo intento de repetición de paquete es detectado y denegado (`REJECTED_REPLAY`).
- **Rate Limiting:** Ventana deslizante que limita las solicitudes a un máximo de 10 por minuto por remitente, impidiendo ataques de denegación de servicio.

### 3.3 Desafíos de Confirmación (2FA / OTP)
- Para acciones de alto riesgo (cancelaciones críticas, modificaciones de estado), el sistema genera un código efímero de 6 dígitos con tiempo de vida limitado (120 segundos) y máximo 3 intentos.
- El propietario debe responder: `CONFIRMAR <código>` para autorizar la ejecución.

---

## 4. CATÁLOGO DE ACCIONES AUTORIZADAS VS RECHAZADAS

### 4.1 Acciones Permitidas (Lista Blanca)
| Comando / Intención | Tipo | Comportamiento en Windows | Evidencia Recopilada |
| :--- | :--- | :--- | :--- |
| **"¿Estás ahí?" / Ping** | `PING_STATUS` | Verifica que el agente en Windows esté conectado y respondiendo por el túnel. | `host_online: True`, estado de bloqueo de pantalla. |
| **"Estado de JESSYCA"** | `JESSYCA_STATUS` | Consulta telemetría real: RAM libre, GPU VRAM (RTX 3060), modelo activo (`llama3.2`) y estado de parada de emergencia. | `cpu_percent`, `ram_available_gb`, `gpu_vram_free_gb`. |
| **"Investiga sobre [tema]"** | `RESEARCH_TASK` | Lanza tarea de investigación en segundo plano en la PC y resume hallazgos para WhatsApp. | `stored_locally: True`, timestamp de guardado. |
| **"Últimas tareas"** | `TASK_RESULTS` | Devuelve el historial reciente de operaciones completadas en la sesión. | Conteo y metadatos de las últimas 5 tareas. |
| **"Detente" / "Cancela todo"** | `CANCEL_TASK` | Activa de inmediato la Parada de Emergencia global (`EmergencyStopManager`) abortando tareas activas. | `emergency_stop_triggered: True`, `source: remote_whatsapp_owner`. |
| **"Abre [app autorizada]"** | `OPEN_APP` | Abre exclusivamente aplicaciones de la lista blanca autorizada: `chrome`, `notepad`, `calc`. | PID del proceso y verificación de estado. |
| **"Despierta la PC"** | `WAKE_ON_LAN` | Despacha el Magic Packet hacia la subred doméstica autorizada y sondea confirmación real. | Socket UDP broadcast transmitido y sondeo de socket. |

### 4.2 Prohibiciones Estrictas (Cero Compromiso de Seguridad)
- **Consola remota arbitraria (`cmd.exe`, `powershell`, `pwsh`, `bash`, `sh`):** Denegado inmediatamente con alerta crítica.
- **Manipulación destructiva de archivos (`del`, `format`, `rmdir`, `reg`):** Rechazado por catálogo de patrones prohibidos.
- **Instalación de software o ejecución de instaladores (`msiexec`, `pip install`, `install`):** Bloqueado.
- **Acceso a credenciales protegidas (.env, SAM, SSH, certificados):** Blindado a nivel de núcleo.
- **Apertura de apps fuera de la lista blanca:** Aplicaciones no listadas son rechazadas con mensaje explícito.

---

## 5. CAPACIDADES REALES DE WAKE-ON-LAN (WOL)

De acuerdo con el informe de auditoría física [`06_WOL_DIAGNOSTICO.md`](docs/jessyca4/06_WOL_DIAGNOSTICO.md):

1. **Hardware Comprobado:**
   - **Placa Base:** MSI B550M PRO-VDH WIFI (MS-7C95) v1.0, BIOS AMI 2.C0.
   - **Tarjeta de Red:** Realtek PCIe GbE Family Controller (`04-7C-16-6E-B4-70`).
   - **Estado en Sistema:** Armado para reactivar (`wake_armed` activo en Windows).
   - **Parámetros del Controlador:** `Reactivar en Magic Packet: Activado`, `Activación con LAN de apagado: Activado`, `Velocidad de enlace WOL y Apagado: 10 Mbps Primero`.

2. **Estados Compatibles:**
   - **Modo de Espera (S3):** **100% Funcional.** Despierta en < 3 segundos.
   - **Hibernación (S4):** **100% Funcional.** Despierta y restaura sesión.
   - **Inicio Rápido (S4 Híbrido):** Funcional con alimentación continua.
   - **Apagado Completo (S5):** Condicionado a que la BIOS mantenga alimentación en standby y no se interrumpa la energía eléctrica.
   - **Wi-Fi (WoWLAN):** No recomendado por estar desconectado y carecer de S0 Modern Standby.

3. **Política Anti-Falsos Éxitos:**
   - El sistema **NUNCA** afirma que la PC despertó por el simple hecho de enviar el paquete UDP.
   - Emite confirmación de envío y únicamente confirma *"Tu PC ha respondido"* cuando el agente en Windows establece la conexión TCP de vuelta por el túnel cifrado.

---

## 6. PROTOCOLO DE CONEXIÓN TRAS LA REACTIVACIÓN DE WINDOWS

Al reactivarse el equipo:
1. **Espera de Red:** El servicio espera a que el adaptador Realtek negocie enlace (1 Gbps) y obtenga IP válida.
2. **Arranque del Agente:** Se comprueba la inicialización de `JessycaLocalAgent` y los subsistemas de seguridad.
3. **Restablecimiento del Túnel:** El cliente de Windows establece la conexión saliente hacia el VPS Gateway.
4. **Handshake Autenticado:** Intercambio de paquete `HANDSHAKE_INIT` y recepción de `HANDSHAKE_ACK` con firma HMAC.
5. **Comprobación de Pantalla de Bloqueo:** El sistema evalúa `is_windows_session_locked()`. Si la pantalla está bloqueada, las acciones en segundo plano (estado, investigación) operan normalmente, mientras que las acciones interactivas de escritorio quedan en espera honesta de inicio de sesión.
6. **Notificación al Propietario:** El Gateway emite a WhatsApp: *"Tu PC está encendida y JESSYCA se encuentra lista."*

---

## 7. SUITE DE PRUEBAS AUTOMATIZADAS (23/23 PASSED)

Archivo de pruebas: [`tests/remote/test_whatsapp_personal_and_wol.py`](file:///d:/JESSYCA%203.0/asistente-jessyca/tests/remote/test_whatsapp_personal_and_wol.py)

```text
tests/remote/test_whatsapp_personal_and_wol.py .......................   [100%]
============================= 23 passed in 3.22s ==============================
```

Pruebas ejecutadas:
1. `test_auth_authorized_sender_and_device`: Remitente y dispositivo válidos aceptados.
2. `test_auth_unknown_sender_rejected`: Remitente desconocido denegado (403).
3. `test_auth_unauthorized_device_rejected`: Dispositivo no registrado bloqueado.
4. `test_anti_replay_blocks_duplicate_nonce`: Bloqueo inmediato de nonces duplicados.
5. `test_anti_replay_blocks_expired_timestamp`: Rechazo de mensajes fuera de ventana de 60s.
6. `test_hmac_signature_verification`: Verificación e invalidación ante mensajes alterados.
7. `test_rate_limiting_enforcement`: Corte automático al superar 10 req/min.
8. `test_forbidden_command_patterns_rejected`: Rechazo de cmd, powershell, del, format, net user e install.
9. `test_gateway_ping_command`: Respuesta natural a preguntas de disponibilidad.
10. `test_gateway_status_command`: Entrega de métricas reales de RAM, GPU, modelo y estado.
11. `test_gateway_research_command`: Tarea de investigación en segundo plano.
12. `test_gateway_cancel_triggers_emergency_stop`: Parada de emergencia activada y verificada.
13. `test_open_app_whitelisted`: Apertura verificada con PID real para apps autorizadas (notepad).
14. `test_open_app_non_whitelisted_rejected`: Rechazo de apps fuera de lista blanca.
15. `test_open_app_blocked_when_session_is_locked`: Detección honesta de estación bloqueada.
16. `test_gateway_handles_offline_pc_honestly`: Manejo honesto de PC apagada ofreciendo WOL.
17. `test_wol_magic_packet_structure`: Ensamblado canónico de 102 bytes con MAC física.
18. `test_wol_send_packet_acknowledgment`: Reconocimiento sin afirmar éxito prematuro.
19. `test_wol_does_not_claim_awake_on_timeout`: Reporte de fallo honesto ante timeout.
20. `test_wol_confirms_awake_only_when_probe_succeeds`: Confirmación exclusiva tras probe exitoso.
21. `test_sensitive_operation_confirmation_flow`: Ciclo completo de desafío 2FA/OTP de 6 dígitos.
22. `test_tunnel_protocol_packing_and_unpacking`: Empaquetado y verificación de integridad.
23. `test_tunnel_rejects_tampered_packet`: Detección y rechazo de paquetes adulterados.

---

## 8. DOCUMENTACIÓN DE RECUPERACIÓN Y OPERACIÓN

### Procedimiento ante Pérdida de Conexión o Fallo de Red:
1. **Reintento de Reconexión con Backoff:** El cliente de Windows reintenta la conexión hacia el VPS en intervalos de 5s, 10s, 30s hasta restablecer el canal.
2. **Reinicio Manual del Túnel en Windows:**
   ```powershell
   python -m core.remote.relay_client
   ```
3. **Comprobación de Wake-on-LAN Local:**
   ```powershell
   python scripts/diagnose_wol.py
   ```
4. **Desbloqueo de Emergencia tras Parada por Voz o Remota:**
   Si el propietario activó la parada con *"detente"*, puede restablecer el asistente diciendo *"continúa"* o mediante:
   ```python
   from core.emergency_stop import EmergencyStopManager
   EmergencyStopManager.get_instance().reset(caller_id="owner")
   ```
