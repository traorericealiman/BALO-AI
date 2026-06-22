from flask import Flask, request, Response, send_file
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import requests
import tempfile
import os

# ================= LOAD ENV =================
load_dotenv()

app = Flask(__name__)

DJELIA_API_KEY = os.getenv("DJELIA_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

BASE_URL = os.getenv("BASE_URL")

# ================= API URLs =================
TRANSCRIBE_URL = "https://djelia.cloud/api/v1/models/transcribe"
TRANSLATE_URL = "https://djelia.cloud/api/v1/models/translate"
TTS_URL = "https://djelia.cloud/api/v2/models/tts"

DJELIA_HEADERS = {
    "x-api-key": DJELIA_API_KEY
}

GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
)

# ================= ENTRY POINT TWILIO =================

@app.route("/voice", methods=["GET", "POST"])
def voice():
    response = VoiceResponse()

    response.say(
        "Bonjour, parlez après le bip.",
        language="fr-FR"
    )

    response.record(
        max_length=20,
        play_beep=True,
        action="/handle-recording"
    )

    return Response(str(response), mimetype="text/xml")

# ================= HANDLE RECORDING =================

@app.route("/handle-recording", methods=["POST"])
def handle_recording():

    recording_url = request.form.get("RecordingUrl") + ".wav"

    # télécharger audio Twilio
    audio = requests.get(
        recording_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.write(audio.content)
    tmp.close()

    # ================= 1. TRANSCRIPTION DJELIA =================
    with open(tmp.name, "rb") as f:
        res = requests.post(
            TRANSCRIBE_URL,
            headers=DJELIA_HEADERS,
            files={"file": f},
            params={"translate_to_french": True}
        )

    text_dioula = res.json().get("text", "")

    # ================= 2. GEMINI (ASSISTANT COMMERCIAL) =================
    prompt = f"""
Tu es un assistant commercial intelligent en Afrique de l'Ouest.

Réponds de manière courte, claire et utile.

Message client :
{text_dioula}
"""

    gemini = requests.post(
        GEMINI_URL,
        json={"contents": [{"parts": [{"text": prompt}]}]}
    )

    if gemini.status_code == 200:
        reply_fr = gemini.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        reply_fr = "Je n'ai pas compris votre demande."

    # ================= 3. TRADUCTION FR -> DIOULA =================
    tr = requests.post(
        TRANSLATE_URL,
        headers=DJELIA_HEADERS,
        json={
            "source": "fra_Latn",
            "target": "bam_Latn",
            "text": reply_fr
        }
    )

    reply_dioula = tr.json().get("text", reply_fr)

    # ================= 4. TTS DIOULA =================
    tts = requests.post(
        TTS_URL,
        headers=DJELIA_HEADERS,
        json={"text": reply_dioula}
    )

    audio_path = "/tmp/reply.mp3"

    with open(audio_path, "wb") as f:
        f.write(tts.content)

    # cleanup audio input
    os.remove(tmp.name)

    # ================= RESPONSE TWILIO =================
    response = VoiceResponse()

    response.say("Voici votre réponse.")

    response.play(f"{BASE_URL}/audio")

    return Response(str(response), mimetype="text/xml")

# ================= AUDIO ENDPOINT =================

@app.route("/audio", methods=["GET"])
def audio():
    path = "/tmp/reply.mp3"

    if os.path.exists(path):
        return send_file(path, mimetype="audio/mpeg")

    return "No audio found", 404


# ================= RUN APP =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)