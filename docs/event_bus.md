# Arquitectura del Event Bus Interno

Este documento describe la arquitectura, características y ejemplos de integración del **Event Bus Interno** (`core/event_bus.py`) en **Jessyca Windows MCP**.

---

## 1. Visión General

El **Event Bus** proporciona un patrón de comunicación **Publicador/Suscriptor (Pub/Sub)** completamente desacoplado. Permite a cualquier componente del sistema publicar eventos (ej. inicio de sesión, ejecución de herramientas, alertas de seguridad, cambios de ventana en el contexto) sin necesidad de conocer qué otros componentes están escuchando o procesando dicha información.

### Características Clave

1. **Desacoplamiento Absoluto**: El emisor sólo conoce el nombre del evento y su payload.
2. **Prioridades de Ejecución (`EventPriority`)**:
   - `HIGHEST = 0`: Ejecución inmediata previa a otros listeners (ej. auditoría de seguridad).
   - `HIGH = 10`: Acciones de alta prioridad.
   - `NORMAL = 50`: Nivel por defecto.
   - `LOW = 100`: Tareas secundarias o post-procesamiento.
3. **Tolerancia a Fallos e Aislamiento**: Si un listener falla o lanza una excepción no capturada, el `EventBus` la registra en el sistema de logs y **continúa notificando a los demás listeners** de manera transparente.
4. **Soporte Híbrido Síncrono y Asíncrono**: Soporta callbacks tradicionales `def handler(event)` y corrutinas `async def handler(event)`.
5. **Comodines de Suscripción (`*`)**: Permite suscribir listeners a todos los eventos del sistema.

---

## 2. Ejemplos de Uso

### Ejemplo A: Suscripción y Publicación Básica

```python
from core.event_bus import get_event_bus, Event, EventPriority

bus = get_event_bus()

# Listener síncrono
def on_tool_executed(event: Event) -> None:
    print(f"Herramienta ejecutada: {event.payload.get('tool_name')}")

# Suscribir con prioridad HIGHEST
sub_id = bus.subscribe("tool:executed", on_tool_executed, priority=EventPriority.HIGHEST)

# Publicar un evento
bus.publish("tool:executed", {"tool_name": "system_health", "status": "success"})

# Des-suscribir usando la función o el ID
bus.unsubscribe(sub_id)
```

### Ejemplo B: Handlers Asíncronos y Prioridades

```python
import asyncio
from core.event_bus import EventBus, EventPriority, Event

async def main():
    bus = EventBus()
    execution_order = []

    # Listener de baja prioridad (LOW)
    def low_priority_listener(event: Event):
        execution_order.append("LOW")

    # Listener de máxima prioridad (HIGHEST)
    async def highest_priority_listener(event: Event):
        execution_order.append("HIGHEST")

    # Registrar en orden inverso
    bus.subscribe("user:action", low_priority_listener, priority=EventPriority.LOW)
    bus.subscribe("user:action", highest_priority_listener, priority=EventPriority.HIGHEST)

    # Publicar evento asíncrono
    await bus.publish_async("user:action", {"action": "click"})

    print(execution_order)  # Salida garantizada: ['HIGHEST', 'LOW']

asyncio.run(main())
```

### Ejemplo C: Tolerancia a Fallos (Fault Tolerance)

```python
from core.event_bus import EventBus, Event

bus = EventBus()

def faulty_listener(event: Event):
    raise ValueError("Error intencional en listener defectuoso")

def safe_listener(event: Event):
    print("Safe listener ejecutado exitosamente!")

bus.subscribe("data:updated", faulty_listener)
bus.subscribe("data:updated", safe_listener)

# El listener defectuoso falla, pero el safe_listener SE EJECUTA de todos modos
bus.publish("data:updated", {"key": "val"})
```
