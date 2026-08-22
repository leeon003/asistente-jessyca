# JESSYCA 3.0 — FASE 62: PERSONALIZATION ENGINE
## JESSYCA EXPERIENCE & LEARNING ENGINE

**Fecha de Implementación y Certificación:** 22 de Agosto de 2026  
**Estado:** CERTIFICADO Y VALIDADO (100% Tests Aprobados — 2,119/2,119)

---

## 1. OBJETIVO Y ALCANCE

La **Fase 62** implementa el **Personalization Engine**, el motor de aprendizaje de preferencias, aliases de comandos y hábitos de interacción de JESSYCA, bajo una regla fundamental e inquebrantable de diseño:

$$\mathbf{PREFERENCIA \neq AUTORIZACI\acute{O}N} \quad \text{y} \quad \mathbf{APRENDIZAJE \neq SEGURIDAD}$$

### Principios e Invariantes Fundamentales:
1. **Aislamiento Absoluto de Seguridad:** Una preferencia aprendida (ej. `"notas"` $\to$ `"notepad"` o `"navegador"` $\to$ `"msedge"`) opera exclusivamente como alias contextual o valor por defecto de intención. **NUNCA** otorga permisos, ni bypassea confirmaciones, ni altera el `PermissionManager`, `RiskEngine` o `SecurityPolicy`.
2. **Dinámica de Confianza y Acumulación de Evidencia:**
   - 1 interacción inferida $\to$ `CANDIDATE` con confianza baja ($0.35$).
   - Evidencia repetida consistente $\to$ Incrementa confianza ($+0.15$) hasta alcanzar `ACTIVE` ($\ge 0.70$).
   - Confirmación explícita del usuario $\to$ Salto directo a `ACTIVE` con confianza $\ge 0.95$.
   - Contradicciones del usuario $\to$ Penalización ($-0.25$) y degradación a `CANDIDATE` o `FORGOTTEN` ($< 0.25$).
3. **Decaimiento Temporal y Expiración:** Las preferencias en desuso prolongado sufren un decaimiento determinista ($1\%$ diario) hasta pasar a `EXPIRED`.
4. **Sanitización y Cero Fugas:** Queda terminantemente prohibido almacenar contraseñas, tokens, credenciales o términos de bypass (`password`, `token`, `api_key`, `grant_permission`, etc.).
5. **Resolución Determinista de Conflictos:** Algoritmo para resolver colisiones sobre la misma clave priorizando la alternativa con mayor confianza y conteo de evidencias.

---

## 2. ARQUITECTURA DEL PAQUETE `core/personalization/`

```text
core/personalization/
├── __init__.py                  # Exportaciones unificadas del paquete
├── preference_models.py         # Modelos Pydantic v2 (UserPreference, PreferenceStatus, etc.)
├── preference_validator.py      # Validador de seguridad, no bypass y sanitización
├── preference_confidence.py     # Cálculo dinámico de confianza, evidencia y time decay
├── preference_store.py          # Almacenes persistentes InMemory y SQLite (preferences.db)
└── preference_engine.py         # Motor de gestión, confirmación y resolución de conflictos
```

---

## 3. COMPONENTES Y RESPONSABILIDADES

### 3.1 `preference_models.py`
- `PreferenceStatus`: `CANDIDATE`, `ACTIVE`, `REJECTED`, `EXPIRED`, `FORGOTTEN`.
- `PreferenceCategory`: `COMMAND_ALIAS`, `APPLICATION_PREFERENCE`, `BROWSER_PREFERENCE`, `RESPONSE_STYLE`, `CLARIFICATION_PREFERENCE`, `WORKFLOW_PREFERENCE`, `LANGUAGE_PREFERENCE`, `TIMING_PREFERENCE`.
- `PreferenceSource`: `INFERRED`, `USER_EXPLICIT`, `EXPERIENCE_ANALYSIS`.
- `UserPreference`: Entidad inmutable con clave normalizada, valor, confianza, conteos de evidencia/contradicción y fechas de observación.

### 3.2 `preference_validator.py`
- `FORBIDDEN_PREFERENCE_TERMS`: Bloqueo tajante de secretos y comandos de alteración de seguridad.
- `PreferenceValidator`: Normalización de claves y validación de rangos.

### 3.3 `preference_confidence.py`
- `ConfidenceCalculator`: Algoritmo matemático para sumar evidencia ($+0.15$), procesar confirmaciones explícitas ($\ge 0.95$), penalizar contradicciones ($-0.25$) y aplicar time decay ($1\%$ diario).

### 3.4 `preference_store.py`
- `SQLitePreferenceStore`: Persistencia en SQLite local (`data/preferences.db`) con modo WAL e índices por categoría, clave y estado.

### 3.5 `preference_engine.py`
- `PersonalizationEngine`: Orquestador de observaciones, contradicciones, confirmaciones, consultas de valores preferidos y olvido voluntario (`forget_preference`).

---

## 4. RESULTADOS DE LA CERTIFICACIÓN

### Batería de Pruebas (`pytest`)
- **Suite de Personalization Engine (`tests/personalization/test_personalization_engine.py`):** 13/13 tests aprobados (100%).
- **Suites del Experience & Learning Engine:** 90/90 tests aprobados (100%).
- **Suite de Regresión Global del Sistema:** **2,119/2,119 tests aprobados (100%)** en 183s.
- **Análisis Estático de Tipos (`mypy`):** 0 errores en `core/personalization/`.
- **Linter (`ruff`):** 100% de cumplimiento en estilo y formateo.

---

## 5. CONCLUSIÓN

La Fase 62 dota a JESSYCA de una capacidad de personalización natural y contextual que aprende los hábitos y expresiones del usuario respetando de manera infranqueable la frontera de seguridad y permisos del sistema.
