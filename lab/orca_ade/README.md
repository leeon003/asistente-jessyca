# LABORATORIO AISLADO: ORCA + ADE (FASE 1)

**Sistema:** JESSYCA PC  
**Módulo:** `lab/orca_ade`  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Modo:** `LAB` / `SHADOW` (Estrictamente no productivo)  
**Autoridad:** JESSYCA Decision Engine (JDE)  

---

## 1. Propósito del Laboratorio

Este entorno de laboratorio proporciona un espacio estrictamente confinado para experimentar con los conceptos de:
1. **Aislamiento mediante Git Worktrees:** Creación de ramas efímeras para que múltiples agentes prueben cambios sin tocar el checkout principal.
2. **Propuestas de Descomposición de Tareas:** Simulación de flotas de sub-agentes en paralelo.
3. **Inspección UI (Design Mode):** Extracción segura de selectores sin navegación descontrolada.

---

## 2. Reglas de Aislamiento Inviolables

1. **PROHIBICIÓN DE SHELLS DEL HOST:** Ningún script de este laboratorio invoca `powershell`, `cmd.exe` ni `bash` de forma no mediada.
2. **CONFINAMIENTO DE FILESYSTEM:** Todas las operaciones de archivo se circunscriben a directorios temporales creados bajo `data/orca_worktrees/` o mocks en memoria.
3. **SUBORDINACIÓN AL JDE:** Toda propuesta de acción debe evaluarse mediante `OrcaAdeAdapter.evaluate_proposal()` sujeta a la decisión del JDE (`ALLOW` o `DENY`).
4. **CERO EFECTOS COLATERALES:** Las pruebas en modo `SHADOW` garantizan `side_effects_produced == 0`.
5. **PROHIBICIÓN DE ACTIVACIÓN EN PRODUCCIÓN:** El modo `ACTIVE` está terminantemente bloqueado y arroja una excepción fatal si se intenta configurar.

---

## 3. Estructura del Directorio

```text
lab/orca_ade/
├── README.md               # Este documento de especificación
├── sandbox.py              # Administrador seguro y mockeado de Git Worktrees
├── fixtures/               # Datos de prueba sintéticos, tareas y cargas adversarias
│   ├── tasks.json          # Casos de prueba estándar
│   └── malicious.json      # Cargas de inyección, traversal y comandos destructivos
├── experiments/            # Ejecutor de experimentos controlados (LAB-01 a LAB-15)
│   └── runner.py           # Script de ejecución de los 15 casos de laboratorio
└── reports/                # Salidas y evidencias de las ejecuciones del LAB
```
