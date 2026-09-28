# Auditoría y Matriz de Solapamiento: ARE vs Skill Graph Planner

**Fecha:** 2026-09-27  
**Fase:** Fase 2 — Auditoría de Planificadores  
**Estado:** AUDITADO / MATRIZ DEFINIDA / NO DESTRUCCIÓN  

---

## 1. Contexto y Objetivos

En el ecosistema JESSYCA PC coexisten dos artefactos relacionados con la planificación y orquestación de tareas complejas:
1. `skills/skill_graph_planner.py`: Planificador histórico basado en grafos dirigidos acíclicos (DAG) de dependencias de skills, resolución topológica, propagación de contexto (`SkillData`), y ejecución secuencial/reductiva de sub-skills.
2. `core/integration/adapters/are_adapter.py` + `core/are/`: Action Reasoning Engine (ARE), formalizado como adaptador del Integration Hub y motor de razonamiento de planes complejos, descomposición semántica (`are.decompose_task`), evaluación de viabilidad (`are.evaluate_plan`), diagnóstico de fallos (`are.diagnose_failure`), y recuperación/re-planificación (`are.recover_plan`).

El objetivo de esta auditoría es determinar con rigor técnico el solapamiento funcional, las capacidades exclusivas y la estrategia de coexistencia sin eliminar código prematuramente.

---

## 2. Análisis Comparativo

### 2.1 Qué funciones realiza Skill Graph Planner (`skills/skill_graph_planner.py`)
- Define tipos de datos de bajo nivel para skills: `SkillRequirement`, `SkillDependencyEdge`, `SkillData`, `ExecutionPlan`, `ExecutionTrace`.
- Provee un registro de tipos de datos requeridos/producidos por skills (`TypeRegistry`).
- Construye un grafo dirigido (NetworkX o ad-hoc DAG) mapeando skills candidatos a resolver dependencias de datos.
- Resuelve orden topológico y valida consistencia de tipos.
- Ejecuta los pasos interactuando directamente con el registro de skills locales.

### 2.2 Qué funciones realiza actualmente ARE (`core/integration/adapters/are_adapter.py`)
- Provee interfaz formal de adapter (`IIntegrationAdapter`) desacoplada con 4 capabilities certificadas:
  - `are.decompose_task`: Descompone solicitudes complejas del usuario en pasos estructurados con dependencias, precondiciones y metadatos.
  - `are.evaluate_plan`: Evalúa consistencia de dependencias, viabilidad de capabilities requeridas, coherencia de pre/postcondiciones y riesgos.
  - `are.diagnose_failure`: Analiza errores y trazas de ejecución determinando categoría de causa raíz, severidad y recuperabilidad.
  - `are.recover_plan`: Genera planes de mitigación, pasos alternativos o rollback cuando un paso falla.
- Genera propuestas estructuradas de datos (`AREPlanProposal`, `AREStepProposal`, `ARERecoveryProposal`) con hash de integridad SHA-256 (`integrity_hash`).
- Opera estrictamente sin efectos secundarios directos, delegando autorización y ejecución a JDE.

### 2.3 Qué funciones se solapan
- **Descomposición de tareas en sub-pasos:** Ambos definen planes estructurados con dependencias (`depends_on`).
- **Validación de dependencias del plan:** Ambos verifican que los pasos previos requeridos existan antes de ejecutar un paso dependiente.
- **Rastreo de contexto/datos entre pasos:** Ambos modelan cómo la salida de un paso alimenta al siguiente.

### 2.4 Qué funciones son exclusivas de cada uno
- **Exclusivas de ARE:**
  - Descomposición semántica mediante razonamiento estructurado / LLM prompts gobernados.
  - Diagnóstico sistemático de causa raíz ante fallos (`are.diagnose_failure`).
  - Formulación de propuestas de recuperación y reintento contextual (`are.recover_plan`).
  - Hash de integridad de planes y firma criptográfica para gobernanza JDE.
  - Aislamiento completo de ejecución: ARE es puramente consultivo/analítico (cero side effects).
- **Exclusivas de Skill Graph Planner:**
  - Sistema de tipos formal a nivel de Python (`TypeRegistry`) para datos de entrada/salida entre skills en memoria.
  - Resolución determinista de dependencias de tipos de datos fuertemente tipados.
  - Acceso directo al catálogo de skills implementadas internamente.

### 2.5 Autoridad de Planificación
- **Autoridad:** Ningún planificador posee autoridad de ejecución. La única autoridad decisional es **JDE** (Jessyca Decision Engine).
- **Planificador Principal:** **ARE** es el motor de razonamiento de planificación (`PLANNER / ANALYZER / RECOVERY PROPOSER`), dado que genera planes estructurados gobernados, integrados con JDE Runtime Binding y compatibles con ORCA/ADE y AnyDoc.
- **Rol de Skill Graph Planner:** Se mantiene como un motor de grafo de resolución de tipos local subordinable (`DELEGATE TO ARE` / `KEEP` para tipado).

---

## 3. Matriz de Capacidades y Decisiones

| Capacidad | ARE | Skill Graph Planner | Solapamiento | Acción | Justificación |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Descomposición de tareas complejas** | Sí (`are.decompose_task`) | Parcial (basado en catálogo estático) | Alto | **DELEGATE TO ARE** | ARE tiene capacidad semántica, metadatos de riesgo y alineación con JDE. |
| **Generación de DAG de pasos** | Sí (`AREPlanProposal`) | Sí (`ExecutionPlan`) | Alto | **MERGE** | ARE genera la propuesta de DAG; la estructura de dependencias se estandariza en AREPlanProposal. |
| **Resolución de tipos de datos I/O** | Parcial (`required_capabilities`) | Sí (`TypeRegistry`, `SkillData`) | Bajo | **KEEP** | La validación de tipos en memoria de Skill Graph Planner es útil y no debe destruirse. |
| **Evaluación y viabilidad de plan** | Sí (`are.evaluate_plan`) | Parcial (ciclos en DAG) | Medio | **DELEGATE TO ARE** | ARE evalúa dependencias circulares, steps faltantes, capabilities y contexto de riesgo. |
| **Diagnóstico de fallos** | Sí (`are.diagnose_failure`) | No | Nulo | **KEEP (ARE EXCLUSIVE)** | Capacidad exclusiva de ARE. |
| **Estrategia de recuperación / Rollback** | Sí (`are.recover_plan`) | No | Nulo | **KEEP (ARE EXCLUSIVE)** | Capacidad exclusiva de ARE. |
| **Ejecución directa de skills** | No (Prohibido por diseño) | Sí (histórico) | Nulo | **DEPRECATE LATER** | La ejecución directa viola la jerarquía JDE. La ejecución debe siempre pasar por JDE -> Security Layers. |

---

## 4. Reglas de Preservación de Código

1. `skills/skill_graph_planner.py` **NO SE ELIMINA**. Permanece intacto en el repositorio.
2. Los tipos y validadores de `skill_graph_planner.py` se conservan para retrocompatibilidad con pipelines que invoquen validación de tipos locales.
3. El flujo productivo de tareas complejas del agente (`JessycaLocalAgent`) utiliza `ARERuntime` en modo `CONTROLLED`, garantizando que ninguna acción eluda a JDE.
