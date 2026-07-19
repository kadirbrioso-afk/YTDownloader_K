import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
import urllib.request
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk
import requests
import yt_dlp
from PIL import Image
from yt_dlp.utils import DownloadCancelled, DownloadError, download_range_func

# Configuración de diseño unificada - Sci-Fi Cyberpunk / Premium Dark
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

VERSION_APP = "8.3"

# NUEVO v8.1: traducciones parciales de interfaz (botones y encabezados
# principales). Los mensajes de estado dinámicos durante análisis/descarga
# permanecen en español por ahora; una i18n completa queda para una futura
# iteración.
TRADUCCIONES = {
    "es": {
        "placeholder_url": "Inserte URL de video individual o lista de reproducción completa (Playlist)...",
        "pegar": "📋 Pegar",
        "analizar": "Analizar Origen",
        "descargar": "Descargar",
        "cancelar": "Cancelar",
        "abrir": "📂 Abrir",
        "historial": "🕘 Ver Historial de Descargas",
        "descargar_cola": "▶ Descargar Cola",
        "boveda": "Bóveda destino / Carpeta de descargas:",
        "calidad": "Calidad:",
        "bitrate": "Bitrate:",
    },
    "en": {
        "placeholder_url": "Paste a single video URL or a full playlist URL...",
        "pegar": "📋 Paste",
        "analizar": "Analyze Source",
        "descargar": "Download",
        "cancelar": "Cancel",
        "abrir": "📂 Open",
        "historial": "🕘 View Download History",
        "descargar_cola": "▶ Download Queue",
        "boveda": "Destination vault / Download folder:",
        "calidad": "Quality:",
        "bitrate": "Bitrate:",
    },
}


# ----------------------------------------------------------------------
# NUEVO v8.1: funciones "puras" a nivel de módulo (sin depender de la GUI).
# Se usan tanto desde la clase (como wrappers finos) como desde el modo CLI,
# para no duplicar lógica ni arriesgar comportamientos distintos entre ambos.
# ----------------------------------------------------------------------
def detectar_ffmpeg():
    ffmpeg_global = shutil.which("ffmpeg")
    if ffmpeg_global:
        return os.path.dirname(ffmpeg_global)

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    dir_os = (
        "win"
        if sys.platform.startswith("win")
        else "linux"
        if sys.platform.startswith("linux")
        else "generic"
    )
    ruta_final = os.path.join(base_path, "binarios", dir_os)

    if dir_os == "linux":
        try:
            for binario in ["ffmpeg", "ffprobe"]:
                camino_bin = os.path.join(ruta_final, binario)
                if os.path.exists(camino_bin):
                    os.chmod(camino_bin, 0o755)
        except Exception:
            pass
    return ruta_final


def sanear_nombre_archivo(titulo):
    titulo_normalizado = (
        unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode("ascii")
    )
    if not titulo_normalizado.strip():
        titulo_normalizado = "Recurso_Multimedia"
    saneado = re.sub(r'[/\\:*?"<>|#^\[\]]', "_", titulo_normalizado)
    saneado = re.sub(r"\s+", " ", saneado).strip()
    return saneado[:120] if len(saneado) > 120 else saneado


def formatear_tamano(tamano_bytes):
    try:
        tamano_bytes = float(tamano_bytes)
    except (TypeError, ValueError):
        return "N/D"
    if tamano_bytes <= 0:
        return "N/D"
    mb = tamano_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def transcribir_audio(ruta_archivo, modelo="base", idioma=None):
    """NUEVO v8.1: transcribe un archivo de audio/video con Whisper.
    Intenta primero 'faster-whisper' (más rápido/liviano) y si no está
    instalado cae a 'openai-whisper'. Si ninguno está disponible, retorna
    None sin lanzar excepción (para no romper el flujo de descarga)."""
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return None
    try:
        from faster_whisper import WhisperModel

        modelo_cargado = WhisperModel(modelo, device="cpu", compute_type="int8")
        segmentos, _ = modelo_cargado.transcribe(ruta_archivo, language=idioma)
        return " ".join(seg.text.strip() for seg in segmentos).strip()
    except ImportError:
        pass
    except Exception as e:
        print(f"Error transcribiendo con faster-whisper: {e}", file=sys.stderr)
        return None

    try:
        import whisper

        modelo_cargado = whisper.load_model(modelo)
        resultado = modelo_cargado.transcribe(ruta_archivo, language=idioma)
        return (resultado.get("text") or "").strip()
    except ImportError:
        return None
    except Exception as e:
        print(f"Error transcribiendo con openai-whisper: {e}", file=sys.stderr)
        return None


def escribir_nota_markdown(
    directorio,
    titulo,
    video_id,
    canal,
    fecha,
    duracion_str,
    duracion_sec,
    url_origen,
    capitulos,
    descripcion_cruda,
    transcripcion=None,
):
    """NUEVO v8.1: extraído de corregir_a_markdown para poder reutilizarlo
    también desde el modo CLI. Ahora acepta una transcripción opcional."""
    try:
        titulo_saneado = sanear_nombre_archivo(titulo)
        for archivo in os.listdir(directorio):
            if archivo.endswith(".description") and video_id in archivo:
                os.remove(os.path.join(directorio, archivo))

        titulo_escapado = titulo.replace("\\", "\\\\").replace('"', '\\"')
        canal_escapado = canal.replace("\\", "\\\\").replace('"', '\\"')

        desc_limpia = re.sub(r"(?m)^---$", "___", descripcion_cruda or "")
        ruta_nueva = os.path.join(directorio, f"{titulo_saneado}.md")

        with open(ruta_nueva, "w", encoding="utf-8") as f:
            f.write(f"""---
title: "{titulo_escapado}"
channel: "{canal_escapado}"
upload_date: {fecha}
duration_seconds: {duracion_sec}
url: "{url_origen}"
type: video_resource
tags: [recurso/video, multimedia/indexado]
---

# {titulo}

## 📋 Ficha Técnica del Recurso
- **Canal Creador:** [[{canal}]]
- **Fecha de Indexación:** {fecha}
- **Duración Total:** {duracion_str}
- **Enlace de Origen:** [{url_origen}]({url_origen})

""")

            if capitulos:
                f.write("## 📌 Índice de Capítulos Interactivos\n")
                for cap in capitulos:
                    sec_inicio = int(cap.get("start_time", 0))
                    t_str = f"{sec_inicio // 60:02d}:{sec_inicio % 60:02d}"
                    f.write(
                        f"- [{t_str}]({url_origen}&t={sec_inicio}s) ➔ {cap.get('title', 'Segmento')}\n"
                    )
                f.write("\n")

            f.write("## 📝 Descripción Original del Video\n---\n")
            f.write(
                desc_limpia.strip() if desc_limpia.strip() else "*Sin descripción.*"
            )

            if transcripcion:
                f.write("\n\n## 🎙️ Transcripción Automática (Whisper)\n---\n")
                f.write(transcripcion.strip())

            f.write("\n\n## 🧠 Mis Notas y Resumen\n---\n- \n")
        return ruta_nueva
    except Exception as e:
        print(f"Error escribiendo Markdown: {e}", file=sys.stderr)
        return None


class YoutubeUniversalDownloader(ctk.CTk):
    REGISTRO_NOMBRE = "_registro_descargas.json"

    def __init__(self):
        super().__init__()

        self.title(f"YTDownloader Kadir v{VERSION_APP} - Definitive Edition (Mejorada)")
        self.geometry("1280x900")
        self.minsize(1150, 780)

        # NUEVO v8.1: idioma activo para la traducción parcial de la interfaz
        self.idioma = "es"

        # Hilos y Ciclo de Vida del Sistema
        self.hilos_activos = []
        self.esta_cerrando = False
        self.lock_hilos = threading.Lock()

        # NUEVO: control de cancelación de descargas
        self.evento_cancelar = threading.Event()

        # Conectividad Persistente
        self.http_session = requests.Session()
        self.http_session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
            }
        )

        # Estado Técnico en Caché
        self.url_miniatura = ""
        self.url_limpia = ""
        self.id_video_actual = ""
        self.titulo_video_actual = ""
        self.canal_video_actual = ""
        self.fecha_video_actual = ""
        self.duracion_segundos = 0
        self.duracion_string_actual = ""
        self.stream_directo_piped = ""
        self.descripcion_piped = ""
        self.es_playlist = False

        # NUEVO: estado para las mejoras
        self.resoluciones_detectadas = []  # resoluciones reales detectadas en el análisis
        self.origen_actual = ""  # "Piped" o "yt-dlp Clásico", para el badge
        self.ultima_ruta_descarga = ""  # para el botón "Abrir carpeta"
        self.cola_urls = []  # cola de descargas múltiples

        # NUEVO: historial persistente de descargas
        self.RUTA_HISTORIAL = os.path.join(
            os.path.expanduser("~"), ".ytdownloader_historial.json"
        )
        self.historial_descargas = self.cargar_historial()

        # Localización de Dependencias Estructurales
        self.ruta_ffmpeg = self.obtener_ruta_ffmpeg_inteligente()

        # Variables Reactivas para la UI
        self.meta_vars = {
            "📌 Título:": tk.StringVar(value="-"),
            "👤 Canal:": tk.StringVar(value="-"),
            "⏱️ Duración:": tk.StringVar(value="-"),
            "👁️ Vistas:": tk.StringVar(value="-"),
            "👍 Likes:": tk.StringVar(value="-"),
            "📅 Fecha:": tk.StringVar(value="-"),
        }

        default_path = os.path.join(os.path.expanduser("~"), "Downloads")
        self.download_path = tk.StringVar(value=default_path)

        self.crear_interfaz_avanzada()
        self.protocol("WM_DELETE_WINDOW", self.cerrar_aplicacion_limpia)

        # NUEVO v8.1: chequeo silencioso de actualización de yt-dlp al arrancar
        self.verificar_actualizacion_ytdlp(manual=False)

    def obtener_ruta_ffmpeg_inteligente(self):
        return detectar_ffmpeg()

    # ------------------------------------------------------------------
    # INTERFAZ
    # ------------------------------------------------------------------
    def crear_interfaz_avanzada(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- PANEL SUPERIOR: BARRA DE COMANDOS E INPUT DE RED ---
        self.frame_superior = ctk.CTkFrame(
            self,
            fg_color="#18181A",
            corner_radius=12,
            border_width=1,
            border_color="#27272A",
        )
        self.frame_superior.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="ew")
        self.frame_superior.grid_columnconfigure(0, weight=1)

        self.entry_url = ctk.CTkEntry(
            self.frame_superior,
            placeholder_text="Inserte URL de video individual o lista de reproducción completa (Playlist)...",
            height=44,
            font=("Helvetica", 13),
            fg_color="#09090B",
            border_color="#27272A",
            text_color="#FAFAFA",
        )
        self.entry_url.grid(row=0, column=0, padx=(15, 8), pady=15, sticky="ew")
        self.entry_url.bind("<Return>", lambda event: self.validar_y_analizar())
        self.entry_url.bind("<KeyRelease>", lambda event: self.detectar_cambio_input())

        self.btn_pegar = ctk.CTkButton(
            self.frame_superior,
            text="📋 Pegar",
            font=("Helvetica", 12, "bold"),
            height=44,
            width=90,
            fg_color="#27272A",
            hover_color="#3F3F46",
            text_color="#FAFAFA",
            command=self.pegar_del_portapapeles,
        )
        self.btn_pegar.grid(row=0, column=1, padx=4, pady=15)

        self.btn_buscar = ctk.CTkButton(
            self.frame_superior,
            text="Analizar Origen",
            font=("Helvetica", 13, "bold"),
            height=44,
            width=150,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            command=self.validar_y_analizar,
        )
        self.btn_buscar.grid(row=0, column=2, padx=(4, 15), pady=15)

        # --- CUERPO DOBLE COLUMNA ---
        self.frame_cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_cuerpo.grid(row=1, column=0, padx=15, pady=0, sticky="nsew")
        self.frame_cuerpo.grid_rowconfigure(0, weight=1)
        self.frame_cuerpo.grid_columnconfigure(0, weight=4)
        self.frame_cuerpo.grid_columnconfigure(1, weight=5)

        # --- COLUMNA IZQUIERDA: METADATA & INSPECCIÓN ---
        self.col_izquierda = ctk.CTkFrame(
            self.frame_cuerpo,
            fg_color="#18181A",
            corner_radius=12,
            border_width=1,
            border_color="#27272A",
        )
        self.col_izquierda.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="nsew")
        self.col_izquierda.grid_columnconfigure(0, weight=1)
        self.col_izquierda.grid_rowconfigure(
            3, weight=1
        )  # MEJORA: fila del textbox se corrió a 3

        self.frame_thumb_wrap = ctk.CTkFrame(
            self.col_izquierda,
            width=320,
            height=180,
            fg_color="#09090B",
            corner_radius=8,
        )
        self.frame_thumb_wrap.grid(row=0, column=0, padx=15, pady=15)
        self.frame_thumb_wrap.pack_propagate(False)
        self.lbl_preview_img = ctk.CTkLabel(
            self.frame_thumb_wrap,
            text="A la espera de telemetría...",
            font=("Helvetica", 12),
            text_color="#71717A",
        )
        self.lbl_preview_img.pack(expand=True, fill="both")

        self.frame_datos_atomicos = ctk.CTkFrame(
            self.col_izquierda, fg_color="#27272A", corner_radius=8
        )
        self.frame_datos_atomicos.grid(
            row=1, column=0, padx=15, pady=(0, 6), sticky="ew"
        )
        self.frame_datos_atomicos.grid_columnconfigure(1, weight=1)

        for idx, (lbl_text, var_obj) in enumerate(self.meta_vars.items()):
            lbl_tit = ctk.CTkLabel(
                self.frame_datos_atomicos,
                text=lbl_text,
                font=("Helvetica", 11, "bold"),
                text_color="#A1A1AA",
                anchor="w",
            )
            lbl_tit.grid(row=idx, column=0, padx=10, pady=5, sticky="w")
            lbl_val = ctk.CTkLabel(
                self.frame_datos_atomicos,
                textvariable=var_obj,
                font=("Helvetica", 11),
                text_color="#FFFFFF",
                anchor="w",
                justify="left",
            )
            lbl_val.grid(row=idx, column=1, padx=5, pady=5, sticky="ew")

        # NUEVO: etiqueta de peso total estimado (para playlists)
        self.lbl_peso_playlist = ctk.CTkLabel(
            self.col_izquierda,
            text="📦 Peso total estimado: -",
            font=("Helvetica", 10),
            text_color="#71717A",
            anchor="w",
        )
        self.lbl_peso_playlist.grid(row=2, column=0, padx=18, pady=(0, 6), sticky="w")

        self.txt_resultados = ctk.CTkTextbox(
            self.col_izquierda,
            font=("Courier New", 11),
            fg_color="#09090B",
            text_color="#22C55E",
            border_width=1,
            border_color="#27272A",
            corner_radius=8,
        )
        self.txt_resultados.grid(row=3, column=0, padx=15, pady=10, sticky="nsew")
        self.imprimir_en_tabla("Consola lista para volcado de flujos...")

        # --- COLUMNA DERECHA: AJUSTES ---
        self.col_derecha = ctk.CTkFrame(
            self.frame_cuerpo,
            fg_color="#18181A",
            corner_radius=12,
            border_width=1,
            border_color="#27272A",
        )
        self.col_derecha.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="nsew")
        self.col_derecha.grid_columnconfigure(0, weight=1)
        self.col_derecha.grid_rowconfigure(
            2, weight=1
        )  # NUEVO: la zona con scroll se expande

        self.frame_ruta = ctk.CTkFrame(self.col_derecha, fg_color="transparent")
        self.frame_ruta.grid(row=0, column=0, padx=15, pady=(15, 4), sticky="ew")
        self.frame_ruta.grid_columnconfigure(0, weight=1)

        self.lbl_titulo_ruta = ctk.CTkLabel(
            self.frame_ruta,
            text="Bóveda destino / Carpeta de descargas:",
            font=("Helvetica", 12, "bold"),
            text_color="#E4E4E7",
        )
        self.lbl_titulo_ruta.grid(row=0, column=0, sticky="w")
        self.path_entry = ctk.CTkEntry(
            self.frame_ruta,
            textvariable=self.download_path,
            state="readonly",
            fg_color="#09090B",
            border_color="#27272A",
            height=36,
        )
        self.path_entry.grid(row=1, column=0, padx=(0, 6), pady=5, sticky="ew")
        self.path_btn = ctk.CTkButton(
            self.frame_ruta,
            text="📁",
            width=42,
            height=36,
            fg_color="#27272A",
            hover_color="#3F3F46",
            command=self.examinar_carpeta,
        )
        self.path_btn.grid(row=1, column=1, pady=5)

        # NUEVO: badge de origen de datos (Piped / yt-dlp clásico)
        self.lbl_origen_badge = ctk.CTkLabel(
            self.col_derecha,
            text="⚪ Origen: -",
            font=("Helvetica", 11, "bold"),
            text_color="#71717A",
            anchor="w",
        )
        self.lbl_origen_badge.grid(row=1, column=0, padx=15, pady=(0, 6), sticky="w")

        # --- ZONA CON SCROLL: contiene todos los ajustes para que quepan en pantalla ---
        self.scroll_settings = ctk.CTkScrollableFrame(
            self.col_derecha, fg_color="transparent", height=330
        )
        self.scroll_settings.grid(row=2, column=0, padx=15, pady=5, sticky="nsew")
        self.scroll_settings.grid_columnconfigure(0, weight=1)

        # Formato y calidad
        self.frame_settings = ctk.CTkFrame(
            self.scroll_settings,
            fg_color="#09090B",
            corner_radius=8,
            border_width=1,
            border_color="#27272A",
        )
        self.frame_settings.pack(fill="x", pady=(0, 10))
        self.frame_settings.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(
            self.frame_settings,
            text="Formato:",
            font=("Helvetica", 11, "bold"),
            text_color="#A1A1AA",
        ).grid(row=0, column=0, padx=10, pady=12, sticky="w")
        self.format_option = ctk.CTkOptionMenu(
            self.frame_settings,
            values=["Video (MP4)", "Solo Audio (MP3)"],
            command=self.gestionar_cambio_formato,
            height=30,
            fg_color="#27272A",
            button_color="#27272A",
        )
        self.format_option.grid(row=0, column=1, padx=5, pady=12, sticky="ew")

        self.res_label = ctk.CTkLabel(
            self.frame_settings,
            text="Calidad:",
            font=("Helvetica", 11, "bold"),
            text_color="#A1A1AA",
        )
        self.res_label.grid(row=0, column=2, padx=10, pady=12, sticky="w")
        self.res_option = ctk.CTkOptionMenu(
            self.frame_settings,
            values=["Máxima Calidad", "1080p", "720p", "480p"],
            height=30,
            fg_color="#27272A",
            button_color="#27272A",
        )
        self.res_option.grid(row=0, column=3, padx=5, pady=12, sticky="ew")

        # NUEVO: recorte de segmento
        self.frame_recorte = ctk.CTkFrame(
            self.scroll_settings,
            fg_color="#09090B",
            corner_radius=8,
            border_width=1,
            border_color="#27272A",
        )
        self.frame_recorte.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            self.frame_recorte,
            text="✂️ Recortar segmento (opcional)",
            font=("Helvetica", 12, "bold"),
            text_color="#E4E4E7",
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 4), sticky="w")
        self.recorte_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.frame_recorte,
            text="Activar recorte",
            variable=self.recorte_var,
            font=("Helvetica", 11),
        ).grid(row=1, column=0, columnspan=4, padx=10, pady=4, sticky="w")
        ctk.CTkLabel(
            self.frame_recorte,
            text="Inicio:",
            font=("Helvetica", 11),
            text_color="#A1A1AA",
        ).grid(row=2, column=0, padx=(10, 2), pady=(2, 12), sticky="w")
        self.entry_recorte_inicio = ctk.CTkEntry(
            self.frame_recorte, placeholder_text="mm:ss", width=80, fg_color="#18181A"
        )
        self.entry_recorte_inicio.grid(
            row=2, column=1, padx=2, pady=(2, 12), sticky="w"
        )
        ctk.CTkLabel(
            self.frame_recorte,
            text="Fin:",
            font=("Helvetica", 11),
            text_color="#A1A1AA",
        ).grid(row=2, column=2, padx=(10, 2), pady=(2, 12), sticky="w")
        self.entry_recorte_fin = ctk.CTkEntry(
            self.frame_recorte, placeholder_text="mm:ss", width=80, fg_color="#18181A"
        )
        self.entry_recorte_fin.grid(row=2, column=3, padx=2, pady=(2, 12), sticky="w")

        # Automatizaciones Obsidian
        self.frame_obsidian_opt = ctk.CTkFrame(
            self.scroll_settings, fg_color="#1F1F23", corner_radius=8
        )
        self.frame_obsidian_opt.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            self.frame_obsidian_opt,
            text="Automatizaciones de la Base de Conocimiento",
            font=("Helvetica", 12, "bold"),
            text_color="#60A5FA",
        ).grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        self.thumb_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.frame_obsidian_opt,
            text="Incrustar miniatura HD en contenedor multimedia",
            variable=self.thumb_var,
            font=("Helvetica", 11),
        ).grid(row=1, column=0, padx=20, pady=6, sticky="w")

        self.meta_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.frame_obsidian_opt,
            text="Forzar metadatos atómicos ID3/XMP (Autor, Enlace, Fecha)",
            variable=self.meta_var,
            font=("Helvetica", 11),
        ).grid(row=2, column=0, padx=20, pady=6, sticky="w")

        self.subs_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.frame_obsidian_opt,
            text="Extraer pistas de subtítulos nativos (VTT)",
            variable=self.subs_var,
            font=("Helvetica", 11),
        ).grid(row=3, column=0, padx=20, pady=6, sticky="w")

        # NUEVO: evitar duplicados
        self.omitir_duplicados_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.frame_obsidian_opt,
            text="Omitir video si ya fue descargado antes en esta carpeta",
            variable=self.omitir_duplicados_var,
            font=("Helvetica", 11),
        ).grid(row=4, column=0, padx=20, pady=6, sticky="w")

        # NUEVO: casilla para hacer opcional la generación de la nota .md
        # (que incluye la descripción del video, ficha técnica y capítulos)
        self.generar_markdown_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.frame_obsidian_opt,
            text="Generar nota Markdown (.md) con descripción y metadatos",
            variable=self.generar_markdown_var,
            font=("Helvetica", 11),
        ).grid(row=5, column=0, padx=20, pady=(6, 12), sticky="w")

        # NUEVO v8.1: transcripción automática con Whisper
        self.frame_transcripcion = ctk.CTkFrame(
            self.scroll_settings,
            fg_color="#09090B",
            corner_radius=8,
            border_width=1,
            border_color="#27272A",
        )
        self.frame_transcripcion.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            self.frame_transcripcion,
            text="🎙️ Transcripción automática (Whisper)",
            font=("Helvetica", 12, "bold"),
            text_color="#E4E4E7",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 4), sticky="w")

        self.transcribir_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.frame_transcripcion,
            text="Generar transcripción e incluirla en la nota",
            variable=self.transcribir_var,
            font=("Helvetica", 11),
        ).grid(row=1, column=0, columnspan=2, padx=10, pady=4, sticky="w")

        self.solo_transcripcion_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.frame_transcripcion,
            text="Modo 'solo transcripción' (no conserva video/audio)",
            variable=self.solo_transcripcion_var,
            font=("Helvetica", 11),
        ).grid(row=2, column=0, columnspan=2, padx=10, pady=4, sticky="w")

        ctk.CTkLabel(
            self.frame_transcripcion,
            text="Modelo:",
            font=("Helvetica", 11),
            text_color="#A1A1AA",
        ).grid(row=3, column=0, padx=(10, 2), pady=(2, 12), sticky="w")
        self.modelo_whisper_option = ctk.CTkOptionMenu(
            self.frame_transcripcion,
            values=["tiny", "base", "small"],
            height=28,
            width=100,
            fg_color="#27272A",
            button_color="#27272A",
        )
        self.modelo_whisper_option.set("base")
        self.modelo_whisper_option.grid(
            row=3, column=1, padx=2, pady=(2, 12), sticky="w"
        )
        ctk.CTkLabel(
            self.frame_transcripcion,
            text="Requiere 'faster-whisper' u 'openai-whisper' instalado",
            font=("Helvetica", 9),
            text_color="#71717A",
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="w")

        # NUEVO: cola de descargas múltiples
        self.frame_cola = ctk.CTkFrame(
            self.scroll_settings, fg_color="#1F1F23", corner_radius=8
        )
        self.frame_cola.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(
            self.frame_cola,
            text="📥 Cola de Descargas (varias URLs)",
            font=("Helvetica", 12, "bold"),
            text_color="#60A5FA",
        ).pack(anchor="w", padx=15, pady=(10, 4))
        ctk.CTkLabel(
            self.frame_cola,
            text="Pega una o varias URLs (una por línea):",
            font=("Helvetica", 10),
            text_color="#A1A1AA",
        ).pack(anchor="w", padx=15)
        self.txt_cola_input = ctk.CTkTextbox(
            self.frame_cola, height=55, fg_color="#09090B", font=("Helvetica", 10)
        )
        self.txt_cola_input.pack(fill="x", padx=15, pady=5)

        frame_cola_botones = ctk.CTkFrame(self.frame_cola, fg_color="transparent")
        frame_cola_botones.pack(fill="x", padx=15)
        ctk.CTkButton(
            frame_cola_botones,
            text="➕ Añadir",
            command=self.agregar_a_cola,
            width=90,
            height=30,
            fg_color="#27272A",
            hover_color="#3F3F46",
        ).pack(side="left", padx=(0, 5))
        ctk.CTkButton(
            frame_cola_botones,
            text="🗑️ Vaciar",
            command=self.vaciar_cola,
            width=90,
            height=30,
            fg_color="#27272A",
            hover_color="#3F3F46",
        ).pack(side="left", padx=5)

        self.txt_cola_preview = ctk.CTkTextbox(
            self.frame_cola,
            height=65,
            fg_color="#09090B",
            font=("Courier New", 10),
            state="disabled",
        )
        self.txt_cola_preview.pack(fill="x", padx=15, pady=5)

        self.btn_cola_iniciar = ctk.CTkButton(
            self.frame_cola,
            text="▶ Descargar Cola (0)",
            command=self.iniciar_cola_descargas,
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
        )
        self.btn_cola_iniciar.pack(fill="x", padx=15, pady=(0, 12))

        # Estado / progreso / acciones (fuera del scroll, siempre visibles)
        self.status_label = ctk.CTkLabel(
            self.col_derecha,
            text="Configure los parámetros y pulse el ejecutor térmico.",
            text_color="#A1A1AA",
            font=("Helvetica", 12, "bold"),
            justify="center",
        )
        self.status_label.grid(row=3, column=0, padx=15, pady=(10, 2))

        self.download_progress = ctk.CTkProgressBar(
            self.col_derecha, height=10, fg_color="#09090B", progress_color="#2563EB"
        )
        self.download_progress.set(0)
        self.download_progress.grid(row=4, column=0, padx=30, pady=10, sticky="ew")

        # NUEVO: fila de botones de acción (Descargar / Cancelar / Abrir Carpeta)
        self.frame_botones_accion = ctk.CTkFrame(
            self.col_derecha, fg_color="transparent"
        )
        self.frame_botones_accion.grid(
            row=5, column=0, padx=30, pady=(0, 8), sticky="ew"
        )
        self.frame_botones_accion.grid_columnconfigure((0, 1, 2), weight=1)

        self.download_btn = ctk.CTkButton(
            self.frame_botones_accion,
            text="Descargar",
            command=self.iniciar_hilo_descarga,
            height=48,
            font=("Helvetica", 13, "bold"),
            fg_color="#16A34A",
            hover_color="#15803D",
            text_color="#FFFFFF",
        )
        self.download_btn.grid(row=0, column=0, padx=3, sticky="ew")

        self.cancel_btn = ctk.CTkButton(
            self.frame_botones_accion,
            text="Cancelar",
            command=self.cancelar_descarga_actual,
            height=48,
            font=("Helvetica", 13, "bold"),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            text_color="#FFFFFF",
            state="disabled",
        )
        self.cancel_btn.grid(row=0, column=1, padx=3, sticky="ew")

        self.btn_abrir_carpeta = ctk.CTkButton(
            self.frame_botones_accion,
            text="📂 Abrir",
            command=self.abrir_ultima_carpeta,
            height=48,
            font=("Helvetica", 13, "bold"),
            fg_color="#27272A",
            hover_color="#3F3F46",
            text_color="#FFFFFF",
            state="disabled",
        )
        self.btn_abrir_carpeta.grid(row=0, column=2, padx=3, sticky="ew")

        self.btn_historial = ctk.CTkButton(
            self.col_derecha,
            text="🕘 Ver Historial de Descargas",
            command=self.mostrar_historial,
            height=34,
            fg_color="#27272A",
            hover_color="#3F3F46",
            text_color="#FAFAFA",
            font=("Helvetica", 12),
        )
        self.btn_historial.grid(row=6, column=0, padx=30, pady=(0, 8), sticky="ew")

        # NUEVO v8.1: preferencias -- tema, idioma y chequeo manual de yt-dlp
        self.frame_prefs = ctk.CTkFrame(self.col_derecha, fg_color="transparent")
        self.frame_prefs.grid(row=7, column=0, padx=30, pady=(0, 15), sticky="ew")
        self.frame_prefs.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_tema = ctk.CTkButton(
            self.frame_prefs,
            text="🌙 Tema",
            command=self.alternar_tema,
            height=30,
            fg_color="#27272A",
            hover_color="#3F3F46",
            font=("Helvetica", 11),
        )
        self.btn_tema.grid(row=0, column=0, padx=2, sticky="ew")

        self.btn_idioma = ctk.CTkButton(
            self.frame_prefs,
            text="🌐 ES/EN",
            command=self.alternar_idioma,
            height=30,
            fg_color="#27272A",
            hover_color="#3F3F46",
            font=("Helvetica", 11),
        )
        self.btn_idioma.grid(row=0, column=1, padx=2, sticky="ew")

        self.btn_check_update = ctk.CTkButton(
            self.frame_prefs,
            text="🔄 yt-dlp",
            command=lambda: self.verificar_actualizacion_ytdlp(manual=True),
            height=30,
            fg_color="#27272A",
            hover_color="#3F3F46",
            font=("Helvetica", 11),
        )
        self.btn_check_update.grid(row=0, column=2, padx=2, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(
            self,
            mode="indefinite",
            height=4,
            fg_color="#18181A",
            progress_color="#2563EB",
        )
        self.progress_bar.grid(row=2, column=0, sticky="ew")
        self.progress_bar.stop()
        self.progress_bar.grid_remove()

        self.actualizar_preview_cola()

    # ------------------------------------------------------------------
    # UTILIDADES GENERALES
    # ------------------------------------------------------------------
    def pegar_del_portapapeles(self):
        try:
            contenido = self.clipboard_get()
            if contenido:
                self.entry_url.delete(0, tk.END)
                self.entry_url.insert(0, contenido.strip())
                self.validar_y_analizar()
        except Exception:
            pass

    def imprimir_en_tabla(self, texto, limpiar=True, color_error=False):
        self.txt_resultados.configure(state="normal")
        self.txt_resultados.configure(
            text_color="#EF4444" if color_error else "#10B981"
        )
        if limpiar:
            self.txt_resultados.delete("1.0", ctk.END)
        self.txt_resultados.insert(ctk.END, texto)
        self.txt_resultados.configure(state="disabled")

    def detectar_cambio_input(self):
        if not self.entry_url.get().strip():
            self.limpiar_interfaz()

    def limpiar_interfaz(self):
        for var in self.meta_vars.values():
            var.set("-")
        self.lbl_preview_img.configure(text="A la espera de telemetría...", image=None)
        self.url_miniatura = ""
        self.url_limpia = ""
        self.id_video_actual = ""
        self.titulo_video_actual = ""
        self.canal_video_actual = ""
        self.fecha_video_actual = ""
        self.duracion_segundos = 0
        self.duracion_string_actual = ""
        self.stream_directo_piped = ""
        self.descripcion_piped = ""
        self.es_playlist = False
        self.resoluciones_detectadas = []
        self.origen_actual = ""
        self.download_progress.set(0)
        self.lbl_peso_playlist.configure(text="📦 Peso total estimado: -")
        self.actualizar_badge_origen("-")
        self.actualizar_lista_calidades()
        self.update_status_descarga(
            "Configure los parámetros y pulse el ejecutor térmico.", "#A1A1AA"
        )
        self.imprimir_en_tabla("Consola lista para volcado de flujos...")

    def extraer_id_youtube(self, url):
        match = re.search(
            r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/|e\/|watch\?v%3D)([^#\&\?]{11})",
            url,
        )
        return match.group(1) if match else None

    def saneamiento_titulo_archivo(self, titulo):
        return sanear_nombre_archivo(titulo)

    def registrar_hilo(self, t):
        with self.lock_hilos:
            self.hilos_activos.append(t)

    def limpiar_hilo_terminado(self, hilo):
        with self.lock_hilos:
            if hilo in self.hilos_activos:
                self.hilos_activos.remove(hilo)

    def formatear_tamano_bytes(self, tamano_bytes):
        """Convierte bytes a una cadena legible en MB/GB para la columna de 'peso'."""
        return formatear_tamano(tamano_bytes)

    # ------------------------------------------------------------------
    # NUEVO v8.1: PREFERENCIAS (idioma / tema) Y CHEQUEO DE ACTUALIZACIÓN
    # ------------------------------------------------------------------
    def aplicar_idioma(self):
        """Traduce los elementos principales de la interfaz. Es una i18n
        parcial: cubre botones y encabezados clave; los mensajes de estado
        dinámicos (durante análisis/descarga) siguen en español."""
        t = TRADUCCIONES[self.idioma]
        self.entry_url.configure(placeholder_text=t["placeholder_url"])
        self.btn_pegar.configure(text=t["pegar"])
        self.btn_buscar.configure(text=t["analizar"])
        self.download_btn.configure(text=t["descargar"])
        self.cancel_btn.configure(text=t["cancelar"])
        self.btn_abrir_carpeta.configure(text=t["abrir"])
        self.btn_historial.configure(text=t["historial"])
        self.btn_cola_iniciar.configure(
            text=f"{t['descargar_cola']} ({len(self.cola_urls)})"
        )
        self.lbl_titulo_ruta.configure(text=t["boveda"])
        if self.format_option.get() == "Solo Audio (MP3)":
            self.res_label.configure(text=t["bitrate"])
        else:
            self.res_label.configure(text=t["calidad"])

    def alternar_idioma(self):
        self.idioma = "en" if self.idioma == "es" else "es"
        self.aplicar_idioma()

    def alternar_tema(self):
        actual = ctk.get_appearance_mode()
        nuevo = "Light" if actual == "Dark" else "Dark"
        ctk.set_appearance_mode(nuevo)

    def verificar_actualizacion_ytdlp(self, manual=False):
        """Comprueba en segundo plano si hay una versión más nueva de yt-dlp
        publicada en GitHub. No bloquea la app si falla (ej. sin internet);
        solo informa por el status bar."""

        def _check():
            try:
                actual = yt_dlp.version.__version__
                res = self.http_session.get(
                    "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                    timeout=5,
                )
                if res.status_code == 200:
                    ultima = (res.json().get("tag_name") or "").lstrip("v")
                    if ultima and ultima != actual:
                        self.after(
                            0,
                            lambda: self.update_status_descarga(
                                f"🔔 Nueva versión de yt-dlp disponible: {ultima} (tienes {actual}). Ejecuta: pip install -U yt-dlp",
                                "#F59E0B",
                            ),
                        )
                    elif manual:
                        self.after(
                            0,
                            lambda: self.update_status_descarga(
                                f"✅ yt-dlp está actualizado (v{actual}).", "#10B981"
                            ),
                        )
                elif manual:
                    self.after(
                        0,
                        lambda: self.update_status_descarga(
                            "⚠️ No se pudo consultar la última versión de yt-dlp.",
                            "#F59E0B",
                        ),
                    )
            except Exception:
                if manual:
                    self.after(
                        0,
                        lambda: self.update_status_descarga(
                            "⚠️ No se pudo verificar la versión de yt-dlp (¿sin conexión?).",
                            "#F59E0B",
                        ),
                    )

        threading.Thread(target=_check, daemon=True).start()

    # ------------------------------------------------------------------
    # NUEVO v8.1: INTEGRIDAD DE ARCHIVO Y TRANSCRIPCIÓN
    # ------------------------------------------------------------------
    def verificar_integridad_archivo(self, info):
        """Chequeo laxo de integridad: compara el tamaño final en disco
        contra el tamaño esperado reportado por yt-dlp. El post-proceso
        (fusión de streams, conversión a mp3, incrustar miniatura) cambia el
        tamaño final, así que se usa un margen amplio (50%) solo para
        detectar descargas claramente truncadas o fallidas a medias."""
        try:
            for rd in info.get("requested_downloads", []) or []:
                ruta = rd.get("filepath")
                esperado = rd.get("filesize") or rd.get("filesize_approx")
                if ruta and esperado and os.path.exists(ruta):
                    real = os.path.getsize(ruta)
                    if real < esperado * 0.5:
                        return False
            return True
        except Exception:
            return True

    def obtener_ruta_archivo_descargado(self, info):
        try:
            rd = info.get("requested_downloads")
            if rd:
                return rd[0].get("filepath")
        except Exception:
            pass
        return None

    def transcribir_audio_whisper(self, ruta_archivo, modelo="base"):
        return transcribir_audio(ruta_archivo, modelo)

    def procesar_transcripcion_y_limpieza(self, ruta_carpeta, info):
        """Si el usuario activó transcripción (o 'solo transcripción'),
        transcribe el archivo recién descargado. En modo 'solo transcripción'
        borra el archivo pesado al terminar, dejando solo la nota .md."""
        transcripcion = None
        if self.transcribir_var.get() or self.solo_transcripcion_var.get():
            ruta_archivo = self.obtener_ruta_archivo_descargado(info)
            if ruta_archivo and os.path.exists(ruta_archivo):
                modelo = self.modelo_whisper_option.get()
                self.after(
                    0,
                    lambda: self.update_status_descarga(
                        "🎙️ Transcribiendo con Whisper (puede tardar unos minutos)...",
                        "#60A5FA",
                    ),
                )
                transcripcion = self.transcribir_audio_whisper(ruta_archivo, modelo)
                if transcripcion is None:
                    transcripcion = "*(No se pudo generar la transcripción: instala `faster-whisper` u `openai-whisper`.)*"
                if self.solo_transcripcion_var.get():
                    try:
                        os.remove(ruta_archivo)
                    except Exception:
                        pass
        return transcripcion

    def parsear_tiempo_a_segundos(self, texto):
        """NUEVO: convierte 'mm:ss', 'hh:mm:ss' o segundos planos a un entero de segundos."""
        texto = (texto or "").strip()
        if not texto:
            return None
        if ":" in texto:
            partes = texto.split(":")
            try:
                partes = [int(p) for p in partes]
            except ValueError:
                return None
            segundos = 0
            for p in partes:
                segundos = segundos * 60 + p
            return segundos
        try:
            return int(float(texto))
        except ValueError:
            return None

    def verificar_espacio_disco(self, ruta, minimo_mb=200):
        """NUEVO: valida que haya espacio libre suficiente antes de iniciar una descarga."""
        try:
            _, _, libre = shutil.disk_usage(ruta)
            libre_mb = libre / (1024 * 1024)
            return libre_mb >= minimo_mb, libre_mb
        except Exception:
            return True, None  # si no se puede verificar, no se bloquea la descarga

    def interpretar_error_ytdlp(self, excepcion):
        """NUEVO: traduce errores comunes de yt-dlp a mensajes claros en español."""
        msg = str(excepcion)
        reglas = [
            ("private video", "🔒 Este video es privado y no se puede descargar."),
            (
                "sign in to confirm your age",
                "🔞 El video tiene restricción de edad y requiere inicio de sesión.",
            ),
            (
                "not available in your country",
                "🌍 El video está bloqueado en tu región.",
            ),
            ("members-only", "⭐ Este video es exclusivo para miembros del canal."),
            (
                "video unavailable",
                "🚫 El video no está disponible (pudo haber sido eliminado).",
            ),
            ("this live event", "🔴 Es una transmisión en vivo que aún no finaliza."),
            (
                "copyright",
                "©️ El video fue bloqueado por una reclamación de derechos de autor.",
            ),
        ]
        msg_lower = msg.lower()
        for clave, amigable in reglas:
            if clave in msg_lower:
                return amigable
        return f"Error: {msg[:90]}"

    def abrir_carpeta(self, ruta):
        """NUEVO: abre la carpeta de destino en el explorador de archivos del sistema."""
        if not ruta or not os.path.isdir(ruta):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(ruta)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", ruta])
            else:
                subprocess.Popen(["xdg-open", ruta])
        except Exception as e:
            print(f"No se pudo abrir la carpeta: {e}", file=sys.stderr)

    def abrir_ultima_carpeta(self):
        self.abrir_carpeta(self.ultima_ruta_descarga)

    # ------------------------------------------------------------------
    # HISTORIAL
    # ------------------------------------------------------------------
    def cargar_historial(self):
        try:
            if os.path.exists(self.RUTA_HISTORIAL):
                with open(self.RUTA_HISTORIAL, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def guardar_historial(self):
        try:
            with open(self.RUTA_HISTORIAL, "w", encoding="utf-8") as f:
                json.dump(self.historial_descargas, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"No se pudo guardar el historial: {e}", file=sys.stderr)

    def limpiar_historial(self, ventana=None):
        """NUEVO: borra por completo el historial de descargas persistente."""
        self.historial_descargas = []
        self.guardar_historial()
        if ventana is not None:
            ventana.destroy()
        self.update_status_descarga("🗑️ Historial de descargas eliminado.", "#F59E0B")

    def agregar_al_historial(self, titulo, ruta, tipo="video"):
        entrada = {
            "titulo": titulo,
            "ruta": ruta,
            "tipo": tipo,
            "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        self.historial_descargas.append(entrada)
        self.historial_descargas = self.historial_descargas[-200:]
        self.guardar_historial()

    def mostrar_historial(self):
        ventana = ctk.CTkToplevel(self)
        ventana.title("Historial de Descargas")
        ventana.geometry("580x480")
        ventana.transient(self)

        ctk.CTkButton(
            ventana,
            text="🗑️ Limpiar historial",
            fg_color="#DC2626",
            hover_color="#B91C1C",
            command=lambda: self.limpiar_historial(ventana),
        ).pack(fill="x", padx=10, pady=(10, 0))

        marco = ctk.CTkScrollableFrame(ventana, fg_color="#18181A")
        marco.pack(fill="both", expand=True, padx=10, pady=10)

        if not self.historial_descargas:
            ctk.CTkLabel(
                marco, text="Aún no hay descargas registradas.", text_color="#71717A"
            ).pack(pady=20)
            return

        for item in reversed(self.historial_descargas):
            fila = ctk.CTkFrame(marco, fg_color="#09090B", corner_radius=8)
            fila.pack(fill="x", pady=4, padx=4)
            icono = "📋" if item.get("tipo") == "playlist" else "🎬"
            texto = f"{icono} {item.get('titulo', '?')}\n{item.get('fecha', '')}"
            ctk.CTkLabel(
                fila, text=texto, justify="left", anchor="w", font=("Helvetica", 11)
            ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
            ruta_item = item.get("ruta", "")
            ctk.CTkButton(
                fila,
                text="📂",
                width=36,
                command=lambda r=ruta_item: self.abrir_carpeta(r),
            ).pack(side="right", padx=8, pady=8)

    # ------------------------------------------------------------------
    # REGISTRO DE DUPLICADOS (por carpeta)
    # ------------------------------------------------------------------
    def cargar_registro(self, carpeta):
        ruta_reg = os.path.join(carpeta, self.REGISTRO_NOMBRE)
        try:
            if os.path.exists(ruta_reg):
                with open(ruta_reg, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def guardar_registro(self, carpeta, registro):
        ruta_reg = os.path.join(carpeta, self.REGISTRO_NOMBRE)
        try:
            with open(ruta_reg, "w", encoding="utf-8") as f:
                json.dump(registro, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"No se pudo guardar el registro de descargas: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # ANÁLISIS DE VIDEO INDIVIDUAL
    # ------------------------------------------------------------------
    def validar_y_analizar(self):
        url_cruda = self.entry_url.get().strip()
        self.limpiar_interfaz()

        if not url_cruda:
            self.imprimir_en_tabla("⚠️ Error: Campo de entrada vacío.", color_error=True)
            return

        if "list=" in url_cruda:
            self.es_playlist = True
            self.url_limpia = url_cruda
            self.meta_vars["📌 Título:"].set("Analizando colección...")
            self.btn_buscar.configure(state="disabled", text="Mapeando...")
            self.progress_bar.grid()
            self.progress_bar.start()
            # MEJORA: antes esto solo mostraba un texto estático; ahora se analiza
            # la playlist de verdad para mostrar cantidad de videos y peso estimado.
            t = threading.Thread(
                target=self.analizar_playlist_preliminar, args=(url_cruda,), daemon=True
            )
            self.registrar_hilo(t)
            t.start()
            return

        video_id = self.extraer_id_youtube(url_cruda)
        if not video_id:
            self.imprimir_en_tabla(
                "⚠️ Error: ID multimedia no reconocido.", color_error=True
            )
            return

        self.id_video_actual = video_id
        self.url_limpia = f"https://www.youtube.com/watch?v={video_id}"

        self.btn_buscar.configure(state="disabled", text="Mapeando...")
        self.progress_bar.grid()
        self.progress_bar.start()

        # MEJORA: se invirtió el orden — ahora yt-dlp clásico es el intento
        # principal y Piped queda como respaldo si yt-dlp falla.
        t = threading.Thread(
            target=self.procesar_analisis_legacy, args=(self.url_limpia,), daemon=True
        )
        self.registrar_hilo(t)
        t.start()

    def _peticion_piped_con_reintentos(self, api_url, intentos=2):
        """Reintenta la petición a la API de Piped antes de rendirse. Piped
        es ahora el respaldo (se usa solo si yt-dlp falló primero)."""
        ultimo_error = None
        for i in range(intentos):
            try:
                res = self.http_session.get(api_url, timeout=10)
                if res.status_code == 200:
                    return res
                ultimo_error = RuntimeError(f"HTTP {res.status_code}")
            except Exception as e:
                ultimo_error = e
            if i < intentos - 1:
                time.sleep(1)
        raise (
            ultimo_error if ultimo_error else RuntimeError("Fallo desconocido en Piped")
        )

    def procesar_analisis_piped(self, video_id):
        api_url = f"https://pipedapi.kavin.rocks/streams/{video_id}"
        try:
            res = self._peticion_piped_con_reintentos(api_url)
            info = res.json()

            self.titulo_video_actual = info.get("title", "Video_Sin_Titulo")
            self.canal_video_actual = info.get("uploader", "Canal_Desconocido")
            self.duracion_segundos = info.get("duration") or 0
            self.descripcion_piped = info.get("description", "")
            vistas = info.get("views", 0)
            likes = info.get("likes", 0)

            self.duracion_string_actual = (
                f"{self.duracion_segundos // 60}:{self.duracion_segundos % 60:02d}"
            )
            self.fecha_video_actual = "Indexado Directo (No-VPN)"
            self.url_miniatura = info.get("thumbnailUrl", "")
            self.origen_actual = "Piped"

            # Tabla de resoluciones: se listan TODAS (progresivas y solo-video),
            # ya que YouTube solo entrega streams combinados hasta 360p.
            reporte = " ┌───────────────────────────────────────────────────────────┐\n │ FLUJOS DETECTADOS (PIPED BYPASS)                          │\n ├───────────────────────────────────────────────────────────┤\n"
            hubo_streams = False
            calidades_vistas = set()
            resoluciones_set = set()
            for f in info.get("videoStreams", []):
                calidad = f.get("quality", "N/A")
                if calidad in calidades_vistas:
                    continue
                calidades_vistas.add(calidad)
                hubo_streams = True
                es_progresivo = not f.get("videoOnly")
                if (
                    f.get("format") == "MPEG-4"
                    and es_progresivo
                    and not self.stream_directo_piped
                ):
                    self.stream_directo_piped = f.get("url", "")
                etiqueta_audio = "Video+Audio" if es_progresivo else "Solo Video"
                peso_est = self.formatear_tamano_bytes(f.get("contentLength"))
                reporte += f" │ Res: {calidad:<8} │ {etiqueta_audio:<11} │ FPS: {f.get('fps', 'N/A'):<3} │ Peso: {peso_est:<9} │\n"
                m = re.match(r"(\d+p)", calidad)
                if m:
                    resoluciones_set.add(m.group(1))
            if not hubo_streams:
                reporte += (
                    " │ Sin flujos de video disponibles.                          │\n"
                )
            reporte += (
                " └───────────────────────────────────────────────────────────┘\n"
            )

            self.resoluciones_detectadas = sorted(
                resoluciones_set,
                key=lambda r: int(r.rstrip("p")) if r.rstrip("p").isdigit() else 0,
                reverse=True,
            )

            if self.esta_cerrando:
                return
            self.after(
                0,
                lambda: self.actualizar_ui_metadatos(
                    vistas, likes, self.duracion_string_actual
                ),
            )

            if self.url_miniatura:
                t_thumb = threading.Thread(
                    target=self.descargar_y_renderizar_miniatura, daemon=True
                )
                self.registrar_hilo(t_thumb)
                t_thumb.start()

            self.after(0, lambda: self.finalizar_exito_analisis(reporte))
        except Exception as e:
            # MEJORA: Piped es ahora el ÚLTIMO recurso; si también falla, se
            # informa el error en vez de intentar otro fallback.
            self.after(
                0,
                lambda: self.finalizar_fallo_analisis(
                    f"No se pudo analizar el video (yt-dlp ni Piped funcionaron).\nError: {e}"
                ),
            )
        finally:
            self.limpiar_hilo_terminado(threading.current_thread())

    def ejecutar_fallback_piped(self):
        """NUEVO: se activa cuando yt-dlp (intento principal) falla; usa Piped
        como plan B."""
        if not self.id_video_actual:
            self.finalizar_fallo_analisis("Error: no se pudo analizar el video.")
            return
        t = threading.Thread(
            target=self.procesar_analisis_piped,
            args=(self.id_video_actual,),
            daemon=True,
        )
        self.registrar_hilo(t)
        t.start()

    def procesar_analisis_legacy(self, url):
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "ffmpeg_location": self.ruta_ffmpeg,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                self.titulo_video_actual = info.get("title", "Video_Sin_Titulo")
                self.canal_video_actual = info.get("uploader", "Canal_Desconocido")
                self.duracion_segundos = info.get("duration") or 0
                self.duracion_string_actual = info.get("duration_string", "N/A")
                self.url_miniatura = info.get("thumbnail", "")
                self.origen_actual = "yt-dlp Clásico"

                raw_date = info.get("upload_date", "") or ""
                self.fecha_video_actual = (
                    f"{raw_date[6:8]}/{raw_date[4:6]}/{raw_date[0:4]}"
                    if len(raw_date) == 8
                    else "N/A"
                )

                # Tabla de resoluciones (video-only incluido, no solo progresivos)
                reporte = " ┌───────────────────────────────────────────────────────────┐\n │ FLUJOS DETECTADOS (YT-DLP - HANDSHAKE CLÁSICO)            │\n ├───────────────────────────────────────────────────────────┤\n"
                formatos = info.get("formats", []) or []
                vistos = set()
                resoluciones_set = set()
                hubo_formatos = False

                def _orden(fmt):
                    return (fmt.get("height") or 0, fmt.get("tbr") or 0)

                for fmt in sorted(formatos, key=_orden, reverse=True):
                    altura = fmt.get("height")
                    vcodec = fmt.get("vcodec", "none")
                    if not altura or vcodec == "none":
                        continue
                    if altura in vistos:
                        continue
                    vistos.add(altura)
                    hubo_formatos = True
                    resoluciones_set.add(f"{altura}p")
                    acodec = fmt.get("acodec", "none")
                    etiqueta_audio = "Video+Audio" if acodec != "none" else "Solo Video"
                    tamano = fmt.get("filesize") or fmt.get("filesize_approx")
                    peso_est = self.formatear_tamano_bytes(tamano)
                    reporte += f" │ Res: {str(altura) + 'p':<8} │ {etiqueta_audio:<11} │ FPS: {str(fmt.get('fps', 'N/A')):<3} │ Peso: {peso_est:<9} │\n"
                if not hubo_formatos:
                    reporte += " │ Sin formatos de video disponibles.                        │\n"
                reporte += (
                    " └───────────────────────────────────────────────────────────┘\n"
                )

                self.resoluciones_detectadas = sorted(
                    resoluciones_set, key=lambda r: int(r.rstrip("p")), reverse=True
                )

                if not self.esta_cerrando:
                    self.after(
                        0,
                        lambda: self.actualizar_ui_metadatos(
                            info.get("view_count"),
                            info.get("like_count"),
                            self.duracion_string_actual,
                        ),
                    )

                    if self.url_miniatura:
                        t_thumb = threading.Thread(
                            target=self.descargar_y_renderizar_miniatura, daemon=True
                        )
                        self.registrar_hilo(t_thumb)
                        t_thumb.start()

                    self.after(0, lambda r=reporte: self.finalizar_exito_analisis(r))
        except Exception:
            # MEJORA: yt-dlp es ahora el intento PRINCIPAL; si falla, se cae a
            # Piped como respaldo (antes era al revés).
            self.after(0, lambda: self.ejecutar_fallback_piped())
        finally:
            self.limpiar_hilo_terminado(threading.current_thread())

    def descargar_y_renderizar_miniatura(self):
        """MEJORA: reintenta hasta 2 veces antes de rendirse."""
        url = self.url_miniatura
        img_data = None
        intentos = 2
        for i in range(intentos):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as res:
                    img_data = res.read()
                break
            except Exception:
                if i < intentos - 1:
                    time.sleep(1)
        if img_data and not self.esta_cerrando:
            self.after(0, lambda: self.renderizar_miniatura_en_main(img_data))
        self.limpiar_hilo_terminado(threading.current_thread())

    def renderizar_miniatura_en_main(self, img_data):
        try:
            img_pil = Image.open(io.BytesIO(img_data))
            img_pil = img_pil.convert("RGB")
            img_res = img_pil.resize((320, 180), Image.Resampling.LANCZOS)
            img_ctk = ctk.CTkImage(
                light_image=img_res, dark_image=img_res, size=(320, 180)
            )
            self.lbl_preview_img.configure(text="", image=img_ctk)
            self.lbl_preview_img.image = img_ctk
        except Exception:
            self.lbl_preview_img.configure(text="Error al cargar miniatura")

    def actualizar_ui_metadatos(self, vistas, likes, duracion_str):
        self.meta_vars["📌 Título:"].set(self.titulo_video_actual)
        self.meta_vars["👤 Canal:"].set(self.canal_video_actual)
        self.meta_vars["⏱️ Duración:"].set(duracion_str)
        self.meta_vars["👁️ Vistas:"].set(f"{vistas:,}" if vistas else "N/A")
        self.meta_vars["👍 Likes:"].set(f"{likes:,}" if likes else "N/A")
        self.meta_vars["📅 Fecha:"].set(self.fecha_video_actual)

    def actualizar_badge_origen(self, origen):
        if origen == "Piped":
            self.lbl_origen_badge.configure(
                text="🟢 Origen: Piped (rápido)", text_color="#22C55E"
            )
        elif origen == "yt-dlp Clásico":
            self.lbl_origen_badge.configure(
                text="🟠 Origen: yt-dlp Clásico (respaldo)", text_color="#F59E0B"
            )
        else:
            self.lbl_origen_badge.configure(text="⚪ Origen: -", text_color="#71717A")

    def actualizar_lista_calidades(self):
        """NUEVO: la lista de calidades ahora refleja las resoluciones reales
        detectadas en el análisis, en vez de un listado fijo genérico."""
        if self.format_option.get() == "Solo Audio (MP3)":
            return
        if self.resoluciones_detectadas:
            valores = ["Máxima Calidad"] + self.resoluciones_detectadas
        else:
            valores = ["Máxima Calidad", "1080p", "720p", "480p"]
        actual = self.res_option.get()
        self.res_option.configure(values=valores)
        self.res_option.set(actual if actual in valores else "Máxima Calidad")

    def finalizar_exito_analisis(self, reporte):
        self.imprimir_en_tabla(reporte)
        self.actualizar_lista_calidades()
        self.actualizar_badge_origen(self.origen_actual)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.btn_buscar.configure(state="normal", text="Analizar Origen")
        self.update_status_descarga("Estructura de flujos verificado.", "#10B981")

    def finalizar_fallo_analisis(self, mensaje):
        self.limpiar_interfaz()
        self.imprimir_en_tabla(mensaje, color_error=True)
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.btn_buscar.configure(state="normal", text="Analizar Origen")

    # ------------------------------------------------------------------
    # ANÁLISIS PRELIMINAR DE PLAYLIST (NUEVO)
    # ------------------------------------------------------------------
    def analizar_playlist_preliminar(self, url):
        try:
            ydl_opts_flat = {"quiet": True, "extract_flat": True}
            with yt_dlp.YoutubeDL(ydl_opts_flat) as ydl:
                info = ydl.extract_info(url, download=False)

            entries = [e for e in info.get("entries", []) if e]
            total = len(entries)
            titulo_pl = info.get("title", "Playlist")
            self.origen_actual = "yt-dlp Clásico"

            # Estimación de peso: se analiza una muestra pequeña (hasta 3 videos)
            # con la calidad real de video seleccionada, y se extrapola al total.
            muestra = entries[:3]
            tamanos_muestra = []
            ydl_opts_full = {
                "quiet": True,
                "skip_download": True,
                "ffmpeg_location": self.ruta_ffmpeg,
                "http_headers": {"User-Agent": "Mozilla/5.0"},
            }
            for e in muestra:
                try:
                    v_url = e.get("url")
                    if not v_url:
                        continue
                    with yt_dlp.YoutubeDL(ydl_opts_full) as ydl2:
                        v_info = ydl2.extract_info(v_url, download=False)
                    formatos = v_info.get("formats", []) or []
                    candidatos = [
                        f.get("filesize") or f.get("filesize_approx")
                        for f in formatos
                        if (f.get("filesize") or f.get("filesize_approx"))
                    ]
                    if candidatos:
                        tamanos_muestra.append(max(candidatos))
                except Exception:
                    continue

            if tamanos_muestra and total:
                promedio = sum(tamanos_muestra) / len(tamanos_muestra)
                texto_peso = f"{self.formatear_tamano_bytes(promedio * total)} (aprox., muestra de {len(tamanos_muestra)} videos)"
            else:
                texto_peso = "No calculable"

            if not self.esta_cerrando:
                self.after(
                    0,
                    lambda: self.finalizar_analisis_playlist(
                        titulo_pl, total, texto_peso
                    ),
                )
        except Exception as e:
            if not self.esta_cerrando:
                self.after(
                    0,
                    lambda: self.finalizar_fallo_analisis(
                        f"Error analizando playlist:\n{e}"
                    ),
                )
        finally:
            self.limpiar_hilo_terminado(threading.current_thread())

    def finalizar_analisis_playlist(self, titulo, total, texto_peso):
        self.meta_vars["📌 Título:"].set(titulo)
        self.meta_vars["👤 Canal:"].set(f"{total} videos en la lista")
        self.lbl_peso_playlist.configure(text=f"📦 Peso total estimado: {texto_peso}")
        self.actualizar_badge_origen(self.origen_actual)
        self.imprimir_en_tabla(
            f"📋 Playlist analizada: {total} videos encontrados.\nEl peso es una estimación basada en una muestra; el real puede variar según la calidad elegida."
        )
        self.progress_bar.stop()
        self.progress_bar.grid_remove()
        self.btn_buscar.configure(state="normal", text="Analizar Origen")
        self.update_status_descarga("Lista de reproducción analizada.", "#10B981")

    # ------------------------------------------------------------------
    # DESCARGA
    # ------------------------------------------------------------------
    def examinar_carpeta(self):
        folder = filedialog.askdirectory()
        if folder:
            self.download_path.set(folder)

    def gestionar_cambio_formato(self, choice):
        if choice == "Solo Audio (MP3)":
            self.res_label.configure(text="Bitrate:")
            self.res_option.configure(values=["320 kbps (Alta)", "192 kbps (Estándar)"])
            self.res_option.set("192 kbps (Estándar)")
        else:
            self.res_label.configure(text="Calidad:")
            self.actualizar_lista_calidades()

    def update_status_descarga(self, text, color):
        self.status_label.configure(text=text, text_color=color)

    def hook_progreso_descarga(self, d):
        # NUEVO: soporte de cancelación desde el hook de progreso de yt-dlp
        if self.evento_cancelar.is_set():
            raise DownloadCancelled("Cancelado por el usuario.")

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            porcentaje = (downloaded / total) if total > 0 else 0

            velocidad = d.get("_speed_str", "0B/s")
            eta = d.get("_eta_str", "00:00")

            txt = f"Descargando: {int(porcentaje * 100)}% | {downloaded / (1024 * 1024):.1f} MB | Vel: {velocidad} | ETA: {eta}"
            self.after(0, lambda: self.actualizar_ui_barra(porcentaje, txt, "#3B8ED0"))
        elif d["status"] == "finished":
            self.after(
                0,
                lambda: self.actualizar_ui_barra(
                    0.95, "Fusing streams & indexando metadatos Obsidian...", "#F59E0B"
                ),
            )

    def actualizar_ui_barra(self, valor, texto, color):
        if not self.esta_cerrando:
            self.download_progress.set(valor)
            self.status_label.configure(text=texto, text_color=color)

    def iniciar_hilo_descarga(self):
        if not self.url_limpia:
            self.update_status_descarga("⚠️ Error: Cache de origen vacía.", "#EF4444")
            return
        self.evento_cancelar.clear()
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        t = threading.Thread(target=self.ejecutar_descarga_master, daemon=True)
        self.registrar_hilo(t)
        t.start()

    def cancelar_descarga_actual(self):
        """NUEVO: solicita la cancelación de la descarga/lote/cola en curso."""
        self.evento_cancelar.set()
        self.update_status_descarga(
            "🛑 Cancelando... esperando a que finalice el bloque actual.", "#F59E0B"
        )
        self.cancel_btn.configure(state="disabled")

    def ejecutar_descarga_master(self):
        ruta_base = self.download_path.get()
        if not os.access(ruta_base, os.W_OK):
            self.after(
                0,
                lambda: self.finalizar_interfaz_descarga(
                    "Error: Sin permisos de escritura.", "#EF4444"
                ),
            )
            return

        ok_espacio, libre_mb = self.verificar_espacio_disco(ruta_base)
        if not ok_espacio:
            self.after(
                0,
                lambda: self.finalizar_interfaz_descarga(
                    f"⚠️ Espacio insuficiente en disco ({libre_mb:.0f} MB libres, mínimo 200 MB).",
                    "#EF4444",
                ),
            )
            return

        if self.es_playlist:
            self.procesar_playlist_lote(ruta_base)
        else:
            self.procesar_video_individual(ruta_base)

    def procesar_video_individual(self, ruta_destino):
        # NUEVO: comprobación de duplicados antes de descargar
        if self.omitir_duplicados_var.get() and self.id_video_actual:
            registro = self.cargar_registro(ruta_destino)
            if self.id_video_actual in registro:
                self.after(
                    0,
                    lambda: self.finalizar_interfaz_descarga(
                        f"⏭️ Omitido: '{self.titulo_video_actual}' ya se descargó antes en esta carpeta.",
                        "#F59E0B",
                    ),
                )
                self.limpiar_hilo_terminado(threading.current_thread())
                return

        # FIX v8.1: en modo 'solo transcripción' se necesita respetar el
        # formato 'bestaudio' liviano; el enlace directo de Piped es un
        # archivo fijo (progresivo) que ignoraría esa selección de formato.
        if self.solo_transcripcion_var.get():
            url = self.url_limpia
        else:
            url = (
                self.stream_directo_piped
                if self.stream_directo_piped
                else self.url_limpia
            )
        ydl_opts = self.construir_opciones_ytdlp(ruta_destino)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                capitulos = info.get("chapters", [])
                desc = info.get("description", "")

            integridad_ok = self.verificar_integridad_archivo(info)
            transcripcion = self.procesar_transcripcion_y_limpieza(ruta_destino, info)

            if self.omitir_duplicados_var.get() and self.id_video_actual:
                registro = self.cargar_registro(ruta_destino)
                registro[self.id_video_actual] = {
                    "titulo": self.titulo_video_actual,
                    "fecha": self.fecha_video_actual,
                }
                self.guardar_registro(ruta_destino, registro)

            self.after(
                0,
                lambda: self.finalizar_flujo_individual(
                    ruta_destino, capitulos, desc, transcripcion, integridad_ok
                ),
            )
        except DownloadCancelled:
            self.after(
                0,
                lambda: self.finalizar_interfaz_descarga(
                    "🛑 Descarga cancelada por el usuario.", "#F59E0B"
                ),
            )
        except DownloadError as e:
            mensaje = self.interpretar_error_ytdlp(e)
            self.after(
                0, lambda m=mensaje: self.finalizar_interfaz_descarga(m, "#EF4444")
            )
        except Exception as e:
            self.after(
                0,
                lambda: self.finalizar_interfaz_descarga(
                    f"Fallo multimedia: {str(e)[:60]}", "#EF4444"
                ),
            )
        finally:
            self.limpiar_hilo_terminado(threading.current_thread())

    def finalizar_flujo_individual(
        self, ruta, capitulos, desc, transcripcion=None, integridad_ok=True
    ):
        if self.generar_markdown_var.get():
            self.corregir_a_markdown(
                ruta,
                self.titulo_video_actual,
                self.id_video_actual,
                self.canal_video_actual,
                self.fecha_video_actual,
                self.duracion_string_actual,
                self.duracion_segundos,
                self.url_limpia,
                capitulos,
                desc,
                transcripcion,
            )
        self.ultima_ruta_descarga = ruta
        self.agregar_al_historial(self.titulo_video_actual, ruta, tipo="video")
        if integridad_ok:
            self.finalizar_interfaz_descarga(
                "Sincronización de recurso completada con éxito.", "#10B981"
            )
        else:
            self.finalizar_interfaz_descarga(
                "⚠️ Descarga completada pero el archivo parece incompleto (revisa tu conexión).",
                "#F59E0B",
            )

    def procesar_playlist_lote(self, ruta_base):
        ydl_opts_meta = {"quiet": True, "extract_flat": True}
        url_fija_playlist = self.url_limpia
        try:
            with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                playlist_info = ydl.extract_info(url_fija_playlist, download=False)

            titulo_pl = self.saneamiento_titulo_archivo(
                playlist_info.get("title", "Playlist_Set")
            )
            carpeta_pl = os.path.join(ruta_base, titulo_pl)
            os.makedirs(carpeta_pl, exist_ok=True)

            entries = playlist_info.get("entries", [])
            total_videos = len(entries)

            moc_path = os.path.join(carpeta_pl, "_Indice_MOC.md")
            with open(moc_path, "w", encoding="utf-8") as f_moc:
                f_moc.write(f"""---
type: MOC
playlist_url: "{url_fija_playlist}"
tags: [recurso/playlist, moc]
---

# Índice Maestro: {playlist_info.get("title", "Sin Título")}

## 🗂️ Recursos Vinculados
""")

            ydl_opts_descarga = self.construir_opciones_ytdlp(carpeta_pl)
            omitir_duplicados = self.omitir_duplicados_var.get()

            for idx, entry in enumerate(entries):
                # NUEVO: soporte de cancelación también dentro de lotes de playlist
                if self.esta_cerrando or self.evento_cancelar.is_set():
                    break
                if not entry:
                    continue
                v_url = entry.get("url")
                if not v_url:
                    continue

                v_id_flat = entry.get("id", "")
                if omitir_duplicados and v_id_flat:
                    registro = self.cargar_registro(carpeta_pl)
                    if v_id_flat in registro:
                        with open(moc_path, "a", encoding="utf-8") as f_moc:
                            f_moc.write(
                                f"- ⏭️ (Omitido, ya descargado antes) {v_id_flat}\n"
                            )
                        continue

                self.after(
                    0,
                    lambda i=idx: self.update_status_descarga(
                        f"Lote: {i + 1}/{total_videos} ➔ Sincronizando...", "#60A5FA"
                    ),
                )

                try:
                    with yt_dlp.YoutubeDL(ydl_opts_descarga) as ydl:
                        v_info = ydl.extract_info(v_url, download=True)
                        if not v_info:
                            continue
                        v_tit = v_info.get("title", "Video")
                        v_id = v_info.get("id", "")
                        v_can = v_info.get("uploader", "Desconocido")
                        v_dur_str = v_info.get("duration_string", "N/A")
                        v_dur_sec = v_info.get("duration") or 0
                        v_desc = v_info.get("description", "")
                        raw_date = v_info.get("upload_date", "") or ""
                        v_fec = (
                            f"{raw_date[6:8]}/{raw_date[4:6]}/{raw_date[0:4]}"
                            if len(raw_date) == 8
                            else "N/A"
                        )
                        v_caps = v_info.get("chapters", [])

                    integridad_ok_v = self.verificar_integridad_archivo(v_info)
                    transcripcion_v = self.procesar_transcripcion_y_limpieza(
                        carpeta_pl, v_info
                    )

                    file_saneado = self.saneamiento_titulo_archivo(v_tit)
                    if self.generar_markdown_var.get():
                        self.corregir_a_markdown(
                            carpeta_pl,
                            v_tit,
                            v_id,
                            v_can,
                            v_fec,
                            v_dur_str,
                            v_dur_sec,
                            f"https://www.youtube.com/watch?v={v_id}",
                            v_caps,
                            v_desc,
                            transcripcion_v,
                        )

                    if omitir_duplicados and v_id:
                        registro = self.cargar_registro(carpeta_pl)
                        registro[v_id] = {"titulo": v_tit, "fecha": v_fec}
                        self.guardar_registro(carpeta_pl, registro)

                    with open(moc_path, "a", encoding="utf-8") as f_moc:
                        if integridad_ok_v:
                            f_moc.write(
                                f"- [[{file_saneado}]] | *{v_dur_str}* - {v_can}\n"
                            )
                        else:
                            f_moc.write(
                                f"- [[{file_saneado}]] | *{v_dur_str}* - {v_can} ⚠️ (posible descarga incompleta)\n"
                            )
                except DownloadCancelled:
                    break
                except DownloadError as e:
                    mensaje = self.interpretar_error_ytdlp(e)
                    print(f"Error en playlist idx {idx}: {mensaje}", file=sys.stderr)
                    with open(moc_path, "a", encoding="utf-8") as f_moc:
                        f_moc.write(f"- ❌ Error al descargar: {mensaje}\n")
                    continue
                except Exception as e:
                    print(
                        f"Error omitido en elemento de playlist index {idx}: {e}",
                        file=sys.stderr,
                    )
                    continue

            self.ultima_ruta_descarga = carpeta_pl
            self.agregar_al_historial(
                playlist_info.get("title", "Playlist"), carpeta_pl, tipo="playlist"
            )

            if self.evento_cancelar.is_set():
                self.after(
                    0,
                    lambda: self.finalizar_interfaz_descarga(
                        "🛑 Descarga de playlist cancelada por el usuario.", "#F59E0B"
                    ),
                )
            else:
                self.after(
                    0,
                    lambda: self.finalizar_interfaz_descarga(
                        "Playlist y MOC estructural creados con éxito.", "#10B981"
                    ),
                )
        except Exception as e:
            self.after(
                0,
                lambda: self.finalizar_interfaz_descarga(
                    f"Fallo en Playlist: {str(e)[:50]}", "#EF4444"
                ),
            )
        finally:
            self.limpiar_hilo_terminado(threading.current_thread())

    def obtener_formato_video_segun_calidad(self):
        """Traduce la calidad elegida (dinámica, según lo detectado en el análisis)
        a un string de formato real para yt-dlp."""
        calidad = self.res_option.get()
        if calidad == "Máxima Calidad":
            return "bestvideo+bestaudio/best"
        m = re.match(r"(\d+)", calidad)
        if m:
            altura = m.group(1)
            return f"bestvideo[height<={altura}]+bestaudio/best[height<={altura}]"
        return "bestvideo+bestaudio/best"

    def obtener_bitrate_audio_seleccionado(self):
        calidad = self.res_option.get()
        return "320" if "320" in calidad else "192"

    def construir_opciones_ytdlp(self, ruta):
        ydl_opts = {
            "outtmpl": os.path.join(ruta, "%(title).120s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "retries": 5,
            "ffmpeg_location": self.ruta_ffmpeg,
            "postprocessors": [],
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }

        # NUEVO v8.1: modo 'solo transcripción' -- solo se necesita el audio
        # (liviano) para transcribir; se ignoran formato/calidad/miniatura,
        # ya que el archivo se borrará después de transcribir.
        if self.solo_transcripcion_var.get():
            ydl_opts["format"] = "bestaudio/best"
        elif self.format_option.get() == "Solo Audio (MP3)":
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": self.obtener_bitrate_audio_seleccionado(),
                }
            )
        else:
            ydl_opts["format"] = self.obtener_formato_video_segun_calidad()
            ydl_opts["merge_output_format"] = "mp4"

        if not self.solo_transcripcion_var.get():
            if self.thumb_var.get():
                ydl_opts["writethumbnail"] = True
                ydl_opts["postprocessors"].append(
                    {"key": "EmbedThumbnail", "already_have_thumbnail": False}
                )
            if self.meta_var.get():
                ydl_opts["postprocessors"].append({"key": "FFmpegMetadata"})
            if self.subs_var.get():
                ydl_opts.update(
                    {"writesubtitles": True, "subtitleslangs": ["es", "en"]}
                )

        # NUEVO: recorte de segmento (descarga solo el rango de tiempo indicado;
        # también aplica en modo 'solo transcripción' para ahorrar tiempo)
        if self.recorte_var.get():
            ini = self.parsear_tiempo_a_segundos(self.entry_recorte_inicio.get())
            fin = self.parsear_tiempo_a_segundos(self.entry_recorte_fin.get())
            if ini is not None and fin is not None and fin > ini:
                ydl_opts["download_ranges"] = download_range_func(None, [(ini, fin)])
                ydl_opts["force_keyframes_at_cuts"] = True

        ydl_opts["progress_hooks"] = [self.hook_progreso_descarga]
        return ydl_opts

    def corregir_a_markdown(
        self,
        directorio,
        titulo,
        video_id,
        canal,
        fecha,
        duracion_str,
        duracion_sec,
        url_origen,
        capitulos,
        descripcion_cruda,
        transcripcion=None,
    ):
        escribir_nota_markdown(
            directorio,
            titulo,
            video_id,
            canal,
            fecha,
            duracion_str,
            duracion_sec,
            url_origen,
            capitulos,
            descripcion_cruda,
            transcripcion,
        )

    def finalizar_interfaz_descarga(self, texto, color):
        self.status_label.configure(text=texto, text_color=color)
        self.download_progress.set(1.0 if color == "#10B981" else 0)
        self.download_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if color == "#10B981" and self.ultima_ruta_descarga:
            self.btn_abrir_carpeta.configure(state="normal")

    # ------------------------------------------------------------------
    # COLA DE DESCARGAS MÚLTIPLES (NUEVO)
    # ------------------------------------------------------------------
    def agregar_a_cola(self):
        contenido = self.txt_cola_input.get("1.0", "end").strip()
        if not contenido:
            return
        lineas = [l.strip() for l in contenido.splitlines() if l.strip()]
        agregadas = 0
        for linea in lineas:
            if (
                "youtube.com" in linea or "youtu.be" in linea
            ) and linea not in self.cola_urls:
                self.cola_urls.append(linea)
                agregadas += 1
        self.txt_cola_input.delete("1.0", "end")
        self.actualizar_preview_cola()
        self.update_status_descarga(
            f"➕ {agregadas} URL(s) añadida(s) a la cola.", "#60A5FA"
        )

    def vaciar_cola(self):
        self.cola_urls = []
        self.actualizar_preview_cola()

    def actualizar_preview_cola(self):
        self.txt_cola_preview.configure(state="normal")
        self.txt_cola_preview.delete("1.0", "end")
        if self.cola_urls:
            for i, u in enumerate(self.cola_urls, 1):
                self.txt_cola_preview.insert("end", f"{i}. {u}\n")
        else:
            self.txt_cola_preview.insert("end", "(vacía)")
        self.txt_cola_preview.configure(state="disabled")
        self.btn_cola_iniciar.configure(
            text=f"▶ Descargar Cola ({len(self.cola_urls)})"
        )

    def iniciar_cola_descargas(self):
        if not self.cola_urls:
            self.update_status_descarga("⚠️ La cola está vacía.", "#EF4444")
            return
        ruta_base = self.download_path.get()
        if not os.access(ruta_base, os.W_OK):
            self.update_status_descarga(
                "Error: Sin permisos de escritura en la carpeta destino.", "#EF4444"
            )
            return
        ok_espacio, libre_mb = self.verificar_espacio_disco(ruta_base)
        if not ok_espacio:
            self.update_status_descarga(
                f"⚠️ Espacio insuficiente en disco ({libre_mb:.0f} MB libres).",
                "#EF4444",
            )
            return

        self.evento_cancelar.clear()
        self.download_btn.configure(state="disabled")
        self.btn_cola_iniciar.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        t = threading.Thread(
            target=self._procesar_cola_worker, args=(ruta_base,), daemon=True
        )
        self.registrar_hilo(t)
        t.start()

    def _descargar_video_individual_directo(self, url, ruta_base):
        """Descarga un video individual dentro del flujo de cola, usando yt-dlp
        directamente (sin pasar por Piped, para simplificar el procesamiento
        en lote de múltiples URLs distintas)."""
        ydl_opts_meta = {
            "quiet": True,
            "skip_download": True,
            "ffmpeg_location": self.ruta_ffmpeg,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info_previo = ydl.extract_info(url, download=False)
        video_id = info_previo.get("id", "")
        titulo = info_previo.get("title", "Video")

        if self.omitir_duplicados_var.get() and video_id:
            registro = self.cargar_registro(ruta_base)
            if video_id in registro:
                self.after(
                    0,
                    lambda: self.imprimir_en_tabla(
                        f"⏭️ Omitido (ya descargado): {titulo}\n", limpiar=False
                    ),
                )
                return

        ydl_opts = self.construir_opciones_ytdlp(ruta_base)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as e:
            mensaje = self.interpretar_error_ytdlp(e)
            self.after(
                0,
                lambda: self.imprimir_en_tabla(
                    f"❌ {titulo}: {mensaje}\n", limpiar=False
                ),
            )
            return

        capitulos = info.get("chapters", [])
        desc = info.get("description", "")
        canal = info.get("uploader", "Desconocido")
        dur_str = info.get("duration_string", "N/A")
        dur_sec = info.get("duration") or 0
        raw_date = info.get("upload_date", "") or ""
        fecha = (
            f"{raw_date[6:8]}/{raw_date[4:6]}/{raw_date[0:4]}"
            if len(raw_date) == 8
            else "N/A"
        )
        url_final = f"https://www.youtube.com/watch?v={video_id}"

        integridad_ok = self.verificar_integridad_archivo(info)
        transcripcion = self.procesar_transcripcion_y_limpieza(ruta_base, info)

        if self.generar_markdown_var.get():
            self.corregir_a_markdown(
                ruta_base,
                titulo,
                video_id,
                canal,
                fecha,
                dur_str,
                dur_sec,
                url_final,
                capitulos,
                desc,
                transcripcion,
            )
        if not integridad_ok:
            self.after(
                0,
                lambda: self.imprimir_en_tabla(
                    f"⚠️ Posible descarga incompleta: {titulo}\n", limpiar=False
                ),
            )

        if self.omitir_duplicados_var.get() and video_id:
            registro = self.cargar_registro(ruta_base)
            registro[video_id] = {"titulo": titulo, "fecha": fecha}
            self.guardar_registro(ruta_base, registro)

        self.agregar_al_historial(titulo, ruta_base, tipo="video")
        self.ultima_ruta_descarga = ruta_base

    def _procesar_cola_worker(self, ruta_base):
        total = len(self.cola_urls)
        urls_pendientes = list(self.cola_urls)
        exitosos = 0
        idx = 0
        for idx, url in enumerate(urls_pendientes):
            if self.evento_cancelar.is_set():
                break
            self.after(
                0,
                lambda i=idx: self.update_status_descarga(
                    f"Cola: {i + 1}/{total} ➔ procesando...", "#60A5FA"
                ),
            )
            try:
                if "list=" in url:
                    self.url_limpia = url
                    self.procesar_playlist_lote(ruta_base)
                else:
                    self._descargar_video_individual_directo(url, ruta_base)
                # FIX: procesar_playlist_lote absorbe la cancelación internamente
                # (no relanza la excepción), así que sin este chequeo una playlist
                # cancelada a la mitad se contaba como "exitosa" en el resumen final.
                if self.evento_cancelar.is_set():
                    break
                exitosos += 1
            except DownloadCancelled:
                break
            except Exception as e:
                print(f"Error en elemento de cola: {e}", file=sys.stderr)
                continue

        if self.evento_cancelar.is_set():
            self.cola_urls = urls_pendientes[idx:]
        else:
            self.cola_urls = []

        self.after(0, lambda: self.finalizar_cola(exitosos, total))

    def finalizar_cola(self, exitosos, total):
        cancelado = self.evento_cancelar.is_set()
        if cancelado:
            texto = (
                f"🛑 Cola cancelada. {exitosos}/{total} completados antes de cancelar."
            )
            color = "#F59E0B"
        else:
            texto = f"✅ Cola finalizada: {exitosos}/{total} descargados con éxito."
            color = "#10B981"
        self.finalizar_interfaz_descarga(texto, color)
        self.btn_cola_iniciar.configure(state="normal")
        self.actualizar_preview_cola()

    # ------------------------------------------------------------------
    # CIERRE DE APLICACIÓN
    # ------------------------------------------------------------------
    def cerrar_aplicacion_limpia(self):
        self.esta_cerrando = True
        self.evento_cancelar.set()
        self.destroy()
        sys.exit(0)


# ----------------------------------------------------------------------
# NUEVO v8.1: MODO CLI (sin interfaz gráfica)
# ----------------------------------------------------------------------
def ejecutar_modo_cli():
    """Punto de entrada para uso por línea de comandos / scripts. Reutiliza
    las funciones de módulo (sanear_nombre_archivo, transcribir_audio,
    escribir_nota_markdown) para no duplicar lógica frente a la GUI."""
    parser = argparse.ArgumentParser(
        prog="youtube_downloader_corregido.py",
        description="YTDownloader Kadir -- modo CLI (sin interfaz gráfica).",
    )
    parser.add_argument("url", help="URL del video o playlist de YouTube")
    parser.add_argument(
        "-o",
        "--output",
        default=os.path.join(os.path.expanduser("~"), "Downloads"),
        help="Carpeta de destino",
    )
    parser.add_argument(
        "--audio", action="store_true", help="Descargar solo audio (MP3)"
    )
    parser.add_argument(
        "--quality",
        default="best",
        help="Altura máxima de video, ej. 1080, 720, 480 (ignorado con --audio)",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Generar transcripción con Whisper e incluirla en la nota",
    )
    parser.add_argument(
        "--transcribe-only",
        action="store_true",
        help="Solo transcribir: descarga audio ligero, transcribe y borra el audio",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small"],
        help="Modelo de Whisper a usar",
    )
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    ruta_ffmpeg = detectar_ffmpeg()

    if args.transcribe_only or args.audio:
        formato = "bestaudio/best"
    elif args.quality != "best":
        formato = (
            f"bestvideo[height<={args.quality}]+bestaudio/best[height<={args.quality}]"
        )
    else:
        formato = "bestvideo+bestaudio/best"

    postprocessors = []
    if args.audio and not args.transcribe_only:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        )

    ydl_opts = {
        "outtmpl": os.path.join(args.output, "%(title).120s.%(ext)s"),
        "format": formato,
        "quiet": False,
        "no_warnings": True,
        "retries": 5,
        "ffmpeg_location": ruta_ffmpeg,
        "postprocessors": postprocessors,
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if not args.audio and not args.transcribe_only:
        ydl_opts["merge_output_format"] = "mp4"

    print(f"🔎 Analizando: {args.url}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(args.url, download=True)
    except DownloadError as e:
        print(f"❌ Error de descarga: {e}", file=sys.stderr)
        sys.exit(1)

    entries = info.get("entries") if info.get("_type") == "playlist" else [info]
    for entry in entries:
        if not entry:
            continue
        titulo = entry.get("title", "Video")
        video_id = entry.get("id", "")
        canal = entry.get("uploader", "Desconocido")
        dur_str = entry.get("duration_string", "N/A")
        dur_sec = entry.get("duration") or 0
        raw_date = entry.get("upload_date", "") or ""
        fecha = (
            f"{raw_date[6:8]}/{raw_date[4:6]}/{raw_date[0:4]}"
            if len(raw_date) == 8
            else "N/A"
        )
        desc = entry.get("description", "")
        capitulos = entry.get("chapters", [])
        url_final = (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else args.url
        )

        transcripcion = None
        if args.transcribe or args.transcribe_only:
            rd = entry.get("requested_downloads")
            ruta_archivo = rd[0].get("filepath") if rd else None
            if ruta_archivo and os.path.exists(ruta_archivo):
                print(f"🎙️ Transcribiendo: {titulo} (modelo={args.whisper_model})...")
                transcripcion = transcribir_audio(ruta_archivo, args.whisper_model)
                if transcripcion is None:
                    transcripcion = "*(No se pudo generar la transcripción: instala `faster-whisper` u `openai-whisper`.)*"
                if args.transcribe_only:
                    try:
                        os.remove(ruta_archivo)
                    except Exception:
                        pass

        ruta_nota = escribir_nota_markdown(
            args.output,
            titulo,
            video_id,
            canal,
            fecha,
            dur_str,
            dur_sec,
            url_final,
            capitulos,
            desc,
            transcripcion,
        )
        print(f"✅ Nota generada: {ruta_nota}")

    print("🏁 Proceso finalizado.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ejecutar_modo_cli()
    else:
        app = YoutubeUniversalDownloader()
        app.mainloop()
