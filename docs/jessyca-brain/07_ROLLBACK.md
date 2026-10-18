# JESSYCA BRAIN 1.0 — FASE 7: PROCEDIMIENTO OFICIAL DE REVERSIÓN (ROLLBACK)

**Fecha:** 16 de Octubre de 2026  
**Objetivo:** Garantizar que el sistema pueda retornar en cualquier momento a su configuración o estado previo sin pérdida de recuerdos ni corrupción de datos.

---

## 1. NIVELES DE REVERSIÓN DISPONIBLES

Existen 3 niveles de reversión según la necesidad del operador:

```
┌─────────────────────────────────────────────────────────────┐
│                    NIVELES DE REVERSIÓN                     │
├───────────────────┬───────────────────┬─────────────────────┤
│      NIVEL 1      │      NIVEL 2      │       NIVEL 3       │
│  Conmutación Flag │  Restauración BDs │  Reversión Código   │
│   (Sin reinicio)  │   (Desde Backup)  │     (Git Reset)     │
└───────────────────┴───────────────────┴─────────────────────┘
```

---

## 2. PROCEDIMIENTO PASO A PASO

### Nivel 1: Conmutación Rápida del Cerebro (Recomendado)
Para volver de inmediato al motor clásico de JESSYCA sin modificar código ni bases de datos:
1. Abre `config/settings.py` o agrega en tu archivo `.env`:
   ```env
   USE_JESSYCA_BRAIN=False
   ```
2. O en PowerShell temporalmente:
   ```powershell
   $env:USE_JESSYCA_BRAIN = "False"
   python main.py
   ```
*Efecto:* El agente local utilizará de inmediato el motor clásico de habilidades sin invocar `JessycaBrain`.

### Nivel 2: Restauración de Bases de Datos de Memoria
Si se desea restaurar las bases de datos de recuerdos al estado exacto previo a la Fase 7:
1. Asegúrate de cerrar los procesos activos de JESSYCA.
2. Copia los archivos desde el respaldo verificado:
   ```powershell
   # Desde el directorio raíz del proyecto:
   Copy-Item -Path "backups/fase7_pre_consolidation_20261016_121316/data/*" -Destination "data/" -Recurse -Force
   ```
3. Verifica la integridad comparando el hash SHA-256 con el manifiesto `backups/fase7_pre_consolidation_20261016_121316/manifest.json`.

### Nivel 3: Reversión Completa del Código en Git
Para restaurar el código fuente exacto previo a las modificaciones de Fase 7:
```powershell
git checkout feature/jessyca-brain-1.0
git status
# Para descartar cambios locales de trabajo si fuera requerido:
# git restore config/ core/ tests/
```

---

## 3. CHECKLIST DE COMPROBACIÓN POST-ROLLBACK

Tras realizar un rollback:
1. Ejecuta `python -c "from config.settings import get_settings; print(get_settings().USE_JESSYCA_BRAIN)"` y confirma el valor esperado.
2. Ejecuta `pytest tests/acceptance/test_fase7_acceptance_30_scenarios.py` y valida 31/31 aprobados.
3. Inicia `iniciar_jessyca.bat` y verifica el arranque sin excepciones.
