# Arquitectura del AI Planner

Este documento describe la arquitectura, estructuras de datos y principios de funcionamiento del **AI Planner** (`core/planner.py`) en **Jessyca Windows MCP**.

---

## 1. Regla Fundamental de Aislamiento

> [!IMPORTANT]
> El **AI Planner NO ejecuta herramientas** ni interactúa con la capa de transporte del servidor MCP.
> Su función exclusiva es recibir intenciones en lenguaje natural, analizar el contexto activo del usuario y generar un **Plan de Ejecución Estructurado (`ExecutionPlan`)** agnóstico del modelo LLM.

---

## 2. Estructura del Plan de Ejecución (`ExecutionPlan`)

```mermaid
flowchart TD
    Plan[ExecutionPlan] --> Meta[Metadatos del Plan: plan_id, goal, total_risk, required_context]
    Plan --> Subtasks[Lista de SubTask Ordenadas]
    
    Subtasks --> T1[SubTask 1: Inspect - READ_ONLY]
    Subtasks --> T2[SubTask 2: Process - SAFE | Depende de T1]
    Subtasks --> T3[SubTask 3: Delete - DANGEROUS | Depende de T2]
```

### Atributos de `SubTask`

| Atributo | Tipo | Descripción |
| :--- | :--- | :--- |
| **`task_id`** | `str` | Identificador único dentro del plan (ej. `"task_01"`). |
| **`description`** | `str` | Explicación funcional de la subtarea. |
| **`capability_required`** | `Optional[str]` | Dominio de capacidad requerida (ej. `"Filesystem"`, `"Network"`). |
| **`action_required`** | `Optional[str]` | Acción requerida (ej. `"copy"`, `"ping"`). |
| **`dependencies`** | `List[str]` | Lista de `task_id` de las que depende esta tarea. |
| **`risk_level`** | `RiskLevel` | Nivel de riesgo asignado (`READ_ONLY`, `SAFE`, `WARNING`, `DANGEROUS`, `CRITICAL`). |
| **`required_context_keys`** | `List[str]` | Claves del `ContextManager` necesarias (ej. `["active_window"]`). |
| **`execution_order`** | `int` | Posición secuencial sugerida. |

### Atributos de `ExecutionPlan`

- **`plan_id`**: ID único UUID4.
- **`goal`**: Meta expresada originalmente por el usuario en texto libre.
- **`tasks`**: Lista ordenada de subtareas (`SubTask`).
- **`total_risk`**: Nivel de riesgo máximo consolidado a partir de sus subtareas.
- **`required_context`**: Consolidado de todas las claves de contexto exigidas.
- **`created_at`**: Timestamp UTC de creación.

---

## 3. Ejemplo de Uso y Generación de Planes

```python
from core.planner import AIPlanner
from core.context_manager import ContextManager

# 1. Configurar contexto del escritorio
ctx = ContextManager()
ctx.set_current_file("C:/Proyectos/reporte.pdf")
ctx.set_active_window("Explorador de archivos", "explorer.exe", 1024)

# 2. Instanciar el Planner
planner = AIPlanner()

# 3. Crear Plan desde Lenguaje Natural
plan = planner.create_plan(
    natural_language_goal="Copiar reporte.pdf a la carpeta de Respaldos",
    context_snapshot=ctx.get_snapshot()
)

# 4. Validar y consultar el plan (SIN EJECUTAR NADA)
print(f"Plan ID: {plan.plan_id}")
print(f"Riesgo Global Consolidado: {plan.total_risk.value}")
print(f"Contexto Requerido: {plan.required_context}")

# Exportar a JSON para ser consumido por un Executor futuro
json_plan = plan.to_json()
print(json_plan)
```

---

## 4. Validación de Dependencias

El método `plan.validate_dependencies()` realiza dos verificaciones:
1. Comprueba que todas las dependencias nombradas existan en `task_id`.
2. Ejecuta un detector de ciclos para garantizar que el grafo sea **Acíclico (DAG)**, evitando bloqueos infinitos durante una ejecución futura.
