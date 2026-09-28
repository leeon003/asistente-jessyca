# Auditoría de Consolidación: AnyDoc vs documents_skills

## Fecha de Auditoría: 2026-09-27
## Estado del Sistema: CONTROLLED READY (Audit Only)

---

### 1. Resumen Ejecutivo

Esta auditoría compara en profundidad las capacidades, robustez y consumidores reales de dos subsistemas de procesamiento de documentos presentes en el repositorio:
1. **AnyDoc Core:** `core/anydoc/` (Certificado en Fase 2 en modo `CONTROLLED`).
2. **Documents Skills:** `skills/documents_skills.py` (Habilidades históricas de Fase 28.8).

El objetivo es determinar la brecha técnica entre ambos subsistemas, auditar quién consume `documents_skills.py`, y establecer una estrategia de compatibilidad sin roturas de contrato ni eliminación de código.

---

### 2. Comparación Exhaustiva de Capacidades Técnicas

| Dimensión / Formato | AnyDoc (`core/anydoc/`) | Documents Skills (`skills/documents_skills.py`) | Diferencia y Evaluación |
| :--- | :--- | :--- | :--- |
| **DOC / DOCX / DOCM** | SÍ. Parsing AST estructurado, extracción de párrafos, tablas, estilos y metadatos. | NINGUNA. Abre con `open(..., encoding='utf-8')`, corrompiendo archivos binarios/ZIP. | **AnyDoc estrictamente superior**. `documents_skills` falla con binarios. |
| **PDF** | SÍ. Extracción de capas de texto, estructura de página, metadatos y detección de necesidad de OCR (`NEEDS_OCR`). | NINGUNA. Intenta leer PDF con `open(encoding='utf-8', errors='replace')` generando texto basura. | **AnyDoc estrictamente superior**. |
| **XLS / XLSX / XLSM / XLSB** | SÍ. Extracción de hojas de cálculo, celdas tabulares y conversión a formato Markdown tabular. | NO. No soporta archivos Excel de ninguna extensión. | **Capacidad única de AnyDoc**. |
| **PPT / PPTX / PPS / PPSX** | SÍ. Extracción secuencial de diapositivas, notas del orador y jerarquía de texto. | NO. No soporta presentaciones. | **Capacidad única de AnyDoc**. |
| **CSV** | SÍ. Parseo robusto respetando delimitadores, dialectos y codificaciones. | Parcial. Uso básico de `csv.DictWriter` en memoria. | **AnyDoc superior en validación y encoding**. |
| **ODT / ODS / ODP** | SÍ. Soporte nativo de formatos OpenDocument. | NO. Sin soporte. | **Capacidad única de AnyDoc**. |
| **EPUB / RTF** | SÍ. Extracción de capítulos, flujo de lectura y formato enriquecido. | NO. Sin soporte. | **Capacidad única de AnyDoc**. |
| **Detección de Formato** | Magic Bytes inspeccionando cabeceras hexadecimales reales y estructura MIME. | Solo extensión de archivo (`os.path.splitext`). Vulnerable a extensión falsa. | **AnyDoc inmune a spoofing de extensiones**. |
| **Aislamiento y Sandbox** | Sandbox estricto en `data/anydoc/{input,output,cache,quarantine}` con prevención de path traversal. | Sin sandbox. Rutas directas en el sistema de archivos del host. | **AnyDoc cumple con la política de seguridad**. |
| **Integridad Criptográfica** | Sello criptográfico SHA-256 (`task_contract.seal`) y verificación física (`VERIFIED_SUCCESS`). | Sin verificación de integridad ni hashes. | **AnyDoc no-repudiable**. |
| **Política de Red** | Aislamiento estricto de red saliente (`network_policy = "DENY"`). | No aplica. | **AnyDoc garantizado offline**. |
| **Escritura y Creación** | Conversión estructurada a Markdown, JSON estructurado y almacenamiento de assets. | Creación directa de archivos Markdown con encabezados `# {titulo}`. | **`documents.create` tiene valor para notas rápidas**. |
| **Resumen Semántico** | Extracción estructural lista para consumo de LLM. | Heurística rudimentaria: selecciona las primeras 3 líneas del texto. | **`documents.summarize` es un placeholder léxico**. |

---

### 3. Matriz de Formatos Soportados

| Formato | AnyDoc | documents_skills | Cobertura Real |
| :---: | :---: | :---: | :--- |
| **DOCX** | ✅ SÍ | ❌ Falso Soporte (Text open) | Solo AnyDoc |
| **PDF** | ✅ SÍ | ❌ Falso Soporte (Text open) | Solo AnyDoc |
| **XLSX** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **PPTX** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **CSV** | ✅ SÍ | ⚠️ Básico | Ambos |
| **ODT** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **ODS** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **ODP** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **EPUB** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **RTF** | ✅ SÍ | ❌ NO | Solo AnyDoc |
| **TXT / MD**| ✅ SÍ | ✅ SÍ | Ambos |

---

### 4. Auditoría de Consumidores de `documents_skills.py`

Búsqueda de dependencias e invocaciones en todo el repositorio:

1. **`skills/__init__.py`:**
   - **Imports:** `DocumentsReadSkill`, `DocumentsCreateSkill`, `DocumentsSummarizeSkill`, `DocumentsConvertSkill`.
   - **Registro de Catálogo:** Instanciación en `_DEFAULT_SKILLS = {"documents.read": DocumentsReadSkill(), ...}`.
   - **Ruta:** `PUBLIC CATALOG / EXPORT`.
2. **`core/__init__.py`:**
   - **Imports:** Re-exportación en el catálogo global de clases del Core.
   - **Ruta:** `BACKWARD COMPATIBILITY EXPORT`.
3. **`tests/skills/test_initial_skill_catalog.py`:**
   - **Prueba:** `test_documents_skills_pipeline(self)` (Línea 229).
   - **Invocación:** Verifica que `DocumentsReadSkill`, `DocumentsCreateSkill` y `DocumentsSummarizeSkill` respondan a llamadas básicas de prueba.
   - **Ruta:** `TEST ONLY`.
4. **`tests/skills/test_skill_graph.py`:**
   - **Import:** `DocumentsReadSkill` (Línea 32).
   - **Uso:** Nodo de soporte en pruebas del planificador de grafos.
   - **Ruta:** `TEST ONLY`.
5. **`benchmarks/real_world_benchmark_100.py`:**
   - **Línea:** 57, 331.
   - **Uso:** Medición de latencia de lectura de archivos locales de texto.
   - **Ruta:** `BENCHMARK ONLY`.

---

### 5. Clasificación de Componentes

- **AnyDoc (`core/anydoc/`):**
  - **Estado:** `PRODUCTION CERTIFIED / CONTROLLED READY`.
  - **Función:** Motor oficial de ingestión, extracción estructural y conversión de documentos para JESSYCA PC.
- **Documents Skills (`skills/documents_skills.py`):**
  - **Estado:** `COMPATIBILITY / LEGACY`.
  - **Función:** Catálogo inicial de compatibilidad. No procesa formatos complejos ni cuenta con sandbox ni verificación de integridad.

---

### 6. Recomendación Arquitectónica y Hoja de Ruta

**Dictamen:** `KEEP + COMPATIBILITY WRAPPER (NO BORRAR)`.

1. **Invariante:** No eliminar `skills/documents_skills.py` en esta fase. Su presencia es requerida por los 10 tests de `test_initial_skill_catalog.py`, `test_skill_graph.py` y los benchmarks de regresión.
2. **Evolución Futura (Fase de Consolidación):**
   - Refactorizar internamente `DocumentsReadSkill.ejecutar()` para que, si el archivo no es texto plano simple (`.txt`, `.md`), delegue transparentemente en el adaptador `AnyDoc` dentro del sandbox, manteniendo la firma de entrada/salida exacta.
   - Preservar `DocumentsCreateSkill` como utilidad ligera para escritura de notas Markdown.
   - Marcar `DocumentsConvertSkill` como deprecado en favor de `AnyDocTaskContract`.
