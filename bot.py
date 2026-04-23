import os
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

SYSTEM_PROMPT = """Eres un tutor de inglés amigable, paciente y motivador llamado "Tutor AI". 
Tu misión es ayudar a hispanohablantes a aprender inglés de forma práctica y divertida.

REGLAS:
- Siempre responde en ESPAÑOL, pero usa el inglés para enseñar.
- Corrige los errores del usuario con amabilidad, sin hacerlos sentir mal.
- Cuando el usuario escriba en inglés, corrígelo si hay errores y explica por qué.
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
- Pronunciación (descripción fonética)
- Conversación simulada
- Verbos irregulares
- Tiempos verbales
"""

# Historial por usuario
user_histories = {}


def ask_gemini(history: list) -> str:
    """Llama a la API de Gemini usando requests."""
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": history
    }
    response = requests.post(GEMINI_URL, json=payload)
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu *Tutor de Inglés AI* 🎓\n\n"
        "Estoy aquí para ayudarte a aprender inglés de forma fácil y divertida.\n\n"
        "Puedes:\n"
        "📝 Escribirme en español y te enseño cómo decirlo en inglés\n"
        "🗣️ Escribirme en inglés y te corrijo si hay errores\n"
        "📚 Pedirme ejercicios o explicaciones de gramática\n\n"
        "¿Por dónde quieres empezar? 😊",
        parse_mode="Markdown"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("🔄 ¡Conversación reiniciada! ¿Qué quieres aprender hoy?")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Comandos disponibles:*\n\n"
        "/start — Iniciar o reiniciar el bot\n"
        "/reset — Borrar el historial de conversación\n"
        "/ejercicio — Recibir un ejercicio práctico\n"
        "/help — Ver esta ayuda\n\n"
        "También puedes simplemente escribirme lo que quieras aprender 💬",
        parse_mode="Markdown"
    )


async def ejercicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    history = user_histories.get(user_id, [])

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    msg = "Dame un ejercicio corto y práctico de inglés para practicar ahora."
    history.append({"role": "user", "parts": [{"text": msg}]})
    reply = ask_gemini(history)
    history.append({"role": "model", "parts": [{"text": reply}]})
    user_histories[user_id] = history[-20:]

    await update.message.reply_text(reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    history = user_histories[user_id]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history.append({"role": "user", "parts": [{"text": user_text}]})
    reply = ask_gemini(history)
    history.append({"role": "model", "parts": [{"text": reply}]})
    user_histories[user_id] = history[-20:]

    await update.message.reply_text(reply)


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ejercicio", ejercicio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot iniciado correctamente!")
    app.run_polling()


if __name__ == "__main__":
    main()
