# JESSYCA BRAIN 1.0 — GUÍA DE USUARIO FINAL PARA WINDOWS 11

Bienvenido a **JESSYCA BRAIN 1.0**, tu Asistente Personal Autónomo e Inteligente diseñado específicamente para Windows 11.

---

## 1. INICIO RÁPIDO

### Opción A: Inicio con Doble Clic (Recomendado)
Haz doble clic sobre el archivo:
[`iniciar_jessyca.bat`](file:///d:/JESSYCA%203.0/asistente-jessyca/iniciar_jessyca.bat)

El asistente comprobará automáticamente que Ollama esté disponible, verificará tu micrófono y altavoces, y te presentará un menú interactivo para elegir el modo de interacción.

### Opción B: Inicio desde la Terminal (PowerShell)
```powershell
# Modo Texto Interactivo (Consola rápida)
python main.py --text

# Modo Voz Interactivo (Escucha continua / Manos libres)
python main.py --voice

# Modo Pulsar para Hablar (PTT con tecla ENTER)
python main.py --voice-ptt

# Prueba Presencial Guiada de Micrófono
python scripts/guided_voice_test.py
```

---

## 2. EJEMPLOS DE ÓRDENES Y COMANDOS REALES

### A. Conversación, Ciencia y Razonamiento
* *"JESSYCA, ¿quién fue Albert Einstein?"*
* *"Explícame qué es el entrelazamiento cuántico en palabras sencillas."*
* *"¿Cuál es la diferencia entre inteligencia artificial y aprendizaje automático?"*
* *(JESSYCA responde de inmediato hablando con su voz natural CamilaNeural sin abrir programas innecesarios).*

### B. Control del Escritorio y Aplicaciones Windows
* *"JESSYCA, abre la Calculadora."*
* *"Abre Bloc de notas."*
* *"Abre YouTube y pon música clásica."*
* *"Baja el volumen al 30 %."*

### C. Redacción de Documentos y Notas
* *"Abre Bloc de notas y escribe un resumen sobre inteligencia artificial en notas.txt."*
* *(JESSYCA redacta el contenido, lo guarda en disco y verifica que el archivo existe y es legible).*

### D. Investigación Web y Búsqueda
* *"Investiga cuáles son los mejores modelos de IA para programar y resume las conclusiones."*
* *"Abre Chrome y busca información sobre Python."*

### E. Órdenes Compuestas Multietapa
* *"JESSYCA, baja el volumen, abre Chrome y busca información sobre computación cuántica."*
* *(JESSYCA planifica un DAG de 3 pasos, ejecuta cada acción ordenadamente y te informa al terminar).*

### F. Memoria y Continuidad
* Turno 1: *"JESSYCA, recuerda que estamos investigando energía de fusión."*
* Turno 2: *"Continúa con lo anterior y dime qué estábamos investigando."*
* *(JESSYCA recupera de su memoria semántica y de trabajo el tema previo y continúa sin perder el hilo).*

### G. Aprendizaje y Reutilización de Procedimientos
* *"JESSYCA, utiliza el procedimiento que aprendiste para preparar otra nota."*
* *(JESSYCA consulta su memoria procedimental y ejecuta la plantilla validada en milisegundos).*

### H. Parada de Emergencia y Cancelación Segura
* *"JESSYCA, detente."* o *"Cancela la tarea."*
* *(El sistema activa de inmediato el Fail-Safe de emergencia e interrumpe cualquier operación activa en el escritorio).*

---

## 3. NOTA SOBRE CAPACIDADES PENDIENTES

* **CUA Driver Externo:** El sistema utiliza actualmente `NativeWindowsDriver`, el cual cubre el 100% del control del escritorio local en Windows 11 sin necesidad de daemons externos. La integración con CUA permanece en estado PENDIENTE y no bloquea tu experiencia cotidiana.
* **WhatsApp Remoto / Wake-on-LAN:** Módulo desacoplado arquitectónicamente para despliegue posterior en VPS independiente.
