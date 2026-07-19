# 🎬 YTDownloader Kadir v8.1 — Definitive Edition

Un potente gestor de descargas multimedia universal optimizado para la automatización de bases de conocimiento y entornos personales de Obsidian. Cuenta con un diseño premium Sci-Fi Cyberpunk/Dark basado en `customtkinter`, soporte multihilo distribuido y un motor híbrido inteligente que alterna entre análisis nativo por `yt-dlp` y bypass mediante la API de `Piped`.

---

## ✨ Características Principales

### ⚙️ Motor de Descarga Avanzado
**Bypass Inteligente (Híbrido):** Intento principal mediante `yt-dlp` clásico con caída automática (*fallback*) a la API de Piped si se detectan bloqueos de red o de región.
* **Control de Duplicados Persistente:** Mantiene un registro local (`_registro_descargas.json`) por carpeta para evitar volver a descargar recursos ya indexados.
* **Manejo de Colas Múltiples:** Interfaz dedicada para pegar y procesar lotes con decenas de URLs (individuales o listas completas) de forma secuencial.
* **Recorte de Segmentos Exacto:** Permite descargar únicamente fragmentos específicos de tiempo definiendo marcas de inicio y fin (`mm:ss`).
* **Seguridad de Operación:** Validación automatizada de espacio libre en disco antes de iniciar flujos pesados.

### 🧠 Automatizaciones para la Base de Conocimiento (Obsidian/Logseq)
* **Indexación en Markdown (.md):** Genera una ficha técnica limpia y metadatos atómicos (Frontmatter en YAML) listos para herramientas de personal knowledge management (PKM).
* **Índices Estructurales (MOC):** Al descargar Playlists completas, crea de forma automática un archivo maestro (`_Indice_MOC.md`) con enlaces internos hacia cada video y sus tiempos correspondientes.
* **Capítulos Interactivos:** Extrae las marcas de tiempo nativas de los videos y las mapea en el archivo Markdown como enlaces dinámicos de origen.
* **Incrustación de Metadatos y Miniaturas:** Forzado automático de etiquetas atómicas ID3/XMP (autor, enlace, fecha) e incrustación de miniaturas HD dentro de los contenedores MP4/MP3.

### 🎙️ Inteligencia Artificial: Transcripción con Whisper
* **Módulo de Audio a Texto:** Transcribe de forma nativa usando modelos de OpenAI Whisper.
* **Arquitectura de Respaldo Lógica:** Intenta la ejecución acelerada en CPU mediante `faster-whisper` (int8) y cae de forma segura a `openai-whisper` clásico si el primero no está presente.
* **Modo "Solo Transcripción":** Descarga un *stream* de audio liviano, procesa el texto para añadirlo directamente a la nota `.md` y elimina el archivo multimedia pesado para economizar almacenamiento en disco.

---

## 🛠️ Modos de Uso

El programa está diseñado con una arquitectura dual que permite ejecutar tanto una suite gráfica avanzada como un utilitario ágil por terminal.

### 1. Modo Interfaz Gráfica (GUI)
Si ejecutas el script sin argumentos adicionales, se inicializará el panel unificado:
```bash
python youtube_downloader.py
```
### 2. Modo Línea de Comandos (CLI)
Ideal para scripting, servidores o flujos automatizados de terminal:
```bash
# Descarga estándar de video con calidad acotada
python youtube_downloader.py "[https://www.youtube.com/watch?v=VIDEO_ID](https://www.youtube.com/watch?v=VIDEO_ID)" --quality 1080 -o ~/Ruta/Destino
```

# Descargar solo audio extraído en MP3
```bash
python youtube_downloader.py "[https://www.youtube.com/watch?v=VIDEO_ID](https://www.youtube.com/watch?v=VIDEO_ID)" --audio
```

# Modo Inteligencia Artificial: Solo transcripción (Genera solo la nota Markdown con el texto)
```bash
python youtube_downloader.py "[https://www.youtube.com/watch?v=VIDEO_ID](https://www.youtube.com/watch?v=VIDEO_ID)" --transcribe-only --whisper-model small
```
```
## 📋 Requisitos del Sistema y Dependencias
Para asegurar el funcionamiento óptimo de todos los componentes de post-procesamiento e IA, se requieren las siguientes librerías y binarios:
### Dependencias Base (Python)
```bash
pip install requests customtkinter pillow yt-dlp
```
### Inteligencia Artificial (Opcional, para Transcripción)
```bash
# Recomendado por rendimiento (Aceleración int8)
pip install faster-whisper

# O de forma clásica
pip install openai-whisper
```
### Dependencia de Sistema (FFmpeg)
El programa cuenta con detección inteligente local en la carpeta binarios/win o binarios/linux. En caso de no incluir los binarios en el despliegue de la app, asegúrate de tener ffmpeg instalado en las variables de entorno de tu sistema operativo:
 * **Linux:** sudo apt install ffmpeg o sudo dnf install ffmpeg
 * **Windows/macOS:** Descarga desde el sitio oficial e inclúyelo en tu PATH.
## 📂 Estructura Interna del Repositorio
```text
├── youtube_downloader.py             # Script Principal (Punto de entrada Dual CLI/GUI)
├── binarios/                         # Carpeta opcional de binarios estáticos empacados
│   ├── win/                          # ffmpeg.exe y ffprobe.exe para Windows
│   └── linux/                        # ffmpeg y ffprobe con permisos de ejecución para Linux
└── README.md                         # Documentación técnica

```
## ⚙️ Configuración y Diseño de la Interfaz
 * **Tema Visual:** Configuración unificada *Premium Dark* mediante paletas de grises zinc de alta densidad (#18181A, #09090B) y contrastes en verde esmeralda y azul cyberpunk.
 * **Soporte de Idiomas (i18n):** Traducción parcial en tiempo de ejecución para controles de interfaz clave (Español / Inglés) conmutables mediante un clic.
