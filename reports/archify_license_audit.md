# AUDITORÍA DE LICENCIA: ARCHIFY

**Fecha:** 2026-09-27  
**Proyecto Evaluado:** `tt-a1i/archify` (versión 2.17.x)  
**Autor Original:** tt-a1i (Archify) / Cocoon AI (Cocoon-AI/architecture-diagram-generator)  
**Destino de Integración:** JESSYCA PC (`D:\JESSYCA 3.0\asistente-jessyca`)  
**Licencia de JESSYCA:** MIT  
**Estado:** COMPATIBLE — APROBADO CON CONDICIONES

---

## 1. TÉRMINOS EXACTOS DE LA LICENCIA

Archify está publicado bajo la **Licencia MIT**:

```text
MIT License

Copyright (c) 2026 tt-a1i (Archify)
Copyright (c) 2025 Cocoon AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. EVALUACIÓN DE CONDICIONES LEGALES

| Aspecto | Evaluación | Impacto en JESSYCA |
|---|---|---|
| **Commercial Use** | Permitido | Compatible con el uso comercial e institucional de JESSYCA. |
| **Modification** | Permitido | Permite adaptar esquemas, validadores y plantillas. |
| **Distribution** | Permitido | Permite distribuir scripts o artefactos generados. |
| **Sublicensing** | Permitido | Compatible con la licencia MIT planificada de JESSYCA. |
| **Attribution** | Obligatorio | Debe conservarse el copyright notice de tt-a1i y Cocoon AI si se empaqueta código fuente. |
| **Copyleft** | Ninguno (Permisiva) | No impone obligaciones de liberar componentes privativos ni de Core. |

---

## 3. DECISIÓN ARQUITECTÓNICA DE INTEGRACIÓN

Para mantener la máxima higiene legal, modularidad y evitar contaminación de código fuente:

1. **NO copiar código fuente masivo de Archify al Core de JESSYCA**: JESSYCA interactuará con Archify a través de su **especificación declarativa JSON** y mediante un **Bridge / Adapter desacoplado** (`JessycaArchifyAdapter`).
2. **Uso de Interfaces de Protocolo**: La generación y validación se orquestará mediante contratos de datos (`ArchifyDiagramSpec`), schemas JSON y ejecución aislada de Node.js / CLI en subprocess o sandbox.
3. **Mantenimiento de Créditos y Atribución**: Cualquier schema o referencia utilizada incluirá explícitamente el copyright de `tt-a1i` y `Cocoon AI`.

---

## 4. CONCLUSIÓN DE LICENCIA

**DICTAMEN: COMPATIBLE (PASS)**.  
No existen impedimentos legales para integrar Archify como herramienta de visualización técnica asistida dentro de JESSYCA PC, siempre respetando la arquitectura de Adapter aislado.
