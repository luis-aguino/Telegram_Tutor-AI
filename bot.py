import os
import re
import time
import asyncio
import threading
import tempfile
import requests
import edge_tts
from http.server import HTTPServer, BaseHTTPRequestHandler

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Voz americana natural y profesional
VOICE_EN = "en-US-JennyNeural"

SYSTEM_PROMPT = """Eres un tutor de inglés amigable, paciente y motivador llamado "Tutor AI". 
Tu misión es ayudar a hispanohablantes a aprender inglés americano.

REGLAS:
- Siempre responde en ESPAÑOL, pero usa el inglés americano para enseñar.
- Corrige los errores del usuario con amabilidad.
- Usa emojis para hacer las conversaciones más amenas.
- Adapta el nivel al usuario (principiante, intermedio o avanzado).
- Si hay error: ❌ Error → ✅ Correcto.
- Mantén las respuestas concisas (máximo 200 palabras).

MUY IMPORTANTE - Al final de CADA respuesta incluye siempre esta sección:
🔊 AUDIO: [escribe aquí en inglés americano la frase o corrección completa que el usuario debe escuchar y practicar]

Ejemplos de la sección AUDIO:
- Si corregiste: 🔊 AUDIO: The correct way to say it is: I want to go to the store.
- Si enseñaste vocabulario: 🔊 AUDIO: Here are today's words: apple, house, beautiful.
- Si diste ejercicio: 🔊 AUDIO: Repeat after me: How are you doing today? I'm doing great, thank you!
- Si el usuario habló bien: 🔊 AUDIO: Great job! You said it perfectly: I would like a cup of coffee, please.
"""

user_histories = {}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo!")

    def log_message(self, format, *args):
        pass


def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def send_message(chat_id, text):
    requests.post(f"{TELEGRAM_BASE}/sendMessage", json={
        "chat_id": chat_id,
        "text": text
    })


def send_typing(chat_id):
    requests.post(f"{TELEGRAM_BASE}/sendChatAction", json={
        "chat_id": chat_id,
        "action": "typing"
    })


def send_voice_file(chat_id, filepath):
    with open(filepath, "rb") as audio:
        requests.post(
            f"{TELEGRAM_BASE}/sendVoice",
            data={"chat_id": chat_id},
            files={"voice": audio}
        )


async def text_to_speech_async(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def speak_english(chat_id, text):
    """Genera audio en inglés americano y lo envía."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            output_path = f.name
        asyncio.run(text_to_speech_async(text, VOICE_EN, output_path))
        send_voice_file(chat_id, output_path)
        os.unlink(output_path)
    except Exception as e:
        print(f"Error en TTS: {e}")


def extract_audio_phrase(reply):
    """Extrae la frase en inglés marcada con 🔊 AUDIO: ..."""
    match = re.search(r"🔊 AUDIO:\s*(.+)", reply)
    if match:
        return match.group(1).strip()
    return None


def transcribe_voice(file_id):
    """Transcribe audio con Groq Whisper."""
    try:
        file_info = requests.get(f"{TELEGRAM_BASE}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        audio_data = requests.get(file_url).content

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        with open(temp_path, "rb") as audio_file:
            response = requests.post(
                GROQ_WHISPER_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", audio_file, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "en"}
            )
        os.unlink(temp_path)

        data = response.json()
        print(f"Whisper: {data}")
        return data.get("text", "")
    except Exception as e:
        print(f"Error transcribiendo: {e}")
        return ""


def ask_groq(history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    response = requests.post(
        GROQ_CHAT_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "max_tokens": 500
        }
    )
    data = response.json()
    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    elif "error" in data:
        return f"Error: {data['error'].get('message', 'Error desconocido')}"
    return "Respuesta inesperada."


def process_message(chat_id, user_id, text, is_voice=False):
    if user_id not in user_histories:
        user_histories[user_id] = []

    history = user_histories[user_id]

    if is_voice:
        content = f"[El usuario envió un mensaje de VOZ en inglés. Transcripción: '{text}']. Corrígelo si hay errores, felicítalo si estuvo bien."
    else:
        content = text

    history.append({"role": "user", "content": content})
    send_typing(chat_id)
    reply = ask_groq(history)
    history.append({"role": "assistant", "content": reply})
    user_histories[user_id] = history[-20:]

    # Texto en español (sin la línea de AUDIO)
    text_reply = re.sub(r"🔊 AUDIO:.*", "", reply).strip()
    send_message(chat_id, text_reply)

    # Audio en inglés americano
    english_audio = extract_audio_phrase(reply)
    if english_audio:
        send_message(chat_id, "🇺🇸 Escucha la pronunciación:")
        speak_english(chat_id, english_audio)


def handle_update(update):
    if "message" not in update:
        return

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = str(chat_id)

    # Mensaje de VOZ
    if "voice" in message:
        send_message(chat_id, "🎤 Escuché tu mensaje, analizando...")
        file_id = message["voice"]["file_id"]
        transcription = transcribe_voice(file_id)

        if transcription:
            send_message(chat_id, f"📝 Escuché: {transcription}")
            process_message(chat_id, user_id, transcription, is_voice=True)
        else:
            send_message(chat_id, "No pude entender el audio. Intenta de nuevo.")
        return

    # Mensaje de TEXTO
    text = message.get("text", "")
    if not text:
        return

    if text == "/start":
        user_histories[user_id] = []
        send_message(chat_id,
            "Hola! Soy tu Tutor de Ingles Americano AI 🎓🇺🇸\n\n"
            "Puedes:\n"
            "🎤 Enviarme mensajes de VOZ en ingles y te corrijo\n"
            "📝 Escribirme en espanol y te enseno como decirlo\n"
            "✍️ Escribirme en ingles y te corrijo los errores\n"
            "📚 Pedir ejercicios con /ejercicio\n\n"
            "Escucharas la pronunciacion en ingles americano natural! 🔊\n\n"
            "Por donde quieres empezar? 😊"
        )
        return

    if text == "/reset":
        user_histories[user_id] = []
        send_message(chat_id, "Conversacion reiniciada! Que quieres aprender hoy?")
        return

    if text == "/help":
        send_message(chat_id,
            "Comandos disponibles:\n\n"
            "/start - Iniciar el bot\n"
            "/reset - Borrar historial\n"
            "/ejercicio - Recibir un ejercicio\n"
            "/help - Ver esta ayuda\n\n"
            "Tambien puedes enviarme mensajes de VOZ 🎤"
        )
        return

    if text == "/ejercicio":
        text = "Dame un ejercicio corto y practico de ingles americano para practicar ahora."

    process_message(chat_id, user_id, text, is_voice=False)


def main():
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    print("Bot iniciado con voz americana!")

    offset = 0
    while True:
        try:
            response = requests.get(
                f"{TELEGRAM_BASE}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            data = response.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                handle_update(update)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
