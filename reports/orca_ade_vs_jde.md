# COMPARACIÓN CONCEPTUAL Y ROLES DE AUTORIDAD: JDE vs ORCA vs ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Fecha:** Septiembre 2026  

---

## 1. Principio Fundamental de Gobernanza

En la arquitectura de **JESSYCA PC**, el **JESSYCA Decision Engine (JDE)** es la **Autoridad Suprema de Decisión**. Ningún componente externo, subsistema de agentes ni orquestador de terceros puede arrogarse potestades decisorias, puentear el análisis de riesgos ni autorizar operaciones en el sistema operativo.

El propósito de esta comparativa es delimitar taxativamente las fronteras conceptuales y operativas entre:
1. **JDE** (Motor de Decisión Soberano de JESSYCA).
2. **ORCA** (Entorno de Desarrollo Agéntico / Cockpit de ejecución paralela).
3. **ADE** (Paradigma de desarrollo basado en flotas de agentes y Git Worktrees).

---

## 2. Matriz de Responsabilidades y Roles

| Dimensión Operativa | JESSYCA Decision Engine (JDE) | ORCA (Stably AI) | ADE (Paradigma) | Veredicto Arquitectónico |
| :--- | :--- | :--- | :--- | :--- |
| **¿Quién DECIDE?** | **JDE (Exclusivo)** | El desarrollador humano en la UI | El usuario o el agente líder | **JDE mantiene soberanía absoluta.** Orca jamás decide autónomamente. |
| **¿Quién PROPONE?** | Generadores de intención / Skills / Usuario | Tareas descompuestas hacia agentes | Agentes autónomos | **ORCA/ADE actúa únicamente como emisor de propuestas (Proposals).** |
| **¿Quién PLANIFICA?** | JDE Planner / ARE (DAG causal, impacto) | Task Dispatcher / Tab Splitter | Coordinador de flota | **JDE/ARE define el plan maestro.** Orca solo ejecuta tareas acotadas. |
| **¿Quién AUTORIZA?** | **JDE + RiskEngine + PermissionManager** | Ninguno (confianza ciega en el usuario) | Ninguno intrínseco | **Ninguna acción física procede sin autorización explícita del JDE.** |
| **¿Quién EJECUTA?** | Skills de JESSYCA (vía sandbox) | CLI de agentes en terminales (`node-pty`) | Subprocesos en ramas Git | **Orca solo gestiona el aislamiento de ramas; JESSYCA ejecuta de forma segura.** |
| **¿Quién VERIFICA?** | **ExecutionVerifier** (evidencia física de 6 puntos) | El humano mirando los diffs visualmente | Suite de tests o revisión de PR | **ExecutionVerifier de JESSYCA es el único que certifica el resultado.** |
| **¿Quién REGISTRA?** | Receipts criptográficos / Telemetría JDE | Historial de terminales y logs de PTY | Commits de Git y PR logs | **JDE emite los recibos oficiales inmutables de auditoría.** |
| **¿Quién FALLA SEGURO?** | **JDE Fallback** (degradación a texto/Mermaid) | Interrupción de proceso o terminal muerta | Revert de branch en Git | **JDE garantiza contención sin falsos éxitos.** |

---

## 3. Análisis Detallado de Dimensiones

### 3.1 Autoridad de Decisión vs Espacio de Trabajo
* **JDE:** Es un motor analítico y determinista de políticas, capacidades y permisos. No es una interfaz gráfica; es el cerebro de gobernanza que evalúa cada solicitud y dictamina `ALLOW`, `DENY` o `DEGRADE`.
* **ORCA:** Es una herramienta de productividad para ingeniería de software. Su fortaleza radica en permitir que múltiples terminales operen simultáneamente sin pisarse los archivos mediante ramas de Git.
* **Integración:** ORCA debe ser tratado como un **proveedor de infraestructura de trabajo (Capability Provider)** para tareas complejas de codificación, subordinado en todo momento al dictamen del JDE.

### 3.2 Planificación Causal vs Paralelismo Operativo
* **JDE / ARE:** Razona en base a dependencias lógicas, estados del sistema, seguridad y restricciones de hardware (DAG con análisis de impacto río abajo).
* **ORCA:** Divide un prompt en múltiples ramas de trabajo para que varios modelos propongan soluciones alternativas.
* **Sinergia Posible:** JDE puede decidir: *"Esta tarea de refactorización requiere explorar 2 enfoques en paralelo"*. A continuación, solicita a través del Orca Adapter dos worktrees de prueba, evalúa las propuestas en modo seguro, y selecciona la mejor sin comprometer la rama principal.

### 3.3 Aislamiento de Ejecución y Prevalencia
* Si Orca propone: `EXECUTE "npm install && rm -rf dist"`
* El **JDE + RiskEngine** evalúa la propuesta.
* Si el RiskEngine detecta un patrón destructivo o fuera de permisos, el JDE emite **DENY**.
* El Orca Adapter debe abortar la tarea inmediatamente.
* **Regla Inquebrantable:** En caso de discrepancia, la decisión del JDE prevalece siempre sobre cualquier sugerencia de Orca o sus agentes.

---

## 4. Conclusión

```text
=====================================================
JDE vs ORCA vs ADE CONCLUSION
=====================================================
AUTHORITY: JDE (Single & Supreme Authority)
PROPOSAL ROLE: ORCA / ADE (Capability Provider)
GOVERNANCE: RiskEngine + PermissionManager strictly enforced
VERIFICATION: ExecutionVerifier validates all physical outputs
FALLBACK: Automatic degradation to safe text/internal tools
=====================================================
```
