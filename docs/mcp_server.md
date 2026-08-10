# Infraestructura del Servidor MCP — Jessyca Windows MCP (Subetapa 05.1)

## Visión General

La **Infraestructura del Servidor MCP** en `server/` establece la capa de comunicación y punto de entrada para solicitudes MCP utilizando **FastMCP**.

Proporciona administración explícita del ciclo de vida del servidor, contextos sanitizados de solicitud (`RequestContext`), diagnósticos de salud estructurados (`HealthChecker`), jerarquía de excepciones MCP, integración con el `ToolRegistry` y un contrato de frontera de ejecución seguro (`StubExecutionBoundary`).

---

## Flujo Arquitectónico

```text
Client / Jessyca Virtual Assistant
       ↓
    MCP Server (JessycaMCPServer / FastMCP)
       ↓
 Request Context (RequestContext - Untrusted Input Isolation)
       ↓
 Tool Registry (ToolRegistry - Discovery & Metadata)
       ↓
 Capability System (CapabilityResolver -> CapabilityRegistry / CapabilityValidator)
       ↓
 Security Pipeline (05.2: SecureExecutionPipeline)
       ↓
 Execution Boundary (SecureExecutionBoundary -> DisabledToolExecutor)
```

> [!IMPORTANT]
> **Límites de Seguridad de la Subetapa 05.1:**
> - En esta subetapa **NO** se ejecutan herramientas reales de Windows, ni scripts PowerShell, ni comandos del sistema operativo.
> - La frontera de ejecución es un `StubExecutionBoundary` no ejecutable que retorna un estado `STUB_DISABLED` controlado.
> - Se aplica la regla de **Aislamiento de Entradas No Confiables**: Cualquier parámetro enviado por el cliente MCP que intente suplantar estados o decisiones de seguridad (ej. `decision=ALLOW`, `risk_level=SAFE`, `policy_source=ADMINISTRATOR`) es automáticamente sanitizado y desestimado antes de procesar la solicitud.

---

## Componentes Principales

### 1. `JessycaMCPServer` (`server/app.py`)
Contenedor principal FastMCP que administra el ciclo de vida del servidor, la consulta del registro de herramientas y el manejo seguro de solicitudes.

### 2. `ServerLifecycleManager` (`server/lifecycle.py`)
Máquina de estados hilos-segura con transiciones explícitas:
- `STOPPED`: Servidor detenido e inactivo.
- `INITIALIZING`: Cargando componentes e infraestructura.
- `RUNNING`: Servidor activo listo para recibir solicitudes MCP.
- `STOPPING`: Apagado ordenado en proceso.
- `FAILED`: Estado de error catastrófico.

### 3. `RequestContext` (`server/context.py`)
Objeto inmutable `@dataclass(frozen=True)` que transporta:
- `request_id`: Identificador único UUID4 por solicitud.
- `correlation_id`: Identificador de grupo de operaciones correlacionadas.
- `session_id`: Identificador de la sesión de Jessyca.
- `timestamp`: Timestamp ISO 8601 en UTC.
- `user`, `tool_name`, `operation`, `parameters`, `metadata`.

### 4. `HealthChecker` (`server/health.py`)
Genera un diagnóstico estructurado `HealthCheckResult` con información de estado (`HEALTHY`, `DEGRADED`, `UNHEALTHY`), tiempo de actividad (`uptime_seconds`), total de herramientas registradas y estado de componentes **sin ejecutar herramientas del SO**.

### 5. `StubExecutionBoundary` (`server/boundary.py`)
Implementación Stub del protocolo `IExecutionBoundary` que intercepta las solicitudes y responde deterministamente sin invocar el sistema operativo ni procesos externos.
