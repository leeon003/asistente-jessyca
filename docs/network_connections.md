# Active Network Connections & Port Listener Inspector — Jessyca Windows MCP (Subetapa 09.2)

## Visión General

La **Subetapa 09.2** amplía la **ETAPA 09 — SECURE NETWORK & SYSTEM DIAGNOSTICS** implementando la inspección de diagnóstico en modo solo lectura de conexiones activas (TCP/UDP) (`get_active_connections`) y puertos en escucha (`get_listening_ports`) bajo la capability `windows.network`.

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y PRIVACIDAD

1. **READ-ONLY DIAGNOSTIC INSPECTION**: Operación puramente lectora de diagnóstico de sockets y puertos. CERO cierre de conexiones, CERO finalización de procesos, CERO bloqueo/apertura de puertos, CERO modificación de firewall/rutas.
2. **UNTRUSTED INPUT & FAIL-SAFE DENY**: Solicitudes y filtros son validados por `NetworkConnectionSecurityManager`. Se rechazan puertos fuera del rango [0-65535], PIDs negativos, protocolos no reconocidos, NaN, Infinity y valores de tipos incorrectos.
3. **GRACEFUL PROCESS HANDLING**: Manejo de degradación limpia cuando un proceso finaliza durante la inspección (`psutil.NoSuchProcess`, `psutil.AccessDenied`). `process_id` y `process_name` se degradan a `None` sin causar caídas del pipeline.
4. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`total_found`, `returned_count`, `truncated`, `processing_time_ms`, `backend_name`). **NUNCA** almacenan conexiones individuales, direcciones IP/MAC, puertos ni nombres de proceso en logs de auditoría.
5. **CERO SUBPROCESS / SHELL**: La inspección utiliza la API nativa de `psutil.net_connections()` o un `FakeNetworkConnectionInspectionBackend` sintético desacoplado en memoria. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**, **CERO `netstat`**, **CERO `netsh`**.

---

## Componentes Principales

### 1. `NetworkConnectionSecurityManager` (`core/network_connection_security.py`)
- Valida puertos (0-65535), protocolos (TCP, UDP, ANY), PIDs y formatos IP.
- Sanitiza nombres de procesos removiendo argumentos de línea de comandos, credenciales y acotando la longitud máxima (`NETWORK_MAX_PROCESS_NAME_LENGTH=256`).

### 2. Backends de Conexiones Desacoplados (`tools/network/connection_backend.py`)
- `INetworkConnectionInspectionBackend`: Protocolo abstracto para inspección de conexiones de red y puertos.
- `WindowsNetworkConnectionInspectionBackend`: Backend nativo utilizando `psutil.net_connections()` con manejo seguro de procesos desaparecidos y fallback limpio.
- `FakeNetworkConnectionInspectionBackend`: Backend sintético seguro en memoria para pruebas unitarias deterministas.

### 3. Servicio y Ejecutor (`tools/network/connection_service.py` & `executor.py`)
- `NetworkConnectionInspectionService`: Orquesta la validación de seguridad, consulta del backend de conexiones, clasificación TCP/UDP, filtrado y auditoría con metadatos exclusivos.
- `WindowsNetworkToolExecutor`: Ejecutor integrado en `SecureExecutionPipeline` para las operaciones `get_active_connections` y `get_listening_ports`.
