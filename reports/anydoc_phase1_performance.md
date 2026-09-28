# JESSYCA PC — ANYDOC FASE 1 PERFORMANCE REPORT

## METROLOGÍA DE RENDIMIENTO LOCAL (HARDWARE REAL)
* **Plataforma:** Windows 11 AMD64
* **Procesador:** CPU Host (Multinúcleo)
* **GPU / VRAM:** NVIDIA GeForce RTX 3060 12GB (0 MB consumidos — 100% libre para LLMs locales)

### Medición de Latencias de Conversión (10 iteraciones warm)

| Formato | Tamaño Entrada | Salida Markdown | Cold Start | Warm Promedio | Mínimo | Máximo | RAM Proceso |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CSV** | 210 B | 294 caracteres | 0.38 ms | **0.21 ms** | 0.20 ms | 0.23 ms | 25.0 MB |
| **DOCX** | 10,159 B | 1,291 caracteres | 1.64 ms | **1.30 ms** | 1.16 ms | 1.86 ms | 26.1 MB |
| **XLSX** | 7,106 B | 396 caracteres | 1.12 ms | **0.65 ms** | 0.54 ms | 0.86 ms | 26.2 MB |
| **PPTX** | 15,734 B | 273 caracteres | 1.02 ms | **0.87 ms** | 0.85 ms | 0.89 ms | 26.4 MB |
| **PDF** | 90,060 B | 1,070 caracteres | 9.41 ms | **7.43 ms** | 6.76 ms | 8.16 ms | 32.7 MB |
| **RTF** | 20,136 B | 1,296 caracteres | 0.92 ms | **0.77 ms** | 0.74 ms | 0.83 ms | 32.8 MB |
| **ODT** | 25,489 B | 1,297 caracteres | 1.11 ms | **0.78 ms** | 0.71 ms | 0.89 ms | 32.7 MB |
| **EPUB** | 6,167 B | 757 caracteres | 0.47 ms | **0.40 ms** | 0.37 ms | 0.55 ms | 32.8 MB |

### Conclusiones de Rendimiento
1. **Velocidad Extrema:** Conversiones de documentos ofimáticos complejos toman entre 0.4 ms y 1.3 ms. PDFs de ~90 KB toman menos de 7.5 ms.
2. **Eficiencia de Memoria:** El incremento de huella de memoria durante conversiones intensivas es inferior a 8 MB en el proceso Python.
