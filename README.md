# Jessyca - Asistente de Voz/Texto Local para Windows

Jessyca es un asistente de voz y texto local para Windows con capacidad de control del sistema, diseñado bajo una arquitectura modular y en capas (Orquestador + Cerebro + Skills tipo plugin + Seguridad transversal).

## Estructura del Proyecto

- `config/`: Archivos de configuración YAML (configuración general y mapeo de aplicaciones).
- `core/`: Núcleo del asistente (Orquestador, Cerebro, Motor de Reglas, Seguridad).
- `skills/`: Habilidades y módulos tipo plugin para interactuar con el sistema.
- `audio/`: Módulos de captura de voz (STT) y síntesis de voz (TTS).
- `interfaces/`: Interfaces de entrada y salida (CLI, GUI, WebSocket, etc.).
- `logs/`: Registros de ejecución de la aplicación.
- `tests/`: Pruebas unitarias y de integración.
- `main.py`: Punto de entrada principal de la aplicación.

## Requisitos Previos

- Python 3.10 o superior (Windows)

## Instalación y Configuración

1. Crear y activar el entorno virtual:
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```
2. Instalar las dependencias:
   ```cmd
   pip install -r requirements.txt
   ```
3. Configurar variables de entorno:
   Copiar `.env.example` a `.env` y ajustar según sea necesario.

## Ejecución

```cmd
python main.py
```
