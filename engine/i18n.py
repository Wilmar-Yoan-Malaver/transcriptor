"""Textos que el motor y la ventana le muestran al usuario, en español e inglés.

El idioma se elige en la app (Configuración › General). La ventana lo fija con set_language()
y se lo pasa al motor al arrancarlo (variable TRANSCRIPTOR_LANG) y cada vez que cambia.
"""

import os

LANGS = ("es", "en")
DEFAULT = "es"

MESSAGES = {
    "es": {
        # motor
        "engine.loading": "Cargando motor…",
        "engine.starting": "Iniciando motor…",
        "engine.ready": "Motor listo",
        "engine.stopped": "El motor se detuvo",
        "engine.unknown_cmd": "Orden desconocida: {cmd}",
        # grabación
        "rec.busy": "Ya hay una grabación en curso.",
        "rec.engine_starting": "El motor todavía se está iniciando…",
        "rec.window_closed": "Esa ventana ya se cerró. Elige otra.",
        "rec.audio_only_needs_source": "Con «Solo audio» elige al menos el micrófono o el audio del sistema.",
        "rec.start_failed": "No se pudo iniciar la grabación: {error}",
        "rec.nothing": "No se grabó nada.",
        "rec.enable_failed_mic": "No se pudo activar el micrófono: {error}",
        "rec.enable_failed_sys": "No se pudo activar el audio del sistema: {error}",
        "rec.no_device": "No hay un dispositivo elegido en Configuración › Audio.",
        "rec.audio_error": "Audio ({source}): {error}",
        "rec.video_error": "Video: {error}",
        "rec.merge_failed": "No se pudo unir el video y el audio{detail}. "
                            "Se guardaron por separado para no perder la grabación.",
        "rec.merge_timeout": "ffmpeg no terminó en {minutes} min",
        "rec.folder_blocked": "Windows no dejó guardar en {folder} ({error}). La grabación está a salvo en "
                              "{path}. Suele ser el acceso controlado a carpetas "
                              "(protección contra ransomware).",
        "folder.allow_failed": "Windows no agregó Transcriptor a las aplicaciones permitidas.",
        "folder.move_failed": "No se pudo mover la grabación a {folder}: {error}",
        "folder.nothing": "No hay grabaciones pendientes de mover.",
        "rec.file_name": "Grabación {stamp}",
        "rec.screen_label": "Pantalla {n}  ({w}×{h})",
        "rec.screen_primary": "  · principal",
        "rec.confirm_quit": "Hay una grabación en curso. ¿Detenerla, guardarla y salir?",
        "rec.discard_title": "Descartar grabación",
        "rec.discard_text": "¿Descartar esta grabación? No se guardará nada.",
        "rec.finish_before_restart": "Termina la grabación antes de reiniciar el motor.",
        # transcripción
        "tx.busy": "Ya hay una transcripción en curso.",
        "tx.connecting_youtube": "Conectando con YouTube…",
        "tx.download_failed": "No se pudo descargar el audio.",
        "tx.loading_model": "Cargando el modelo «{name}»…",
        "tx.loading_model_first": "Cargando el modelo «{name}» (la primera vez se descarga)…",
        "tx.preparing_audio": "Preparando audio…",
        "tx.too_short": "El archivo no tiene audio o es demasiado corto.",
        "tx.looking_for_speech": "Buscando voz en el audio…",
        "tx.transcribing": "Transcribiendo…",
        "tx.quiet": "Transcribiendo… ({pos} de {total}) · hace {seconds} s sin texto nuevo: "
                    "partes sin voz o con ruido",
        "tx.ffmpeg_failed": "ffmpeg falló",
        "live.transcribing": "Transcribiendo en vivo",
        "live.finishing": "Terminando la transcripción en vivo…",
        "live.error": "Error en vivo: {error}",
        "live.unavailable": "Ya no está disponible la transcripción en vivo.",
        # archivos
        "file.rename_outside": "Solo se pueden renombrar archivos de la carpeta de grabaciones.",
        "file.name_empty": "El nombre no puede quedar vacío.",
        "file.name_too_long": "El nombre puede tener como máximo {max} caracteres.",
        "file.name_reserved": "Ese nombre está reservado por Windows.",
        "file.name_exists": "Ya existe un archivo con ese nombre.",
        "file.rename_failed": "No se pudo renombrar: {error}",
        "file.delete_outside": "El archivo ya no existe o no es de la carpeta de grabaciones.",
        "file.delete_failed": "No se pudo eliminar (¿está abierto en otro programa?).",
        "file.media_types": "Video o audio",
        "file.all_types": "Todos los archivos",
        "app.shortcut_description": "Graba, transcribe y comparte",
    },
    "en": {
        "engine.loading": "Loading engine…",
        "engine.starting": "Starting engine…",
        "engine.ready": "Engine ready",
        "engine.stopped": "The engine stopped",
        "engine.unknown_cmd": "Unknown command: {cmd}",
        "rec.busy": "A recording is already in progress.",
        "rec.engine_starting": "The engine is still starting…",
        "rec.window_closed": "That window was closed. Choose another one.",
        "rec.audio_only_needs_source": "With “Audio only”, choose at least the microphone "
                                       "or the system audio.",
        "rec.start_failed": "Couldn't start the recording: {error}",
        "rec.nothing": "Nothing was recorded.",
        "rec.enable_failed_mic": "Couldn't turn on the microphone: {error}",
        "rec.enable_failed_sys": "Couldn't turn on the system audio: {error}",
        "rec.no_device": "No device is selected in Settings › Audio.",
        "rec.audio_error": "Audio ({source}): {error}",
        "rec.video_error": "Video: {error}",
        "rec.merge_failed": "Couldn't merge the video and audio{detail}. "
                            "They were saved separately so the recording isn't lost.",
        "rec.merge_timeout": "ffmpeg didn't finish within {minutes} min",
        "rec.folder_blocked": "Windows didn't allow saving to {folder} ({error}). "
                              "The recording is safe in {path}. "
                              "This is usually Controlled folder access (ransomware protection).",
        "folder.allow_failed": "Windows didn't add Transcriptor to the allowed apps.",
        "folder.move_failed": "Couldn't move the recording to {folder}: {error}",
        "folder.nothing": "There are no recordings waiting to be moved.",
        "rec.file_name": "Recording {stamp}",
        "rec.screen_label": "Screen {n}  ({w}×{h})",
        "rec.screen_primary": "  · primary",
        "rec.confirm_quit": "A recording is in progress. Stop it, save it and quit?",
        "rec.discard_title": "Discard recording",
        "rec.discard_text": "Discard this recording? Nothing will be saved.",
        "rec.finish_before_restart": "Finish the recording before restarting the engine.",
        "tx.busy": "A transcription is already in progress.",
        "tx.connecting_youtube": "Connecting to YouTube…",
        "tx.download_failed": "Couldn't download the audio.",
        "tx.loading_model": "Loading the “{name}” model…",
        "tx.loading_model_first": "Loading the “{name}” model (downloaded the first time)…",
        "tx.preparing_audio": "Preparing audio…",
        "tx.too_short": "The file has no audio or is too short.",
        "tx.looking_for_speech": "Looking for speech in the audio…",
        "tx.transcribing": "Transcribing…",
        "tx.quiet": "Transcribing… ({pos} of {total}) · no new text for {seconds} s: "
                    "parts without speech or with noise",
        "tx.ffmpeg_failed": "ffmpeg failed",
        "live.transcribing": "Transcribing live",
        "live.finishing": "Finishing the live transcription…",
        "live.error": "Live error: {error}",
        "live.unavailable": "The live transcription is no longer available.",
        "file.rename_outside": "Only files in the recordings folder can be renamed.",
        "file.name_empty": "The name can't be empty.",
        "file.name_too_long": "The name can be at most {max} characters long.",
        "file.name_reserved": "That name is reserved by Windows.",
        "file.name_exists": "A file with that name already exists.",
        "file.rename_failed": "Couldn't rename: {error}",
        "file.delete_outside": "The file no longer exists or isn't in the recordings folder.",
        "file.delete_failed": "Couldn't delete it (is it open in another program?).",
        "file.media_types": "Video or audio",
        "file.all_types": "All files",
        "app.shortcut_description": "Record, transcribe and share",
    },
}

_lang = os.environ.get("TRANSCRIPTOR_LANG") if os.environ.get("TRANSCRIPTOR_LANG") in LANGS else DEFAULT


def set_language(lang):
    """Cambia el idioma de los textos. Un valor desconocido deja el idioma por defecto."""
    global _lang
    _lang = lang if lang in LANGS else DEFAULT


def language():
    return _lang


def tr(key, **values):
    """Texto en el idioma actual, con {marcadores} reemplazados: tr("file.name_too_long", max=150)."""
    text = MESSAGES[_lang].get(key) or MESSAGES[DEFAULT][key]
    return text.format(**values) if values else text
