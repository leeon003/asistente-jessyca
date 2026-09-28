# JESSYCA PC — ANYDOC FASE 1 NETWORK AUDIT

## 1. PRINCIPIO DE AISLAMIENTO OFFLINE
* **Política:** `NETWORK = DENY` obligatorio para conversión local.
* Durante todas las ejecuciones de pruebas y benchmarks con `AnyDocAdapter`, las llamadas a sockets, DNS y HTTP salientes fueron **0**.
* La biblioteca oficial de Rust no contiene telemetría oculta ni llamadas analíticas en su flujo local.

## 2. GOBERNANZA SOBRE HOSTED OCR
* La funcionalidad de OCR alojado en `https://api.firecrawl.dev/v2/parse` implica enviar los bytes completos del documento a servidores externos de Firecrawl.
* **Veredicto en Fase 1:** DESHABILITADO POR DEFECTO (`ocr="reject"` forzado en `AnyDocAdapter`).
* En fases futuras, si se requiere soporte OCR, deberá registrarse como una capacidad independiente `document_processing.ocr_external` clasificada como `RiskLevel.CRITICAL`, con autorización expresa y acotada del JDE.
