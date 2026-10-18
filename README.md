# JESSYCA: asistente local para Windows

El punto de entrada es `iniciar_jessyca.bat`, que prioriza el entorno virtual local.
La configuración existente se conserva en `.env` y `config/`.

## Entorno

Usar Python 3.11 y el entorno `venv`. Los extras de instalación son `dev`, `voice`,
`documents`, `vad`, `uiautomation` y `pywinauto`; habilitar únicamente los componentes
que se vayan a usar. Ollama debe contener los modelos configurados en `config/models_config.json`.

## Modos

```powershell
.\venv\Scripts\python.exe main.py --text
.\venv\Scripts\python.exe main.py --voice
.\venv\Scripts\python.exe main.py serve --host 127.0.0.1 --port 8088
```

El servicio HTTP requiere el token de autenticación configurado. No publicarlo ni
exponer el servicio fuera del equipo sin revisar sus permisos.

## Reproducción local

«Jessyca, báilame» y «báilame» seleccionan un vídeo de la carpeta configurada
`D:\bailes de ia`, evitando el anterior si hay alternativas. FFplay debe estar en
PATH. El asistente verifica el avance del reloj del reproductor y evita declarar
éxito cuando no puede observarlo. Solo se cierran reproductores creados por esta función.

Para reproducir otros archivos locales, indicar una ruta explícita. Si se solicita
música local sin ubicación, se pide la carpeta; no se sustituyen canciones por vídeos.

## Verificación

Las pruebas están en `tests/`. Algunas requieren Ollama, servicios externos,
dependencias opcionales o escritorio interactivo; revisar cada grupo antes de
ejecutar pruebas que controlen aplicaciones. Los informes de auditoría detallan
qué casos se ejecutaron, sus resultados y las limitaciones pendientes.
