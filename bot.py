import os
import time
import threading
import requests
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from gtts import gTTS

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

SYSTEM_PROMPT = """Eres un tutor de inglés amigable, paciente y motivador llamado "Tutor AI". 
Tu misión es ayudar a hispanohablantes a aprender inglés de forma práctica y divertida.

REGLAS:
- Siempre responde en ESPAÑOL, pero usa el inglés para enseñar.
- Corrige los errores del usuario con amabilidad, sin hacerlos sentir mal.
- Cuando el usuario escriba o hable en inglés, corrígelo si hay errores y explica por qué.
- Cuando el usuario hable en inglés, comenta también su pronunciación basándote en lo transcrito.
- Usa emojis para hacer las conversaciones más amenas.
- Adapta el nivel de dificultad al usuario (detecta si es principiante, intermedio o avanzado).
- Da ejercicios prácticos cuando sea apropiado.
- Si el usuario comete un error, muestra la forma correcta con formato: ❌ Error → ✅ Correcto.
- Celebra los logros del usuario con entusiasmo.
- Mantén las respuestas concisas (máximo 200 palabras) para no abrumar al usuario.

TEMAS QUE PUEDES ENSEÑAR:
- Vocabulario cotidiano
- Gramática básica y avanzada
- Frases útiles para viajes, trabajo, etc.
- Conversación simulada
- Verbos irregulares
- Tiempos verbales
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


def send_voice(chat_id, text):
    """Convierte texto a voz y lo envía como mensaje de voz."""
    try:
        tts = gTTS(text=text, lang="es", slow=False)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tts.save(f.name)
            with open(f.name, "rb") as audio:
                requests.post(
                    f"{TELEGRAM_BASE}/sendVoice",
                    data={"chat_id": chat_id},
                    files={"voice": audio}
                )
        os.unlink(f.name)
    except Exception as e:
        print(f"Error enviando voz: {e}")


def transcribe_voice(file_id):
    """Descarga el audio de Telegram y lo transcribe con Groq Whisper."""
    try:
        # Obtener la URL del archivo
        file_info = requests.get(f"{TELEGRAM_BASE}/getFile?file_id={file_id}").json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

        # Descargar el audio
        audio_data = requests.get(file_url).content

        # Transcribir con Groq Whisper
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_data)
            f.flush()
            with open(f.name, "rb") as audio_file:
                response = requests.post(
                    GROQ_WHISPER_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    files={"file": ("audio.ogg", audio_file, "audio/ogg")},
                    data={"model": "whisper-large-v3"}
                )
        os.unlink(f.name)

        data = response.json()
        print(f"Whisper response: {data}")
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
    """Procesa el mensaje y responde."""
    if user_id not in user_histories:
        user_histories[user_id] = []

    history = user_histories[user_id]

    if is_voice:
        content = f"[El usuario envió un mensaje de VOZ. Transcripción: '{text}']. Corrígelo si hay errores en inglés y felicítalo si estuvo bien."
    else:
        content = text

    history.append({"role": "user", "content": content})

    send_typing(chat_id)
    reply = ask_groq(history)

    history.append({"role": "assistant", "content": reply})
    user_histories[user_id] = history[-20:]

    # Siempre envía texto
    send_message(chat_id, reply)

    # Si el mensaje fue de voz, también responde con voz
    if is_voice:
        send_voice(chat_id, reply)


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
            send_message(chat_id, f"📝 Escuché: *{transcription}*")
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
            "Hola! Soy tu Tutor de Ingles AI 🎓\n\n"
            "Puedes:\n"
            "🎤 Enviarme mensajes de VOZ en ingles y te corrijo\n"
            "📝 Escribirme en espanol y te enseno como decirlo en ingles\n"
            "✍️ Escribirme en ingles y te corrijo si hay errores\n"
            "📚 Pedir ejercicios con /ejercicio\n\n"
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
        text = "Dame un ejercicio corto y practico de ingles para practicar ahora."

    process_message(chat_id, user_id, text, is_voice=False)


def main():
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    print("Servidor web iniciado!")
    print("Bot iniciado con voz!")

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
