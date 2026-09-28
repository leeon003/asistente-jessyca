# AUDITORÍA DE LICENCIA: ORCA + ADE

**Sistema:** JESSYCA PC  
**Módulo:** Integración ORCA + ADE  
**Fase:** Fase 1 — Discovery / Audit / Lab  
**Fecha:** Septiembre 2026  
**Resultado de Auditoría:** **COMPATIBLE**  

---

## 1. Identificación Legal de los Componentes

### 1.1 ORCA (Stably AI / Lovecast Inc.)
* **Repositorio Oficial:** [github.com/stablyai/orca](https://github.com/stablyai/orca)
* **Organización / Autor:** Lovecast Inc. / Stably AI (`stablyai`)
* **Licencia Declarada:** **MIT License**
* **Texto de Copyright:** `Copyright (c) 2026 Lovecast Inc.`
* **Archivo de Licencia:** `LICENSE` en la raíz del repositorio oficial.

### 1.2 ADE (Agentic Development Environment)
* **Naturaleza:** "ADE" no es una entidad legal independiente ni una librería cerrada con licencia privativa en este contexto; es el **paradigma y categoría arquitectónica** ("Agentic Development Environment" o "Agent Development Environment") implementado y liderado por el proyecto open-source Orca de Stably AI.
* **Términos de Referencia:** Cualquier especificación o esquema del entorno ADE derivado de Orca hereda la licencia MIT del proyecto matriz.

---

## 2. Análisis de Términos de la Licencia MIT

La licencia MIT es una de las licencias permisivas de código abierto más estándar y flexibles de la industria.

| Cláusula / Derecho | Concesión MIT | Implicación para JESSYCA |
| :--- | :---: | :--- |
| **Uso Comercial** | Permitido | JESSYCA puede utilizarse en entornos comerciales sin restricciones de regalía. |
| **Modificación** | Permitido | Es posible adaptar, refactorizar o extraer conceptos de adaptadores. |
| **Distribución** | Permitido | JESSYCA puede redistribuir código derivado o adaptadores empaquetados. |
| **Sublicenciamiento** | Permitido | Permite incorporar contratos de interfaz bajo los términos de JESSYCA. |
| **Uso Privado / Local** | Permitido | Se permite la ejecución aislada en laboratorios y entornos locales. |
| **Responsabilidad y Garantía** | "AS IS" (Exclusión total) | El autor original no asume responsabilidad ni garantía de idoneidad. |

---

## 3. Requisitos y Obligaciones

Para mantener pleno cumplimiento con la licencia MIT:

1. **Aviso de Copyright y Licencia:**
   Toda copia sustancial o archivo de código fuente derivado o adaptado directamente del proyecto Orca debe incluir la nota de copyright:
   ```text
   Copyright (c) 2026 Lovecast Inc.
   Licensed under the MIT License.
   ```
2. **No Alteración del Aviso:** No se deben suprimir los avisos de licencia en archivos de terceros que se incorporen al repositorio.

---

## 4. Dependencias Críticas del Ecosistema Orca

Orca utiliza una pila basada en Node.js, Electron, React y TypeScript. Sus dependencias principales y sus respectivas licencias son:

| Dependencia | Propósito | Licencia Típica | Compatibilidad |
| :--- | :--- | :---: | :---: |
| **Electron** | Contenedor de escritorio | MIT | Compatible |
| **React** | Framework UI | MIT | Compatible |
| **node-pty** | Emulación de pseudoterminal | MIT | Compatible |
| **xterm.js** | Renderizado de terminal | MIT | Compatible |
| **Monaco Editor** | Editor de código embebido | MIT | Compatible |
| **Zustand** | Gestión de estado | MIT | Compatible |
| **Vitest / Oxlint** | Herramientas de test y linting | MIT | Compatible |

Ninguna de las dependencias nucleares de Orca impone licencias copyleft restrictivas (como GPLv3 o AGPLv3) que pudiesen contaminar el código fuente de JESSYCA.

---

## 5. Dictamen de Compatibilidad con JESSYCA

* **Licencia de JESSYCA:** Código abierto permisivo / modular.
* **Compatibilidad:** **100% COMPATIBLE**.
* **Condición de Integración:** La eventual integración de adaptadores, interfaces RPC o esquemas de trabajo de Orca en JESSYCA cumple plenamente con los requisitos legales mediante la preservación del aviso de atribución a Lovecast Inc.

```text
=====================================================
ORCA + ADE LICENSE AUDIT VERDICT
=====================================================
STATUS: COMPATIBLE
OBLIGATIONS: Preserve Lovecast Inc. MIT copyright notice
RESTRICTIONS: None (Permissive)
=====================================================
```
